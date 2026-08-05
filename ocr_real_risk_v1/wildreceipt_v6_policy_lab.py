"""Post-outcome WildReceipt policy laboratory for numeric-consensus v6.

WildReceipt is opened development data after schema-v5. This module must never
issue an untouched external certificate. It replays frozen shard observations,
keeps the original benchmark result immutable, applies a separately recorded
label adjudication only as sensitivity analysis, and searches deterministic
selective-consensus policies on the two train shards before scoring the test
shard.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .core import canonical_json, sha256_bytes
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .sroie_natural_holdout import stable_payload, verify_stable_payload

REPORT_SCHEMA = "ocr-wildreceipt-v6-policy-lab/1"
SHARD_REPORT_SCHEMA = "ocr-wildreceipt-numeric-shard/1"
ALPHA_PER_LEG = 0.0125
TARGET_REDUCTION = 10.0
MINIMUM_SELECTED = 1200
MINIMUM_ACCEPTED = 400
MINIMUM_COVERAGE_LOWER = 0.25
COUNTERFACTUAL_MAXIMUM_UPPER = 0.01
KNOWN_LABEL_ADJUDICATION_KEY = "test-00000-of-00001:70"
KNOWN_LABEL_ADJUDICATED_TRUTH = "1199"

Policy = Callable[[Mapping[str, Any]], str | None]


def _channels(row: Mapping[str, Any]) -> dict[str, str]:
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


def _unique_mode(values: Iterable[str], minimum_support: int) -> str | None:
    counts = Counter(values)
    if not counts:
        return None
    ranked = counts.most_common()
    if ranked[0][1] < minimum_support:
        return None
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return None
    return ranked[0][0]


def _no_equal_length_conflict(row: Mapping[str, Any]) -> bool:
    matched = row["candidate"].get("matched") or {}
    return not bool(matched.get("equal_length_conflicts"))


def policy_v5_current(row: Mapping[str, Any]) -> str | None:
    candidate = row["candidate"]
    return str(candidate["claim"]) if candidate.get("accepted") else None


def policy_detector_forest_no_conflict(
    row: Mapping[str, Any],
) -> str | None:
    channels = _channels(row)
    detector = channels.get("detector")
    forest = channels.get("forest")
    if detector and detector == forest and _no_equal_length_conflict(row):
        return detector
    return None


def policy_detector_forest_prob25(row: Mapping[str, Any]) -> str | None:
    candidate = row["candidate"]
    result = policy_detector_forest_no_conflict(row)
    if result is None:
        return None
    if float(candidate.get("minimum_mean_probability") or 0.0) < 0.25:
        return None
    return result


def policy_crop_unanimous(row: Mapping[str, Any]) -> str | None:
    channels = _channels(row)
    forest = channels.get("forest")
    gray = channels.get("gray")
    autocontrast = channels.get("autocontrast")
    if forest and forest == gray == autocontrast:
        return forest
    return None


def policy_detector_forest_or_crop_unanimous(
    row: Mapping[str, Any],
) -> str | None:
    detector_forest = policy_detector_forest_no_conflict(row)
    crop = policy_crop_unanimous(row)
    if detector_forest and crop and detector_forest != crop:
        return None
    return detector_forest or crop


def policy_four_channel_majority3(row: Mapping[str, Any]) -> str | None:
    return _unique_mode(_channels(row).values(), minimum_support=3)


POLICIES: dict[str, Policy] = {
    "v5_current": policy_v5_current,
    "detector_forest_no_equal_length_conflict": (
        policy_detector_forest_no_conflict
    ),
    "detector_forest_no_conflict_prob25": policy_detector_forest_prob25,
    "forest_gray_autocontrast_unanimous": policy_crop_unanimous,
    "detector_forest_or_crop_unanimous": (
        policy_detector_forest_or_crop_unanimous
    ),
    "four_channel_majority3": policy_four_channel_majority3,
}


def _truth(row: Mapping[str, Any], adjudicated: bool) -> str:
    if adjudicated and row["key"] == KNOWN_LABEL_ADJUDICATION_KEY:
        return KNOWN_LABEL_ADJUDICATED_TRUTH
    return str(row["truth"])


def exact_summary(
    rows: Sequence[Mapping[str, Any]],
    policy: Policy,
    *,
    adjudicated: bool,
    minimum_selected: int = MINIMUM_SELECTED,
    minimum_accepted: int = MINIMUM_ACCEPTED,
) -> dict[str, Any]:
    selected = list(rows)
    accepted: list[tuple[Mapping[str, Any], str]] = []
    for row in selected:
        prediction = policy(row)
        if prediction is not None:
            accepted.append((row, prediction))
    false_accepted = sum(
        prediction != _truth(row, adjudicated)
        for row, prediction in accepted
    )
    counterfactual_false = sum(
        prediction == str(row["counterfactual_claim"])
        for row, prediction in accepted
    )
    baseline_eligible = [
        row for row in selected if bool(row["baseline"]["eligible"])
    ]
    baseline_false = sum(
        str(row["baseline"]["claim"]) != _truth(row, adjudicated)
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
            counterfactual_false, len(selected), ALPHA_PER_LEG
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
        "counterfactual_false": counterfactual_false,
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


def _load_shard_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SHARD_REPORT_SCHEMA:
        raise RuntimeError(f"unexpected shard report schema: {path}")
    if not verify_stable_payload(payload, "stable_payload_sha256"):
        raise RuntimeError(f"shard report stable replay failed: {path}")
    if payload.get("decision", {}).get("shard_execution_complete") is not True:
        raise RuntimeError(f"shard execution is incomplete: {path}")
    return payload


def _scaled_minimum(total_required: int, subset_size: int, full_size: int) -> int:
    return max(1, int((total_required * subset_size + full_size - 1) // full_size))


def build_report(shard_report_paths: Sequence[Path]) -> dict[str, Any]:
    shard_reports: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for path in shard_report_paths:
        report = _load_shard_report(path)
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
            f"policy lab requires the exact three WildReceipt shards: "
            f"{sorted(shard_reports)}"
        )
    if len(rows) != 1720:
        raise RuntimeError(f"unexpected selected denominator: {len(rows)}")
    if len({str(row["image_sha256"]) for row in rows}) != len(rows):
        raise RuntimeError("duplicate physical images survived v5 deduplication")

    train = [row for row in rows if str(row["split"]) == "train"]
    test = [row for row in rows if str(row["split"]) == "test"]
    policy_results: dict[str, Any] = {}
    for name, policy in POLICIES.items():
        policy_results[name] = {
            "original_labels": {
                "all": exact_summary(rows, policy, adjudicated=False),
                "train": exact_summary(
                    train,
                    policy,
                    adjudicated=False,
                    minimum_selected=_scaled_minimum(
                        MINIMUM_SELECTED, len(train), len(rows)
                    ),
                    minimum_accepted=_scaled_minimum(
                        MINIMUM_ACCEPTED, len(train), len(rows)
                    ),
                ),
                "test": exact_summary(
                    test,
                    policy,
                    adjudicated=False,
                    minimum_selected=_scaled_minimum(
                        MINIMUM_SELECTED, len(test), len(rows)
                    ),
                    minimum_accepted=_scaled_minimum(
                        MINIMUM_ACCEPTED, len(test), len(rows)
                    ),
                ),
            },
            "label_adjudicated_sensitivity": {
                "all": exact_summary(rows, policy, adjudicated=True),
                "train": exact_summary(
                    train,
                    policy,
                    adjudicated=True,
                    minimum_selected=_scaled_minimum(
                        MINIMUM_SELECTED, len(train), len(rows)
                    ),
                    minimum_accepted=_scaled_minimum(
                        MINIMUM_ACCEPTED, len(train), len(rows)
                    ),
                ),
                "test": exact_summary(
                    test,
                    policy,
                    adjudicated=True,
                    minimum_selected=_scaled_minimum(
                        MINIMUM_SELECTED, len(test), len(rows)
                    ),
                    minimum_accepted=_scaled_minimum(
                        MINIMUM_ACCEPTED, len(test), len(rows)
                    ),
                ),
            },
        }

    train_safe = []
    for name, result in policy_results.items():
        summary = result["label_adjudicated_sensitivity"]["train"]
        if (
            summary["accepted_false"] == 0
            and summary["counterfactual_false"] == 0
        ):
            train_safe.append(name)
    if not train_safe:
        raise RuntimeError("no zero-failure train policy exists")
    train_safe.sort(
        key=lambda name: (
            -policy_results[name]["label_adjudicated_sensitivity"]["train"][
                "accepted"
            ],
            name,
        )
    )
    selected_name = train_safe[0]
    selected_result = policy_results[selected_name]

    folds = []
    for held_out in sorted(shard_reports):
        subset = [row for row in rows if row["_shard_id"] != held_out]
        folds.append(
            {
                "held_out_shard": held_out,
                "summary": exact_summary(
                    subset,
                    POLICIES[selected_name],
                    adjudicated=True,
                    minimum_selected=_scaled_minimum(
                        MINIMUM_SELECTED, len(subset), len(rows)
                    ),
                    minimum_accepted=_scaled_minimum(
                        MINIMUM_ACCEPTED, len(subset), len(rows)
                    ),
                ),
            }
        )

    current_original = policy_results["v5_current"]["original_labels"]["all"]
    current_adjudicated = policy_results["v5_current"][
        "label_adjudicated_sensitivity"
    ]["all"]
    selected_all = selected_result["label_adjudicated_sensitivity"]["all"]
    selected_test = selected_result["label_adjudicated_sensitivity"]["test"]
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
        "policies": policy_results,
        "train_only_selection": {
            "constraint": (
                "zero natural and counterfactual failures on both train shards, "
                "then maximum accepted count with lexical deterministic tie-break"
            ),
            "selected_policy": selected_name,
            "selected_policy_train": selected_result[
                "label_adjudicated_sensitivity"
            ]["train"],
            "selected_policy_test": selected_test,
            "selected_policy_all": selected_all,
        },
        "leave_one_shard_out": folds,
        "decision": {
            "v5_external_10x_pass": False,
            "v5_original_result_immutable": True,
            "label_defect_confirmed_high_confidence": True,
            "selected_policy_has_zero_adjudicated_failures": bool(
                selected_all["accepted_false"] == 0
                and selected_all["counterfactual_false"] == 0
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
            "retain exact detector-versus-forest agreement as a zero-failure anchor",
            "add a new coverage path rather than weakening the anchor threshold",
            "use receipt-level repeated-amount and arithmetic consistency only as an independent verifier",
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
