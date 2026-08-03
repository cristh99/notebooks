from __future__ import annotations

import re
from typing import Any, Iterable

from fin_rvi_002_stage1.identity_v2 import adjudicate_object_v2
from fin_rvi_002_stage1.ocds import normalize_name, normalize_text

POLICY_ID = "FIN-RVI-002-DOCUMENTARY-V3"
PAYMENT_MARKERS = (
    "PAGO",
    "PAGADO",
    "ESTIMACION",
    "ANTICIPO",
    "DESEMBOLSO",
    "CANCELACION",
    "FACTURA",
    "ORDEN DE PAGO",
    "RESERVA DE CREDITO",
    "RESERVA DE FONDOS",
)


def _numeric_ids(values: Iterable[str]) -> set[str]:
    output: set[str] = set()
    for value in values:
        digits = "".join(re.findall(r"\d", str(value)))
        if len(digits) >= 8:
            output.add(digits)
    return output


def _names(values: Iterable[str]) -> set[str]:
    return {normalize_name(value) for value in values if normalize_name(value)}


def _identity_facts(left, right) -> dict[str, Any]:
    left_ids = _numeric_ids(left.supplier_ids)
    right_ids = _numeric_ids(right.supplier_ids)
    shared_ids = left_ids & right_ids
    left_names = _names(left.supplier_names)
    right_names = _names(right.supplier_names)
    shared_names = left_names & right_names
    contained_names = {
        (a, b)
        for a in left_names
        for b in right_names
        if min(len(a), len(b)) >= 8 and (a in b or b in a)
    }
    return {
        "numeric_conflict": bool(left_ids and right_ids and not shared_ids),
        "exact_numeric_support": bool(shared_ids),
        "name_support": bool(shared_names or contained_names),
        "shared_numeric_ids": sorted(shared_ids),
        "shared_names": sorted(shared_names),
    }


def adjudicate_policy_v3(left, right) -> dict[str, Any]:
    """Counterexample-guided policy fixed before the Stage 4 cohort.

    Stage 3 produced 17 unsafe promotions, all with incompatible non-empty
    numeric supplier identifiers, and one missed supported payment with an
    exact numeric identifier plus exact code and two specific object tokens.
    """
    base = adjudicate_object_v2(left, right)
    identity = _identity_facts(left, right)
    numeric_conflict = identity["numeric_conflict"]
    exact_numeric = identity["exact_numeric_support"]
    name_support = identity["name_support"]
    payment = any(marker in normalize_text(right.object_text) for marker in PAYMENT_MARKERS)
    hard_conflict = bool(base.get("hard_category_conflict"))
    shared_tokens = len(base.get("shared_tokens", ()))
    shared_classifications = bool(base.get("shared_classifications"))
    base_decision = str(base.get("decision", "UNRESOLVED"))

    if numeric_conflict:
        decision = "REJECTED"
        reason = "V3_NUMERIC_SUPPLIER_CONFLICT_VETO"
    elif (
        exact_numeric
        and payment
        and not hard_conflict
        and (shared_tokens >= 2 or shared_classifications)
    ):
        decision = "SUPPORTED"
        reason = "V3_EXACT_ID_PAYMENT_AND_OBJECT_SUPPORT"
    elif (
        base_decision == "SUPPORTED"
        and name_support
        and payment
        and not hard_conflict
        and (shared_tokens >= 6 or shared_classifications)
    ):
        decision = "SUPPORTED"
        reason = "V3_NAME_PAYMENT_AND_STRONG_OBJECT_SUPPORT"
    elif hard_conflict:
        decision = "REJECTED"
        reason = "V3_HARD_OBJECT_CONFLICT"
    else:
        decision = "UNRESOLVED"
        reason = "V3_INSUFFICIENT_JOINT_EVIDENCE"

    result = dict(base)
    result.update(identity)
    result.update(
        {
            "policy_id": POLICY_ID,
            "base_v2_decision": base_decision,
            "payment_language": payment,
            "shared_object_token_count": shared_tokens,
            "decision": decision,
            "reason": reason,
            "v3_numeric_conflict_veto": numeric_conflict,
            "v3_exact_id_rescue": (
                decision == "SUPPORTED"
                and reason == "V3_EXACT_ID_PAYMENT_AND_OBJECT_SUPPORT"
            ),
        }
    )
    return result
