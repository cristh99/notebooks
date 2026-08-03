from __future__ import annotations

from typing import Any, Mapping

from .constants import (
    ABSOLUTE_TOLERANCE,
    MIN_RELATIONS_FOR_DECISION,
    POLICY_ID,
    RELATIVE_TOLERANCE,
)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def tolerance(observed: float, expected: float) -> float:
    return max(
        ABSOLUTE_TOLERANCE,
        RELATIVE_TOLERANCE * max(abs(observed), abs(expected), 1.0),
    )


def relation_specs(
    values: Mapping[str, float],
    provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    keys = values.keys()
    if {"assets", "liabilities_and_equity"} <= keys:
        relations.append(
            {
                "relation_id": "BS_DIRECT_TOTAL",
                "family": "AE",
                "observed_key": "assets",
                "expected_terms": (("liabilities_and_equity", 1.0),),
            }
        )
    if {"assets", "liabilities", "equity"} <= keys:
        relations.append(
            {
                "relation_id": "BS_COMPONENT_IDENTITY",
                "family": "AE",
                "observed_key": "assets",
                "expected_terms": (("liabilities", 1.0), ("equity", 1.0)),
            }
        )
    if {"gross_profit", "revenue", "cost_of_revenue"} <= keys:
        relations.append(
            {
                "relation_id": "IS_GROSS_PROFIT",
                "family": "AE",
                "observed_key": "gross_profit",
                "expected_terms": (("revenue", 1.0), ("cost_of_revenue", -1.0)),
                "absolute_keys": ("cost_of_revenue",),
            }
        )
    if {"net_change_cash", "cfo", "cfi", "cff", "fx_effect"} <= keys:
        relations.append(
            {
                "relation_id": "CFS_COMPONENT_SUM",
                "family": "CL",
                "observed_key": "net_change_cash",
                "expected_terms": (
                    ("cfo", 1.0),
                    ("cfi", 1.0),
                    ("cff", 1.0),
                    ("fx_effect", 1.0),
                ),
            }
        )

    current = provenance.get("cash")
    prior = provenance.get("prior_cash")
    change = provenance.get("net_change_cash")
    compatible = False
    if isinstance(current, Mapping) and isinstance(change, Mapping):
        compatible = (
            current.get("concept")
            == "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
            and change.get("concept")
            == "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"
        ) or (
            current.get("concept") == "CashAndCashEquivalentsAtCarryingValue"
            and change.get("concept") == "CashAndCashEquivalentsPeriodIncreaseDecrease"
        )
    if (
        {"cash", "prior_cash", "net_change_cash"} <= keys
        and isinstance(current, Mapping)
        and isinstance(prior, Mapping)
        and current.get("concept") == prior.get("concept")
        and compatible
    ):
        relations.append(
            {
                "relation_id": "CASH_ROLL_FORWARD",
                "family": "YOY",
                "observed_key": "cash",
                "expected_terms": (("prior_cash", 1.0), ("net_change_cash", 1.0)),
            }
        )
    return relations


def expected(relation: Mapping[str, Any], values: Mapping[str, float]) -> float:
    absolute = set(relation.get("absolute_keys", ()))
    total = 0.0
    for key, coefficient in relation["expected_terms"]:
        value = float(values[key])
        if key in absolute:
            value = abs(value)
        total += float(coefficient) * value
    return total


def predict(case: Mapping[str, Any]) -> dict[str, Any]:
    raw_values = case.get("values", {})
    provenance = case.get("provenance", {})
    if not isinstance(raw_values, Mapping) or not isinstance(provenance, Mapping):
        return {
            "policy_id": POLICY_ID,
            "decision": "ABSTAIN",
            "relation_count": 0,
            "failed_relations": [],
            "all_relations": [],
            "visible_keys": [],
        }

    values = {
        str(key): float(value)
        for key, value in raw_values.items()
        if is_number(value)
    }
    relations = relation_specs(values, provenance)
    enabled = case.get("enabled_relation_ids")
    if isinstance(enabled, list):
        enabled_set = {str(value) for value in enabled}
        relations = [
            relation
            for relation in relations
            if relation["relation_id"] in enabled_set
        ]

    checks: list[dict[str, Any]] = []
    for relation in relations:
        observed = values[relation["observed_key"]]
        exp = expected(relation, values)
        tol = tolerance(observed, exp)
        residual = observed - exp
        checks.append(
            {
                "relation_id": relation["relation_id"],
                "family": relation["family"],
                "observed_key": relation["observed_key"],
                "expected_keys": [
                    key for key, _ in relation["expected_terms"]
                ],
                "observed": observed,
                "expected": exp,
                "residual": residual,
                "tolerance": tol,
                "passed": abs(residual) <= tol,
            }
        )

    failed = [check for check in checks if not check["passed"]]
    if len(checks) < MIN_RELATIONS_FOR_DECISION:
        decision = "ABSTAIN"
    elif failed:
        decision = "ERROR"
    else:
        decision = "CLEAN"
    visible_keys = sorted(
        {check["observed_key"] for check in checks}
        | {
            key
            for check in checks
            for key in check["expected_keys"]
        }
    )
    return {
        "policy_id": POLICY_ID,
        "decision": decision,
        "relation_count": len(checks),
        "failed_relations": failed,
        "all_relations": checks,
        "visible_keys": visible_keys,
        "boundary": (
            "Only directly reported SEC facts from one accession and explicit "
            "accounting relations are judged. No residual, sector equivalence, "
            "missing value, or economic quantity is synthesized."
        ),
    }


def freeze_case_relations(case: Mapping[str, Any]) -> dict[str, Any] | None:
    """Preregister source-clean relations before any controlled perturbation."""
    import copy

    frozen = copy.deepcopy(case)
    values = {
        str(key): float(value)
        for key, value in frozen.get("values", {}).items()
    }
    candidates = relation_specs(values, frozen.get("provenance", {}))
    accepted: list[str] = []
    rejected: list[dict[str, Any]] = []
    for relation in candidates:
        observed = values[relation["observed_key"]]
        exp = expected(relation, values)
        residual = observed - exp
        tol = tolerance(observed, exp)
        record = {
            "relation_id": relation["relation_id"],
            "residual": residual,
            "tolerance": tol,
        }
        if abs(residual) <= tol:
            accepted.append(relation["relation_id"])
        else:
            rejected.append(record)
    if len(accepted) < MIN_RELATIONS_FOR_DECISION:
        return None
    frozen["enabled_relation_ids"] = accepted
    frozen["source_rejected_relations"] = rejected
    frozen["candidate_relation_count"] = len(candidates)
    frozen["enabled_relation_count"] = len(accepted)
    return frozen
