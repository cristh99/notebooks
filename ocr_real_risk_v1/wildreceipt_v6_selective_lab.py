"""Faithful post-outcome policy laboratory for numeric-consensus v6.

WildReceipt is opened development data after schema-v5. The original terminal
result remains immutable. A known benchmark-label defect is evaluated only in
an explicitly separate sensitivity analysis. Successor policies are selected
on the two train shards and then scored on the test shard. Nothing in this
module can issue an untouched external certificate or modify production.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .sroie_natural_holdout import stable_payload, verify_stable_payload

REPORT_SCHEMA = "ocr-wildreceipt-v6-selective-lab/1"
SHARD_REPORT_SCHEMA = "ocr-wildreceipt-numeric-shard/1"
ALPHA_PER_LEG = 0.0125
TARGET_REDUCTION = 10.0
MINIMUM_SELECTED = 1200
MINIMUM_ACCEPTED = 400
MINIMUM_COVERAGE_LOWER = 0.25
COUNTERFACTUAL_MAXIMUM_UPPER = 0.01
KNOWN_LABEL_ADJUDICATION_KEY = "test-00000-of-00001:70"
KNOWN_LABEL_ADJUDICATED_TRUTH = "1199"

Predictor = Callable[[Mapping[str, Any]], str | None]


@dataclass(frozen=True)
class PolicySpec:
    name: str
    predictor: Predictor
    counterfactual_semantics: str
    successor_candidate: bool


def channels(row: Mapping[str, Any]) -> dict[str, str]:
    candidate = row["candidate"]
    if not candidate.get("eligible") or not candidate.get("guard"):
        return {}
    detector = str(candidate.get("claim") or "")
    if not detector.isdigit():
        return {}
    length = len(detector)
    readings = candidate["guard"].get("readings", {})
    values = {
        "detector": detector,
        "forest": str(candidate.get("prediction") or ""),
        "gray": str(readings.get("gray", {}).get("digits") or ""),
        "autocontrast": str(
            readings.get("autocontrast", {}).get("digits") or ""
        ),
    }
    return {
        name: value
        for name, value in values.items()
        if value.isdigit() and len(value) == length
    }


def unique_mode(values: Iterable[str], minimum_support: int) -> str | None:
    counts = Counter(values)
    if not counts:
        return None
    ranked = counts.most_common()
    if ranked[0][1] < minimum_support:
        return None
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return None
    return ranked[0][0]


def no_equal_length_conflict(row: Mapping[str, Any]) -> bool:
    matched = row["candidate"].get("matched") or {}
    return not bool(matched.get("equal_length_conflicts"))


def predict_v5_current(row: Mapping[str, Any]) -> str | None:
    candidate = row["candidate"]
    return str(candidate["claim"]) if candidate.get("accepted") else None


def predict_detector_forest_no_conflict(
    row: Mapping[str, Any],
) -> str | None:
    observed = channels(row)
    detector = observed.get("detector")
    forest = observed.get("forest")
    if detector and detector == forest and no_equal_length_conflict(row):
        return detector
    return None


def predict_detector_forest_no_conflict_prob25(
    row: Mapping[str, Any],
) -> str | None:
    prediction = predict_detector_forest_no_conflict(row)
    if prediction is None:
        return None
    if float(row["candidate"].get("minimum_mean_probability") or 0.0) < 0.25:
        return None
    return prediction


def predict_crop_unanimous(row: Mapping[str, Any]) -> str | None:
    observed = channels(row)
    forest = observed.get("forest")
    gray = observed.get("gray")
    autocontrast = observed.get("autocontrast")
    if forest and forest == gray == autocontrast:
        return forest
    return None


def predict_detector_forest_or_crop_unanimous(
    row: Mapping[str, Any],
) -> str | None:
    anchor = predict_detector_forest_no_conflict(row)
    crop = predict_crop_unanimous(row)
    if anchor and crop and anchor != crop:
        return None
    return anchor or crop


def predict_four_channel_majority3(row: Mapping[str, Any]) -> str | None:
    return unique_mode(channels(row).values(), minimum_support=3)


POLICIES = (
    PolicySpec(
        name="v5_current",
        predictor=predict_v5_current,
        counterfactual_semantics="stored_injected_claim_replay",
        successor_candidate=False,
    ),
    PolicySpec(
        name="detector_forest_no_equal_length_conflict",
        predictor=predict_detector_forest_no_conflict,
        counterfactual_semantics="final_output_collision_proxy",
        successor_candidate=True,
    ),
    PolicySpec(
        name="detector_forest_no_conflict_prob25",
        predictor=predict_detector_forest_no_conflict_prob25,
        counterfactual_semantics="final_output_collision_proxy",
        successor_candidate=True,
    ),
    PolicySpec(
        name="forest_gray_autocontrast_unanimous",
        predictor=predict_crop_unanimous,
        counterfactual_semantics="final_output_collision_proxy",
        successor_candidate=True,
    ),
    PolicySpec(
        name="detector_forest_or_crop_unanimous",
        predictor=predict_detector_forest_or_crop_unanimous,
        counterfactual_semantics="final_output_collision_proxy",
        successor_candidate=True,
    ),
    PolicySpec(
        name="four_channel_majority3",
        predictor=predict_four_channel_majority3,
        counterfactual_semantics="final_output_collision_proxy",
        successor_candidate=True,
    ),
)
POLICY_BY_NAME = {policy.name: policy for policy in POLICIES}


def truth(row: Mapping[str, Any], adjudicated: bool) -> str:
    if adjudicated and row["key"] == KNOWN_LABEL_ADJUDICATION_KEY:
        return KNOWN_LABEL_ADJUDICATED_TRUTH
    return str(row["truth"])


def counterfactual_false(
    row: Mapping[str, Any],
    prediction: str | None,
    policy: PolicySpec,
) -> bool:
    if policy.counterfactual_semantics == "stored_injected_claim_replay":
        return bool(row["counterfactual"]["false_accept"])
    if policy.counterfactual_semantics == "final_output_collision_proxy":
        return bool(
            prediction is not None
            and prediction == str(row["counterfactual_claim"])
        )
    raise RuntimeError(
        f"unknown counterfactual semantics: {policy.counterfactual_semantics}"
    )


def exact_summary(
    rows: Sequence[Mapping[str, Any]],
    policy: PolicySpec,
    *,
    adjudicated: bool,
    minimum_selected: int = MINIMUM_SELECTED,
    minimum_accepted: int = MINIMUM_ACCEPTED,
) -> dict[str, Any]:
    selected = list(rows)
    predictions = [policy.predictor(row) for row in selected]
    accepted = [
        (row, prediction)
        for row, prediction in zip(selected, predictions, strict=True)
        if prediction is not None
    ]
    false_accepted = sum(
        prediction != truth(row, adjudicated)
        for row, prediction in accepted
    )
    counterfactual_count = sum(
        counterfactual_false(row, prediction, policy)
        for row, prediction in zip(selected, predictions, strict=True)
    )
    baseline_eligible = [
        row for row in selected if bool(row["baseline"]["eligible"])
    ]
    baseline_false = sum(
        str(row["baseline"]["claim"]) != truth(row, adjudicated)
        for row in baseline_eligible
    )
    baseline_lower = (
        clopper_pearson_lower(
            baseline_false, len(baseline_eligible), ALPHA_PER_LEG
        )
        if baseline_eligible
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(
            false_accepted, len(accepted), ALPHA_PER_LEG
        )
        if accepted
        else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(
            len(accepted), len(selected), ALPHA_PER_LEG
        )
        if selected
        else 0.0
    )
    counterfactual_upper = (
        clopper_pearson_upper(
            counterfactual_count, len(selected), ALPHA_PER_LEG
        )
        if selected
        else 1.0
    )
    reduction_lower = (
        baseline_lower / candidate_upper if candidate_upper > 0 else None
    )
    passed = bool(
        len(selected) >= minimum_selected
        and baseline_false > 0
        and len(accepted) >= minimum_accepted
        and coverage_lower >= MINIMUM_COVERAGE_LOWER
        and candidate_upper <= baseline_lower / TARGET_REDUCTION
        and counterfactual_upper <= COUNTERFACTUAL_MAXIMUM_UPPER
    )
    return {
        "selected": len(selected),
        "baseline_eligible": len(baseline_eligible),
        "baseline_false": baseline_false,
        "accepted": len(accepted),
        "accepted_false": false_accepted,
        "counterfactual_false": counterfactual_count,
        "observed_coverage": (
            len(accepted) / len(selected) if selected else 0.0
        ),
        "baseline_lower": baseline_lower,
        "candidate_upper": candidate_upper,
        "coverage_lower": coverage_lower,
        "counterfactual_upper": counterfactual_upper,
        "reduction_lower": reduction_lower,
        "minimum_selected_required": minimum_selected,
        "minimum_accepted_required": minimum_accepted,
        "pass": passed,
    }


def load_shard_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SHARD_REPORT_SCHEMA:
        raise RuntimeError(f"unexpected shard report schema: {path}")
    if not verify_stable_payload(payload, "stable_payload_sha256"):
        raise RuntimeError(f"shard report stable replay failed: {path}")
    if payload.get("decision", {}).get("shard_execution_complete") is not True:
        raise RuntimeError(f"shard execution incomplete: {path}")
    return payload


def scaled_minimum(total_required: int, subset_size: int, full_size: int) -> int:
    return max(
        1,
        (total_required * subset_size + full_size - 1) // full_size,
    )


def subset_summary(
    rows: Sequence[Mapping[str, Any]],
    full_size: int,
    policy: PolicySpec,
    adjudicated: bool,
) -> dict[str, Any]:
    return exact_summary(
        rows,
        policy,
        adjudicated=adjudicated,
        minimum_selected=scaled_minimum(
            MINIMUM_SELECTED, len(rows), full_size
        ),
        minimum_accepted=scaled_minimum(
            MINIMUM_ACCEPTED, len(rows), full_size
        ),
    )


def build_report(shard_report_paths: Sequence[Path]) -> dict[str, Any]:
    shard_reports: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for path in shard_report_paths:
        report = load_shard_report(path)
        shard_id = str(report["dataset"]["shard_id"])
        if shard_id in shard_reports:
            raise RuntimeError(f"duplicate shard report: {shard_id}")
        shard_reports[shard_id] = report
        for observation in report["observations"]:
            row = dict(observation)
            row["_shard_id"] = shard_id
            rows.append(row)
    expected = {
        "test-00000-of-00001",
        "train-00000-of-00002",
        "train-00001-of-00002",
    }
    if set(shard_reports) != expected:
        raise RuntimeError(
            f"requires exact WildReceipt shards: {sorted(shard_reports)}"
        )
    if len(rows) != 1720:
        raise RuntimeError(f"unexpected selected denominator: {len(rows)}")
    if len({str(row["image_sha256"]) for row in rows}) != len(rows):
        raise RuntimeError("duplicate physical images survived v5 deduplication")
    train = [row for row in rows if str(row["split"]) == "train"]
    test = [row for row in rows if str(row["split"]) == "test"]
    if len(train) != 1252 or len(test) != 468:
        raise RuntimeError(
            f"unexpected train/test denominators: {len(train)}/{len(test)}"
        )

    results: dict[str, Any] = {}
    for policy in POLICIES:
        results[policy.name] = {
            "counterfactual_semantics": policy.counterfactual_semantics,
            "successor_candidate": policy.successor_candidate,
            "original_labels": {
                "all": exact_summary(
                    rows, policy, adjudicated=False
                ),
                "train": subset_summary(
                    train, len(rows), policy, False
                ),
                "test": subset_summary(
                    test, len(rows), policy, False
                ),
            },
            "label_adjudicated_sensitivity": {
                "all": exact_summary(rows, policy, adjudicated=True),
                "train": subset_summary(
                    train, len(rows), policy, True
                ),
                "test": subset_summary(
                    test, len(rows), policy, True
                ),
            },
        }

    train_safe = []
    for policy in POLICIES:
        if not policy.successor_candidate:
            continue
        summary = results[policy.name]["label_adjudicated_sensitivity"][
            "train"
        ]
        if (
            summary["accepted_false"] == 0
            and summary["counterfactual_false"] == 0
        ):
            train_safe.append(policy.name)
    if not train_safe:
        raise RuntimeError("no zero-failure successor policy on train")
    train_safe.sort(
        key=lambda name: (
            -results[name]["label_adjudicated_sensitivity"]["train"][
                "accepted"
            ],
            name,
        )
    )
    selected_name = train_safe[0]
    selected_policy = POLICY_BY_NAME[selected_name]
    selected = results[selected_name]["label_adjudicated_sensitivity"]

    folds = []
    for held_out in sorted(shard_reports):
        subset = [row for row in rows if row["_shard_id"] != held_out]
        folds.append(
            {
                "held_out_shard": held_out,
                "summary": subset_summary(
                    subset,
                    len(rows),
                    selected_policy,
                    True,
                ),
            }
        )

    current_original = results["v5_current"]["original_labels"]["all"]
    current_adjudicated = results["v5_current"][
        "label_adjudicated_sensitivity"
    ]["all"]
    selected_all = selected["all"]
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "POST_OUTCOME_DEVELOPMENT_ONLY",
        "source": {
            "workflow_run_id": 30998215981,
            "aggregate_artifact_id": 8928251131,
            "candidate_stable_payload_sha256": (
                "95d4525b8c14de6168d080c8d3aec51852c7f954097426e2f69c00682dd3d387"
            ),
            "selected_unique_receipts": len(rows),
            "train_receipts": len(train),
            "test_receipts": len(test),
            "wildreceipt_opened_for_development": True,
        },
        "known_label_adjudication": {
            "key": KNOWN_LABEL_ADJUDICATION_KEY,
            "original_truth": "1198",
            "pixel_and_arithmetic_truth": KNOWN_LABEL_ADJUDICATED_TRUTH,
            "original_result_preserved": True,
            "silent_relabeling_forbidden": True,
        },
        "v5_terminal_original": current_original,
        "v5_label_adjudicated_sensitivity": current_adjudicated,
        "policies": results,
        "train_only_selection": {
            "constraint": (
                "zero natural and counterfactual failures on both train shards, "
                "then maximum train acceptance; lexical deterministic tie-break"
            ),
            "selected_policy": selected_name,
            "train": selected["train"],
            "test": selected["test"],
            "all": selected_all,
        },
        "leave_one_shard_out": folds,
        "decision": {
            "v5_external_10x_pass": False,
            "v5_original_result_immutable": True,
            "label_defect_confirmed_high_confidence": True,
            "selected_policy_zero_adjudicated_natural_failures": bool(
                selected_all["accepted_false"] == 0
            ),
            "selected_policy_zero_counterfactual_collisions": bool(
                selected_all["counterfactual_false"] == 0
            ),
            "selected_policy_reaches_minimum_accepted": bool(
                selected_all["accepted"] >= MINIMUM_ACCEPTED
            ),
            "selected_policy_reaches_coverage_gate": bool(
                selected_all["coverage_lower"] >= MINIMUM_COVERAGE_LOWER
            ),
            "selected_policy_reaches_10x_bound": bool(selected_all["pass"]),
            "candidate_ready_to_freeze": False,
            "fresh_external_corpus_required": True,
            "production_ready": False,
            "automatic_production_change": False,
        },
        "derived_v6_requirements": [
            "replace psm7_any with disagreement-aware crop verification",
            "retain detector-versus-forest agreement as the zero-failure anchor",
            "add an independent coverage path instead of weakening the anchor",
            "use repeated-amount and receipt arithmetic only as an independent verifier",
            "train on opened CORD and WildReceipt hard negatives, then freeze before a different external corpus",
        ],
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
                "v5_terminal_original": report["v5_terminal_original"],
                "v5_label_adjudicated_sensitivity": report[
                    "v5_label_adjudicated_sensitivity"
                ],
                "train_only_selection": report["train_only_selection"],
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
