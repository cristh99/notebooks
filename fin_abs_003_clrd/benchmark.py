from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .audit import audit, canonical, digest, normalized_frame
from .reserving import (
    BASELINE_METHODS,
    CHALLENGER_WEIGHTS,
    all_metrics,
    paired_entity_bootstrap,
    select_method,
)
from .reserving_v2 import predict_cases_v2, temporal_information_contract

SCHEMA = "fin-abs-003/clrd-sealed-benchmark/1"


def file_sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def safe_relative_improvement(baseline: float, challenger: float) -> float | None:
    if not np.isfinite(baseline) or baseline <= 0:
        return None
    return float((baseline - challenger) / baseline)


def benchmark(input_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    audited = audit(input_path)
    audit_report = {key: value for key, value in audited.items() if key != "cases"}
    if audit_report["payload"]["status"] != "PASS_DATA_AUDIT":
        raise ValueError("CLRD data audit must pass before benchmark execution")
    frame = normalized_frame(input_path)
    cases = audited["cases"]
    information = temporal_information_contract(frame)
    predictions = predict_cases_v2(frame, cases)
    if predictions.empty:
        raise ValueError("no CLRD predictions generated")
    selected = predictions.loc[predictions["split"].isin(["validation", "test"])].copy()
    selected = selected.sort_values(
        ["split", "method", "LOB", "GRCODE", "cutoff", "AccidentYear"]
    ).reset_index(drop=True)
    predictions_path = output / "predictions.csv"
    selected.to_csv(predictions_path, index=False, float_format="%.17g")

    validation_metrics = all_metrics(predictions, "validation")
    test_metrics = all_metrics(predictions, "test")
    baseline = select_method(validation_metrics, BASELINE_METHODS)
    challenger = select_method(
        validation_metrics, tuple(CHALLENGER_WEIGHTS)
    )
    baseline_test = test_metrics[baseline]
    challenger_test = test_metrics[challenger]
    relative_wape = safe_relative_improvement(
        float(baseline_test["wape"]), float(challenger_test["wape"])
    )
    line_comparison: dict[str, Any] = {}
    improved_lines = 0
    for lob in sorted(set(baseline_test["lob_wape"]) | set(challenger_test["lob_wape"])):
        base_value = baseline_test["lob_wape"].get(lob)
        challenger_value = challenger_test["lob_wape"].get(lob)
        improved = (
            base_value is not None
            and challenger_value is not None
            and float(challenger_value) < float(base_value)
        )
        improved_lines += int(improved)
        line_comparison[lob] = {
            "baseline_wape": base_value,
            "challenger_wape": challenger_value,
            "improved": improved,
        }
    test_predictions = predictions.loc[predictions["split"] == "test"]
    bootstrap = paired_entity_bootstrap(
        test_predictions, baseline, challenger
    )
    finite_predictions = bool(
        np.isfinite(selected["prediction"].to_numpy(dtype=float)).all()
        and (selected["prediction"] >= 0).all()
    )
    case_hash_exact = (
        digest(cases.to_dict(orient="records"))
        == audit_report["payload"]["cases"]["cases_sha256"]
    )
    python_gates = {
        "data_audit_pass": audit_report["payload"]["status"] == "PASS_DATA_AUDIT",
        "eligible_cases_at_least_5000": len(cases) >= 5000,
        "entity_disjoint_split": information["entity_sets_disjoint"],
        "zero_future_cell_usage": information["all_cutoffs_no_future"],
        "case_hash_exact": case_hash_exact,
        "finite_nonnegative_predictions": finite_predictions,
        "challenger_relative_wape_improvement_at_least_2pct": (
            relative_wape is not None and relative_wape >= 0.02
        ),
        "calibration_error_within_1pct": float(
            challenger_test["calibration_error"]
        )
        <= float(baseline_test["calibration_error"]) + 0.01,
        "p95_ape_within_5pct": float(challenger_test["p95_ape"])
        <= float(baseline_test["p95_ape"]) + 0.05,
        "improves_at_least_four_lines": improved_lines >= 4,
        "entity_bootstrap_lower_bound_positive": float(
            bootstrap["lower_95"]
            if bootstrap["lower_95"] is not None
            else -np.inf
        )
        > 0.0,
    }
    candidate_pass = all(python_gates.values())
    payload = {
        "schema": SCHEMA,
        "source": {
            "transport_sha256": audit_report["payload"]["source"][
                "transport_sha256"
            ],
            "audit_report_sha256": audit_report["sha256"],
            "cases_sha256": audit_report["payload"]["cases"]["cases_sha256"],
            "source_commit": audit_report["payload"]["source"]["source_commit"],
        },
        "protocol": {
            "cutoffs": [1994, 1995, 1996],
            "target_year": 1997,
            "baselines": list(BASELINE_METHODS),
            "challengers": list(CHALLENGER_WEIGHTS),
            "selection_rule": (
                "lowest validation WAPE; ties by calibration error, p95 APE, method"
            ),
            "maximum_absolute_score_delta_after_full_independent_pass": 20,
        },
        "information_contract": information,
        "validation": {
            "metrics": validation_metrics,
            "selected_baseline": baseline,
            "selected_challenger": challenger,
        },
        "sealed_test": {
            "baseline": {"method": baseline, "metrics": baseline_test},
            "challenger": {"method": challenger, "metrics": challenger_test},
            "relative_wape_improvement": relative_wape,
            "line_comparison": line_comparison,
            "improved_lines": improved_lines,
            "entity_bootstrap": bootstrap,
            "predictions_file": predictions_path.name,
            "predictions_file_sha256": file_sha(predictions_path),
        },
        "python_gate_checks": python_gates,
        "performance_candidate_pass": candidate_pass,
        "independent_prediction_reimplementation": "PENDING",
        "status": (
            "CANDIDATE_PASS_PENDING_INDEPENDENT_PREDICTION_REPLAY"
            if candidate_pass
            else "FALSIFIED_OR_OPEN_ON_CLRD"
        ),
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": (
                "No absolute points are awarded until a separate implementation "
                "reconstructs predictions and all non-compensable gates pass."
            ),
        },
    }
    payload_canonical = canonical(payload)
    report = {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest(),
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "validation_metrics.json").write_text(
        json.dumps(validation_metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "test_metrics.json").write_text(
        json.dumps(test_metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.input, args.output_dir)
    payload = report["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "selected_baseline": payload["validation"]["selected_baseline"],
                "selected_challenger": payload["validation"][
                    "selected_challenger"
                ],
                "test_relative_wape_improvement": payload["sealed_test"][
                    "relative_wape_improvement"
                ],
                "improved_lines": payload["sealed_test"]["improved_lines"],
                "bootstrap_lower_95": payload["sealed_test"][
                    "entity_bootstrap"
                ]["lower_95"],
                "report_sha256": report["sha256"],
                "absolute_score": payload["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
