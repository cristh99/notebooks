from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fin_abs_004_fdic.panel import FEATURE_COLUMNS, MONOTONIC_DIRECTIONS
from fin_abs_004_fdic.serialization import canonical_json

from .model import (
    BASELINES,
    CHALLENGERS,
    bank_cluster_bootstrap,
    calibration_parameters,
    fit_calibrators,
    performance_metrics,
    predict,
    select_method,
    select_threshold,
    split_validation_entities,
    train_models,
)
from .protocol import ABSOLUTE_SCORE, ENTITY_SPLIT_SEED, EXPECTED_BUCKET_RULE, WINDOWS

SCHEMA = "fin-abs-004b/fdic-sealed-rf-benchmark/1"
FALSE_NEGATIVE_COST = 100.0
FALSE_POSITIVE_COST = 1.0


def sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def relative_gain(baseline: float, challenger: float) -> float | None:
    if not np.isfinite(baseline) or baseline == 0:
        return None
    return float((challenger - baseline) / abs(baseline))


def relative_reduction(baseline: float, challenger: float) -> float | None:
    if not np.isfinite(baseline) or baseline <= 0:
        return None
    return float((baseline - challenger) / baseline)


def subset_metrics(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    if frame.empty:
        return {"rows": 0, "positive_rows": 0, "positive_entities": 0, "metrics": None}
    return {
        "rows": int(len(frame)),
        "positive_rows": int(frame["label"].sum()),
        "positive_entities": int(
            frame.loc[frame["label"] == 1, "CERT"].nunique()
        ),
        "metrics": performance_metrics(frame, probabilities, threshold),
    }


def benchmark(
    panel_path: Path,
    panel_report_path: Path,
    preflight_report_path: Path,
    output: Path,
    *,
    rf_trees: int = 600,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    panel_report = json.loads(panel_report_path.read_text(encoding="utf-8"))
    preflight_report = json.loads(preflight_report_path.read_text(encoding="utf-8"))
    panel_contract = panel_report["payload"]
    preflight_contract = preflight_report["payload"]
    panel_sha = sha_file(panel_path)

    if panel_contract["status"] != "PASS_ENTITY_SPLIT":
        raise ValueError("entity-disjoint panel did not pass")
    if preflight_contract["status"] != "PASS_PREFLIGHT":
        raise ValueError("preflight did not pass")
    if panel_sha != panel_contract["evaluation_panel"]["feature_file_sha256"]:
        raise ValueError("panel file hash does not match entity report")
    if panel_sha != preflight_contract["panel_file_sha256"]:
        raise ValueError("panel file hash does not match preflight report")
    if preflight_contract["panel_report_sha256"] != panel_report["sha256"]:
        raise ValueError("preflight is not bound to entity report")

    panel = pd.read_csv(panel_path, low_memory=False)
    panel["REPDTE"] = pd.to_datetime(panel["REPDTE"], errors="raise")
    panel["CERT"] = pd.to_numeric(panel["CERT"], errors="raise").astype(int)
    panel["label"] = pd.to_numeric(panel["label"], errors="raise").astype(int)
    panel = panel.sort_values(["split", "REPDTE", "CERT"]).reset_index(drop=True)
    train = panel.loc[panel["split"] == "train"].copy()
    validation = panel.loc[panel["split"] == "validation"].copy()
    test = panel.loc[panel["split"] == "test"].copy()

    calibration, selection, calibration_split = split_validation_entities(validation)
    bundle = train_models(train, rf_trees=rf_trees)
    bundle = fit_calibrators(bundle, calibration)
    selection_predictions = predict(bundle, selection)
    test_predictions = predict(bundle, test)

    selection_thresholds: dict[str, dict[str, float | int]] = {}
    selection_metrics: dict[str, dict[str, Any]] = {}
    test_metrics: dict[str, dict[str, Any]] = {}
    for method in (*BASELINES, *CHALLENGERS):
        threshold = select_threshold(
            selection["label"].to_numpy(dtype=int),
            selection_predictions[method],
        )
        selection_thresholds[method] = threshold
        selection_metrics[method] = performance_metrics(
            selection,
            selection_predictions[method],
            float(threshold["threshold"]),
        )
        test_metrics[method] = performance_metrics(
            test,
            test_predictions[method],
            float(threshold["threshold"]),
        )

    selected_baseline = select_method(selection_metrics, BASELINES)
    selected_challenger = select_method(selection_metrics, CHALLENGERS)
    baseline_test = test_metrics[selected_baseline]
    challenger_test = test_metrics[selected_challenger]
    baseline_threshold = float(selection_thresholds[selected_baseline]["threshold"])
    challenger_threshold = float(selection_thresholds[selected_challenger]["threshold"])

    by_year: dict[str, dict[str, Any]] = {}
    for year in (2012, 2013):
        mask = (test["REPDTE"].dt.year == year).to_numpy()
        by_year[str(year)] = {
            "baseline": subset_metrics(
                test.loc[mask],
                test_predictions[selected_baseline][mask],
                baseline_threshold,
            ),
            "challenger": subset_metrics(
                test.loc[mask],
                test_predictions[selected_challenger][mask],
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
    auprc_gain = relative_gain(
        float(baseline_test["average_precision"]),
        float(challenger_test["average_precision"]),
    )
    cost_reduction = relative_reduction(
        float(baseline_test["cost_per_row"]),
        float(challenger_test["cost_per_row"]),
    )

    def year_cost_improves(section: dict[str, Any]) -> bool:
        baseline = section["baseline"]
        challenger = section["challenger"]
        if min(
            int(baseline["positive_rows"]),
            int(challenger["positive_rows"]),
        ) < 15:
            return False
        return (
            baseline["metrics"] is not None
            and challenger["metrics"] is not None
            and float(challenger["metrics"]["cost_per_row"])
            < float(baseline["metrics"]["cost_per_row"])
        )

    entity_overlap = preflight_contract["entity_overlap_counts"]
    gates = {
        "entity_report_hash_exact": preflight_contract["panel_report_sha256"]
        == panel_report["sha256"],
        "official_panel_hash_exact": panel_sha
        == panel_contract["evaluation_panel"]["feature_file_sha256"],
        "zero_bank_quarter_duplicates": int(
            panel.duplicated(["CERT", "REPDTE"]).sum()
        )
        == 0,
        "zero_entity_overlap": all(int(value) == 0 for value in entity_overlap.values()),
        "zero_calibration_selection_entity_overlap": int(
            calibration_split["entity_overlap"]
        )
        == 0,
        "calibration_positive_entities_at_least_5": int(
            calibration_split["calibration_positive_entities"]
        )
        >= 5,
        "selection_positive_entities_at_least_5": int(
            calibration_split["selection_positive_entities"]
        )
        >= 5,
        "test_positive_entities_at_least_50": int(
            preflight_contract["split_counts"]["test"]["positive_entities"]
        )
        >= 50,
        "random_forest_in_baseline_family": {
            "RF_BALANCED",
            "RF_COST_SENSITIVE",
            "RF_BALANCED_PLATT",
            "RF_COST_PLATT",
        }.issubset(BASELINES),
        "challenger_auprc_relative_improvement_at_least_5pct": (
            auprc_gain is not None and auprc_gain >= 0.05
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
        "year_2012_cost_improves": year_cost_improves(by_year["2012"]),
        "year_2013_cost_improves": year_cost_improves(by_year["2013"]),
        "bank_cluster_bootstrap_lower_bound_positive": float(
            bootstrap["lower_95"]
            if bootstrap["lower_95"] is not None
            else -np.inf
        )
        > 0.0,
    }
    candidate_pass = all(gates.values())

    prediction_rows: list[dict[str, Any]] = []
    for split_name, frame, predictions in (
        ("selection", selection, selection_predictions),
        ("test", test, test_predictions),
    ):
        for method in (*BASELINES, *CHALLENGERS):
            for row, probability in zip(
                frame.itertuples(index=False), predictions[method], strict=True
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
                        "method": method,
                        "probability": float(probability),
                        "threshold": float(
                            selection_thresholds[method]["threshold"]
                        ),
                    }
                )
    predictions_path = output / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as handle:
        for row in sorted(
            prediction_rows,
            key=lambda item: (
                item["split"],
                item["method"],
                item["REPDTE"],
                item["CERT"],
            ),
        ):
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    calibration_assignments = (
        validation[["CERT"]]
        .drop_duplicates()
        .assign(
            calibration_bucket=lambda frame: frame["CERT"].map(
                lambda cert: int(
                    hashlib.sha256(
                        f"FIN-ABS-004B-CALIBRATION-SPLIT-V1|{int(cert)}".encode(
                            "utf-8"
                        )
                    ).hexdigest()[:16],
                    16,
                )
                % 100
            )
        )
        .sort_values("CERT")
    )
    calibration_assignments["subset"] = np.where(
        calibration_assignments["calibration_bucket"] < 50,
        "calibration",
        "selection",
    )
    assignment_path = output / "validation_entity_assignments.csv"
    calibration_assignments.to_csv(assignment_path, index=False, lineterminator="\n")

    preprocessing = {
        "lower": bundle.transformer.lower,
        "upper": bundle.transformer.upper,
        "median": bundle.transformer.median,
        "mean": bundle.transformer.mean,
        "scale": bundle.transformer.scale,
        "output_columns": list(bundle.transformer.output_columns),
        "monotonic_constraints": list(bundle.transformer.monotonic_constraints),
        "calibrators": calibration_parameters(bundle),
    }
    preprocessing_path = output / "preprocessing_and_calibration.json"
    preprocessing_path.write_text(
        json.dumps(preprocessing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    payload = {
        "schema": SCHEMA,
        "source": {
            "entity_report_sha256": panel_report["sha256"],
            "preflight_report_sha256": preflight_report["sha256"],
            "panel_file_sha256": panel_sha,
        },
        "protocol": {
            "windows": {
                name: [start.date().isoformat(), end.date().isoformat()]
                for name, (start, end) in WINDOWS.items()
            },
            "entity_split_seed": ENTITY_SPLIT_SEED,
            "entity_bucket_rule": EXPECTED_BUCKET_RULE,
            "calibration_split": calibration_split,
            "features": list(FEATURE_COLUMNS),
            "monotonic_directions": MONOTONIC_DIRECTIONS,
            "baselines": list(BASELINES),
            "challengers": list(CHALLENGERS),
            "false_negative_cost": FALSE_NEGATIVE_COST,
            "false_positive_cost": FALSE_POSITIVE_COST,
            "selection_rule": (
                "lowest selection-subset cost; ties by higher AUPRC, lower Brier, method"
            ),
            "rf_trees": int(rf_trees),
            "maximum_absolute_score_delta_after_full_independent_pass": 20,
        },
        "split_counts": preflight_contract["split_counts"],
        "selection": {
            "thresholds": selection_thresholds,
            "metrics": selection_metrics,
            "selected_baseline": selected_baseline,
            "selected_challenger": selected_challenger,
        },
        "sealed_test": {
            "baseline": {"method": selected_baseline, "metrics": baseline_test},
            "challenger": {
                "method": selected_challenger,
                "metrics": challenger_test,
            },
            "auprc_relative_improvement": auprc_gain,
            "expected_cost_reduction": cost_reduction,
            "by_year": by_year,
            "bank_cluster_bootstrap": bootstrap,
            "predictions_file": predictions_path.name,
            "predictions_file_sha256": sha_file(predictions_path),
            "preprocessing_file": preprocessing_path.name,
            "preprocessing_file_sha256": sha_file(preprocessing_path),
            "validation_entity_assignments_file": assignment_path.name,
            "validation_entity_assignments_sha256": sha_file(assignment_path),
        },
        "python_gate_checks": gates,
        "performance_candidate_pass": candidate_pass,
        "independent_model_reimplementation": "PENDING",
        "status": (
            "CANDIDATE_PASS_PENDING_INDEPENDENT_MODEL_REPLAY"
            if candidate_pass
            else "FALSIFIED_OR_OPEN_ON_FDIC_2012_2013"
        ),
        "absolute_score": {
            "before": ABSOLUTE_SCORE,
            "after": ABSOLUTE_SCORE,
            "delta": 0,
            "boundary": (
                "No absolute points are awarded until an independent implementation "
                "reconstructs models, predictions and every non-compensable gate."
            ),
        },
    }
    payload_canonical = canonical_json(payload)
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
    parser.add_argument("--preflight-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rf-trees", type=int, default=600)
    args = parser.parse_args()
    report = benchmark(
        args.panel,
        args.panel_report,
        args.preflight_report,
        args.output_dir,
        rf_trees=args.rf_trees,
    )
    payload = report["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "selected_baseline": payload["selection"]["selected_baseline"],
                "selected_challenger": payload["selection"]["selected_challenger"],
                "candidate_pass": payload["performance_candidate_pass"],
                "report_sha256": report["sha256"],
                "absolute_score": payload["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
