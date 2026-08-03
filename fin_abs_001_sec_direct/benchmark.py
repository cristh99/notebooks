from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from .policy import predict, tolerance
from .utils import digest


def reporting_variant(
    case: Mapping[str, Any],
    divisor: float = 1_000_000.0,
) -> dict[str, Any]:
    result = copy.deepcopy(case)
    result["values"] = {
        key: round(float(value) / divisor)
        for key, value in case.get("values", {}).items()
    }
    result["reporting_variant"] = {
        "name": "rounded_millions",
        "divisor": divisor,
        "rounding": "nearest integer",
    }
    return result


def build_instances(
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for case in cases:
        base_id = (
            f"{case['ticker']}|{case['accession']}|"
            f"{case['report_end']}"
        )
        instances.append(
            {
                "instance_id": f"{base_id}|CLEAN",
                "case": copy.deepcopy(case),
                "ground_truth": {
                    "has_error": False,
                    "target_key": None,
                    "relation_id": None,
                    "family": None,
                    "magnitude_pct": None,
                },
            }
        )

        for index, relation in enumerate(
            predict(case)["all_relations"]
        ):
            modified = copy.deepcopy(case)
            target_key = str(relation["observed_key"])
            original = float(modified["values"][target_key])
            direction = (
                -1.0
                if int(
                    digest(
                        f"{base_id}|{relation['relation_id']}"
                    )[-1],
                    16,
                )
                % 2
                else 1.0
            )
            baseline_expected = float(relation["expected"])
            baseline_tolerance = tolerance(
                original,
                baseline_expected,
            )
            absolute_delta = max(
                abs(original) * 0.05,
                2.0 * baseline_tolerance + 1.0,
            )
            modified_value = original + direction * absolute_delta
            magnitude_pct = (
                100.0 * absolute_delta / abs(original)
                if original != 0
                else None
            )
            modified["values"][target_key] = modified_value
            instances.append(
                {
                    "instance_id": (
                        f"{base_id}|"
                        f"{relation['relation_id']}|{index}"
                    ),
                    "case": modified,
                    "ground_truth": {
                        "has_error": True,
                        "target_key": target_key,
                        "relation_id": relation["relation_id"],
                        "family": relation["family"],
                        "magnitude_pct": (
                            magnitude_pct * direction
                            if magnitude_pct is not None
                            else None
                        ),
                        "original_value": original,
                        "modified_value": modified_value,
                    },
                }
            )
    return instances


def observable(
    instance: Mapping[str, Any],
    prediction: Mapping[str, Any],
) -> bool:
    target = instance.get("ground_truth", {}).get("target_key")
    return not target or target in prediction.get("visible_keys", [])


def evaluate_instances(
    instances: Sequence[Mapping[str, Any]],
    *,
    rounded: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance in instances:
        case = reporting_variant(instance["case"]) if rounded else instance["case"]
        prediction = predict(case)
        ground = instance["ground_truth"]
        rows.append(
            {
                "instance_id": instance["instance_id"],
                "ticker": case["ticker"],
                "sic": case.get("sic", ""),
                "variant": "rounded_millions" if rounded else "exact",
                "gold_error": bool(ground["has_error"]),
                "target_key": ground.get("target_key"),
                "family": ground.get("family"),
                "observable": observable(instance, prediction),
                "decision": prediction["decision"],
                "relation_count": prediction["relation_count"],
                "failed_relation_ids": [
                    relation["relation_id"]
                    for relation in prediction["failed_relations"]
                ],
                "visible_keys": prediction["visible_keys"],
                "prediction_sha256": digest(prediction),
            }
        )
    return rows
