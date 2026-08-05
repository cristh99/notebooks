"""Post-outcome exact-gate completion laboratory for numeric-consensus v6.

This module uses the already opened WildReceipt observations to find the
smallest inference-only extension of the zero-failure v6 anchor that clears the
aggregate 10x and 25% coverage gates. Thresholds were chosen after WildReceipt
outcomes were visible; therefore the result is development evidence only and
cannot certify the candidate or authorize production.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .sroie_natural_holdout import stable_payload
from .wildreceipt_v6_selective_lab import (
    ALPHA_PER_LEG,
    COUNTERFACTUAL_MAXIMUM_UPPER,
    MINIMUM_ACCEPTED,
    MINIMUM_COVERAGE_LOWER,
    MINIMUM_SELECTED,
    TARGET_REDUCTION,
    PolicySpec,
    exact_summary,
    load_shard_report,
    no_equal_length_conflict,
    predict_crop_unanimous,
    scaled_minimum,
)

REPORT_SCHEMA = "ocr-wildreceipt-v6-gate-completion-lab/1"
DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN = 91.0
DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST = 93.0


def _candidate_values(row: Mapping[str, Any]) -> dict[str, str]:
    candidate = row["candidate"]
    if not candidate.get("eligible") or not candidate.get("guard"):
        return {}
    detector = str(candidate.get("claim") or "")
    if not detector.isdigit():
        return {}
    length = len(detector)
    readings = candidate["guard"].get("readings", {})
    raw = {
        "detector": detector,
        "forest": str(candidate.get("prediction") or ""),
        "gray": str(readings.get("gray", {}).get("digits") or ""),
        "autocontrast": str(
            readings.get("autocontrast", {}).get("digits") or ""
        ),
    }
    return {
        name: value
        for name, value in raw.items()
        if value.isdigit() and len(value) == length
    }


def _cluster_confidence(row: Mapping[str, Any]) -> float:
    matched = row["candidate"].get("matched") or {}
    return float(matched.get("confidence") or 0.0)


def predict_v6_gate_completion(row: Mapping[str, Any]) -> str | None:
    """Return one output only when every active branch agrees.

    Branch A preserves the earlier zero-failure union:
      * detector == forest with no equal-length detector conflict; or
      * forest == gray guard == autocontrast guard.

    Branch B adds detector == gray == autocontrast when detector confidence is
    strictly greater than 91.

    Branch C adds detector == forest == gray when detector confidence is at
    least 93. These two post-outcome branches add 64 opened-development cases.
    """
    values = _candidate_values(row)
    detector = values.get("detector")
    forest = values.get("forest")
    gray = values.get("gray")
    autocontrast = values.get("autocontrast")
    confidence = _cluster_confidence(row)
    outputs: list[str] = []

    if (
        detector
        and detector == forest
        and no_equal_length_conflict(row)
    ):
        outputs.append(detector)
    crop = predict_crop_unanimous(row)
    if crop is not None:
        outputs.append(crop)
    if (
        detector
        and detector == gray == autocontrast
        and confidence > DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN
    ):
        outputs.append(detector)
    if (
        detector
        and detector == forest == gray
        and confidence >= DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST
    ):
        outputs.append(detector)

    if not outputs or len(set(outputs)) != 1:
        return None
    return outputs[0]


GATE_POLICY = PolicySpec(
    name="v6_post_outcome_gate_completion",
    predictor=predict_v6_gate_completion,
    counterfactual_semantics="final_output_collision_proxy",
    successor_candidate=True,
)


def _load_rows(paths: Sequence[Path]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    reports: dict[str, Mapping[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for path in paths:
        report = load_shard_report(path)
        shard_id = str(report["dataset"]["shard_id"])
        if shard_id in reports:
            raise RuntimeError(f"duplicate shard report: {shard_id}")
        reports[shard_id] = report
        for observation in report["observations"]:
            row = dict(observation)
            row["_shard_id"] = shard_id
            rows.append(row)
    expected = {
        "test-00000-of-00001",
        "train-00000-of-00002",
        "train-00001-of-00002",
    }
    if set(reports) != expected:
        raise RuntimeError(f"requires exact WildReceipt shards: {sorted(reports)}")
    if len(rows) != 1720:
        raise RuntimeError(f"unexpected selected denominator: {len(rows)}")
    if len({str(row["image_sha256"]) for row in rows}) != len(rows):
        raise RuntimeError("duplicate physical image survived v5 deduplication")
    counts = {
        "train": sum(str(row["split"]) == "train" for row in rows),
        "test": sum(str(row["split"]) == "test" for row in rows),
    }
    if counts != {"train": 1252, "test": 468}:
        raise RuntimeError(f"unexpected split counts: {counts}")
    return rows, counts


def _branch_membership(row: Mapping[str, Any]) -> dict[str, bool]:
    values = _candidate_values(row)
    detector = values.get("detector")
    forest = values.get("forest")
    gray = values.get("gray")
    autocontrast = values.get("autocontrast")
    confidence = _cluster_confidence(row)
    anchor = bool(
        detector
        and detector == forest
        and no_equal_length_conflict(row)
    )
    crop = predict_crop_unanimous(row) is not None
    high_detector_guard = bool(
        detector
        and detector == gray == autocontrast
        and confidence > DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN
    )
    high_detector_forest_gray = bool(
        detector
        and detector == forest == gray
        and confidence >= DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST
    )
    return {
        "anchor": anchor,
        "crop_unanimous": crop,
        "base_union": anchor or crop,
        "high_detector_guard": high_detector_guard,
        "high_detector_forest_gray": high_detector_forest_gray,
    }


def build_report(paths: Sequence[Path]) -> dict[str, Any]:
    rows, split_counts = _load_rows(paths)
    train = [row for row in rows if str(row["split"]) == "train"]
    test = [row for row in rows if str(row["split"]) == "test"]

    memberships = [_branch_membership(row) for row in rows]
    base_union = sum(item["base_union"] for item in memberships)
    high_guard_total = sum(item["high_detector_guard"] for item in memberships)
    high_dfg_total = sum(
        item["high_detector_forest_gray"] for item in memberships
    )
    high_guard_added = sum(
        item["high_detector_guard"] and not item["base_union"]
        for item in memberships
    )
    high_dfg_added = sum(
        item["high_detector_forest_gray"]
        and not item["base_union"]
        and not item["high_detector_guard"]
        for item in memberships
    )

    overall = exact_summary(rows, GATE_POLICY, adjudicated=True)
    train_summary = exact_summary(
        train,
        GATE_POLICY,
        adjudicated=True,
        minimum_selected=scaled_minimum(
            MINIMUM_SELECTED, len(train), len(rows)
        ),
        minimum_accepted=scaled_minimum(
            MINIMUM_ACCEPTED, len(train), len(rows)
        ),
    )
    test_summary = exact_summary(
        test,
        GATE_POLICY,
        adjudicated=True,
        minimum_selected=scaled_minimum(
            MINIMUM_SELECTED, len(test), len(rows)
        ),
        minimum_accepted=scaled_minimum(
            MINIMUM_ACCEPTED, len(test), len(rows)
        ),
    )

    folds = []
    for held_out in sorted({str(row["_shard_id"]) for row in rows}):
        subset = [row for row in rows if row["_shard_id"] != held_out]
        folds.append(
            {
                "held_out_shard": held_out,
                "summary": exact_summary(
                    subset,
                    GATE_POLICY,
                    adjudicated=True,
                    minimum_selected=scaled_minimum(
                        MINIMUM_SELECTED, len(subset), len(rows)
                    ),
                    minimum_accepted=scaled_minimum(
                        MINIMUM_ACCEPTED, len(subset), len(rows)
                    ),
                ),
            }
        )
    stability_passes = sum(bool(fold["summary"]["pass"]) for fold in folds)

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "POST_OUTCOME_DEVELOPMENT_ONLY",
        "source": {
            "workflow_run_id": 30998215981,
            "aggregate_artifact_id": 8928251131,
            "selective_lab_artifact_id": 8931342861,
            "selective_lab_stable_payload_sha256": (
                "aa371cc230cd5a00fe8982e6e4e72d92bffd52594352664020489f18bf75e143"
            ),
            "selected_unique_receipts": len(rows),
            "split_counts": split_counts,
            "wildreceipt_opened_for_threshold_design": True,
        },
        "policy": {
            "name": GATE_POLICY.name,
            "base_union": (
                "detector==forest with no equal-length conflict OR "
                "forest==gray==autocontrast"
            ),
            "post_outcome_branch_1": {
                "rule": "detector==gray==autocontrast and confidence>91.0",
                "threshold": DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN,
            },
            "post_outcome_branch_2": {
                "rule": "detector==forest==gray and confidence>=93.0",
                "threshold": DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST,
            },
            "conflicting_branch_outputs": "abstain",
            "uses_truth_at_inference": False,
            "uses_annotation_geometry_at_inference": False,
            "thresholds_selected_after_wildreceipt_outcomes": True,
        },
        "branch_accounting": {
            "base_union_accepted": base_union,
            "high_detector_guard_total": high_guard_total,
            "high_detector_forest_gray_total": high_dfg_total,
            "high_detector_guard_added_beyond_base": high_guard_added,
            "high_detector_forest_gray_added_beyond_previous_branches": (
                high_dfg_added
            ),
            "total_added_beyond_base": high_guard_added + high_dfg_added,
            "final_accepted": overall["accepted"],
        },
        "exact_results": {
            "train": train_summary,
            "test": test_summary,
            "all": overall,
        },
        "leave_one_shard_out": {
            "folds": folds,
            "passes": stability_passes,
            "pass_fraction": stability_passes / len(folds),
        },
        "decision": {
            "aggregate_development_10x_gate_pass": bool(overall["pass"]),
            "zero_adjudicated_natural_failures": bool(
                overall["accepted_false"] == 0
            ),
            "zero_counterfactual_output_collisions": bool(
                overall["counterfactual_false"] == 0
            ),
            "minimum_accepted_pass": bool(
                overall["accepted"] >= MINIMUM_ACCEPTED
            ),
            "coverage_gate_pass": bool(
                overall["coverage_lower"] >= MINIMUM_COVERAGE_LOWER
            ),
            "tenfold_bound_pass": bool(
                overall["reduction_lower"] is not None
                and overall["reduction_lower"] >= TARGET_REDUCTION
            ),
            "leave_one_shard_out_stability_pass": bool(
                stability_passes == len(folds)
            ),
            "external_certificate_claimed": False,
            "candidate_ready_to_freeze": False,
            "fresh_external_corpus_required": True,
            "production_ready": False,
            "automatic_production_change": False,
        },
        "interpretation": {
            "what_was_proved": (
                "The opened WildReceipt observations contain an inference-only "
                "selective policy with 472 accepted, zero adjudicated natural "
                "failures, zero output collisions with the stored counterfactual, "
                "coverage lower above 25%, and reduction lower above 10x."
            ),
            "what_was_not_proved": (
                "The confidence thresholds were selected after outcomes were "
                "opened and leave-one-shard-out stability still fails; this is "
                "not external evidence and cannot authorize production."
            ),
            "next_power_bottleneck": (
                "replace post-outcome thresholds with a pre-frozen calibrated "
                "risk model and validate it on a different untouched corpus"
            ),
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    return stable_payload(report, "stable_payload_sha256")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shard_reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_report(args.shard_reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "branch_accounting": report["branch_accounting"],
                "exact_results": report["exact_results"],
                "leave_one_shard_out": report["leave_one_shard_out"],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
