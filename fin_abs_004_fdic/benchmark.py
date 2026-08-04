from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .model import (
    BASELINES,
    CHALLENGERS,
    bank_cluster_bootstrap,
    performance_metrics,
    predict,
    select_method,
    select_threshold,
    train_models,
)
from .panel import FEATURE_COLUMNS, MONOTONIC_DIRECTIONS, build_panel, canonical

SCHEMA = "fin-abs-004/fdic-sealed-distress-benchmark/1"


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def relative_improvement(baseline: float, challenger: float) -> float | None:
    if not np.isfinite(baseline) or baseline == 0:
        return None
    return float((challenger - baseline) / abs(baseline))


def relative_cost_reduction(baseline: float, challenger: float) -> float | None:
    if not np.isfinite(baseline) or baseline <= 0:
        return None
    return float((baseline - challenger) / baseline)


def subset_metrics(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    if frame.empty:
        return {"rows": 0, "positive_rows": 0, "metrics": None}
    return {
        "rows": int(len(frame)),
        "positive_rows": int(frame["label"].sum()),
        "metrics": performance_metrics(frame, probabilities, threshold),
    }


def benchmark(panel_path: Path, panel_report_path: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    panel_report = json.loads(panel_report_path.read_text(encoding="utf-8"))
    panel = pd.read_csv(panel_path, low_memory=False)
    panel["REPDTE"] = pd.to_datetime(panel["REPDTE"], errors="raise")
    panel["CERT"] = pd.to_numeric(panel["CERT"], errors="raise").astype(int)
    panel["label"] = pd.to_numeric(panel["label"], errors="raise").astype(int)
    panel = panel.sort_values(["split", "REPDTE", "CERT"]).reset_index(drop=True)
    train = panel.loc[panel["split"] == "train"].copy()
    validation = panel.loc[panel["split"] == "validation"].copy()
    test = panel.loc[panel["split"] == "test"].copy()
    if min(int(train["label"].sum()), int(validation["label"].sum()), int(test["label"].sum())) <= 0:
        raise ValueError("one or more FDIC splits contain no positive labels")

    bundle = train_models(train)
    validation_predictions = predict(bundle, validation)
    test_predictions = predict(bundle, test)

    validation_thresholds: dict[str, dict[str, float | int]] = {}
    validation_metrics: dict[str, dict[str, Any]] = {}
    test_metrics: dict[str, dict[str, Any]] = {}
    for method in (*BASELINES, *CHALLENGERS):
        threshold = select_threshold(
            validation["label"].to_numpy(dtype=int),
            validation_predictions[method],
        )
        validation_thresholds[method] = threshold
        validation_metrics[method] = performance_metrics(
            validation,
            validation_predictions[method],
            float(threshold["threshold"]),
        )
        test_metrics[method] = performance_metrics(
            test,
            test_predictions[method],
            float(threshold["threshold"]),
        )
    selected_baseline = select_method(validation_metrics, BASELINES)
    selected_challenger = select_method(validation_metrics, CHALLENGERS)
    baseline_test = test_metrics[selected_baseline]
    challenger_test = test_metrics[selected_challenger]
    baseline_threshold = float(validation_thresholds[selected_baseline]["threshold"])
    challenger_threshold = float(validation_thresholds[selected_challenger]["threshold"])

    test_year = test["REPDTE"].dt.year
    crisis_mask = test_year.isin([2009, 2010]).to_numpy()
    noncrisis_mask = (test_year == 2011).to_numpy()
    crisis = {
        "baseline": subset_metrics(
            test.loc[crisis_mask],
            test_predictions[selected_baseline][crisis_mask],
            baseline_threshold,
        ),
        "challenger": subset_metrics(
            test.loc[crisis_mask],
            test_predictions[selected_challenger][crisis_mask],
            challenger_threshold,
        ),
    }
    noncrisis = {
        "baseline": subset_metrics(
            test.loc[noncrisis_mask],
            test_predictions[selected_baseline][noncrisis_mask],
            baseline_threshold,
        ),
        "challenger": subset_metrics(
            test.loc[noncrisis_mask],
            test_predictions[selected_challenger][noncrisis_mask],
            challenger_threshold,
        ),
    }
    bootstrap = bank_cluster_bootstrap(
        test,
        test_predictions[selected_baseline],
        test_predictions[selected_challenger],
        baseline_threshold,
        challenger_threshold,
    )

    ap_relative = relative_improvement(
        float(baseline_test["average_precision"]),
        float(challenger_test["average_precision"]),
    )
    cost_reduction = relative_cost_reduction(
        float(baseline_test["cost_per_row"]),
        float(challenger_test["cost_per_row"]),
    )

    def subset_cost_improves(section: dict[str, Any]) -> bool:
        baseline = section["baseline"]
        challenger = section["challenger"]
        positives = min(
            int(baseline["positive_rows"]), int(challenger["positive_rows"])
        )
        if positives < 20:
            return True
        return (
            challenger["metrics"] is not None
            and baseline["metrics"] is not None
            and float(challenger["metrics"]["cost_per_row"])
            < float(baseline["metrics"]["cost_per_row"])
        )

    panel_contract = panel_report["payload"]
    python_gates = {
        "official_panel_hash_exact": sha_file(panel_path)
        == panel_contract["evaluation_panel"]["feature_file_sha256"],
        "zero_bank_quarter_duplicates": int(
            panel.duplicated(["CERT", "REPDTE"]).sum()
        )
        == 0,
        "zero_future_window_overlap": (
            train["REPDTE"].max() < validation["REPDTE"].min()
            and validation["REPDTE"].max() < test["REPDTE"].min()
        ),
        "validation_positive_rows_at_least_20": int(validation["label"].sum()) >= 20,
        "test_positive_rows_at_least_100": int(test["label"].sum()) >= 100,
        "challenger_auprc_relative_improvement_at_least_5pct": (
            ap_relative is not None and ap_relative >= 0.05
        ),
        "challenger_recall_at_1pct_fpr_strictly_higher": float(
            challenger_test["recall_at_fpr_0_01"]
        )
        > float(baseline_test["recall_at_fpr_0_01"]),
        "challenger_brier_no_worse": float(challenger_test["brier"])
        <= float(baseline_test["brier"]),
        "challenger_calibration_no_worse": float(
            challenger_test["calibration_error_10bin"]
        )
        <= float(baseline_test["calibration_error_10bin"]),
        "challenger_expected_cost_reduction_at_least_5pct": (
            cost_reduction is not None and cost_reduction >= 0.05
        ),
        "bank_cluster_bootstrap_lower_bound_positive": float(
            bootstrap["lower_95"]
            if bootstrap["lower_95"] is not None
            else -np.inf
        )
        > 0.0,
        "crisis_cost_improves_if_evaluable": subset_cost_improves(crisis),
        "noncrisis_cost_improves_if_evaluable": subset_cost_improves(noncrisis),
    }
    candidate_pass = all(python_gates.values())

    prediction_rows: list[dict[str, Any]] = []
    for split_name, frame, predictions in (
        ("validation", validation, validation_predictions),
        ("test", test, test_predictions),
    ):
        for method in (*BASELINES, *CHALLENGERS):
            probabilities = predictions[method]
            for row, probability in zip(
                frame.itertuples(index=False), probabilities, strict=True
            ):
                prediction_rows.append(
                    {
                        "split": split_name,
                        "CERT": int(row.CERT),
                        "REPDTE": pd.Timestamp(row.REPDTE).date().isoformat(),
                        "label": int(row.label),
                        "days_to_failure": (
                            float(row.days_to_failure)
                            if pd.notna(row.days_to_failure)
                            else None
                        ),
                        "ASSET": float(row.ASSET),
                        "BKCLASS": str(row.BKCLASS),
                        "method": method,
                        "probability": float(probability),
                        "threshold": float(
                            validation_thresholds[method]["threshold"]
                        ),
                    }
                )
    predictions_path = output / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as handle:
        for row in sorted(
            prediction_rows,
            key=lambda value: (
                value["split"],
                value["method"],
                value["REPDTE"],
                value["CERT"],
            ),
        ):
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    transformer = bundle.transformer
    preprocessing = {
        "lower": transformer.lower,
        "upper": transformer.upper,
        "median": transformer.median,
        "mean": transformer.mean,
        "scale": transformer.scale,
        "output_columns": list(transformer.output_columns),
        "monotonic_constraints": list(transformer.monotonic_constraints),
    }
    preprocessing_path = output / "preprocessing.json"
    preprocessing_path.write_text(
        json.dumps(preprocessing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    payload = {
        "schema": SCHEMA,
        "source": {
            "panel_report_sha256": panel_report["sha256"],
            "panel_file_sha256": sha_file(panel_path),
            "panel_rows_sha256": panel_contract["evaluation_panel"][
                "panel_rows_sha256"
            ],
        },
        "protocol": {
            "features": list(FEATURE_COLUMNS),
            "monotonic_directions": MONOTONIC_DIRECTIONS,
            "baselines": list(BASELINES),
            "challengers": list(CHALLENGERS),
            "false_negative_cost": 100.0,
            "false_positive_cost": 1.0,
            "selection_rule": (
                "lowest validation cost; ties by higher AUPRC, lower Brier, method"
            ),
            "maximum_absolute_score_delta_after_full_independent_pass": 20,
        },
        "split_counts": panel_contract["evaluation_panel"]["split_counts"],
        "validation": {
            "thresholds": validation_thresholds,
            "metrics": validation_metrics,
            "selected_baseline": selected_baseline,
            "selected_challenger": selected_challenger,
        },
        "sealed_test": {
            "baseline": {"method": selected_baseline, "metrics": baseline_test},
            "challenger": {
                "method": selected_challenger,
                "metrics": challenger_test,
            },
            "auprc_relative_improvement": ap_relative,
            "expected_cost_reduction": cost_reduction,
            "crisis_2009_2010": crisis,
            "noncrisis_2011": noncrisis,
            "bank_cluster_bootstrap": bootstrap,
            "predictions_file": predictions_path.name,
            "predictions_file_sha256": sha_file(predictions_path),
            "preprocessing_file": preprocessing_path.name,
            "preprocessing_file_sha256": sha_file(preprocessing_path),
        },
        "python_gate_checks": python_gates,
        "performance_candidate_pass": candidate_pass,
        "independent_model_reimplementation": "PENDING",
        "status": (
            "CANDIDATE_PASS_PENDING_INDEPENDENT_MODEL_REPLAY"
            if candidate_pass
            else "FALSIFIED_OR_OPEN_ON_FDIC"
        ),
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": (
                "No absolute points are awarded until a separate implementation "
                "reconstructs labels, predictions and every non-compensable gate."
            ),
        },
    }
    payload_canonical = canonical(payload)
    report = {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest(),
    }
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--panel-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.panel, args.panel_report, args.output_dir)
    payload = report["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "selected_baseline": payload["validation"]["selected_baseline"],
                "selected_challenger": payload["validation"][
                    "selected_challenger"
                ],
                "test_auprc_baseline": payload["sealed_test"]["baseline"][
                    "metrics"
                ]["average_precision"],
                "test_auprc_challenger": payload["sealed_test"]["challenger"][
                    "metrics"
                ]["average_precision"],
                "cost_reduction": payload["sealed_test"][
                    "expected_cost_reduction"
                ],
                "bootstrap_lower_95": payload["sealed_test"][
                    "bank_cluster_bootstrap"
                ]["lower_95"],
                "report_sha256": report["sha256"],
                "absolute_score": 423,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
