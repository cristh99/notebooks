from __future__ import annotations

from typing import Any

from fin_rvi_002_stage1.identity_v2 import adjudicate_object_v2

POLICY_ID = "FIN-RVI-002-DOCUMENTARY-V3"


def adjudicate_policy_v3(left, right) -> dict[str, Any]:
    """Promote only when identity and object evidence jointly support payment.

    The two additions are fixed from Stage 3 counterexamples before Stage 4:

    1. incompatible non-empty numeric supplier identifiers are a hard veto;
    2. exact numeric identity plus payment language and strong document/object
       support can promote a row that the broad object taxonomy abstains on.
    """
    result = adjudicate_object_v2(left, right)
    numeric_conflict = bool(result.get("numeric_conflict"))
    exact_numeric = bool(result.get("exact_numeric_support"))
    name_support = bool(result.get("name_support"))
    payment = bool(result.get("payment_language"))
    document_available = bool(result.get("document_available"))
    hard_conflict = bool(result.get("hard_category_conflict"))
    shared_tokens = int(result.get("shared_object_token_count", 0))
    shared_classifications = bool(result.get("shared_classifications"))
    base_decision = str(result.get("decision", "UNRESOLVED"))

    if numeric_conflict:
        decision = "REJECTED"
        reason = "V3_NUMERIC_SUPPLIER_CONFLICT_VETO"
    elif exact_numeric and payment and not hard_conflict and (
        shared_classifications
        or shared_tokens >= 6
        or (document_available and shared_tokens >= 4)
    ):
        decision = "SUPPORTED"
        reason = "V3_EXACT_ID_PAYMENT_AND_DOCUMENT_OBJECT_SUPPORT"
    elif (
        base_decision == "SUPPORTED"
        and not hard_conflict
        and (exact_numeric or name_support)
        and payment
        and (shared_tokens >= 6 or shared_classifications)
    ):
        decision = "SUPPORTED"
        reason = "V3_BASE_SUPPORT_WITH_IDENTITY_AND_PAYMENT_GATE"
    elif (
        name_support
        and payment
        and document_available
        and not hard_conflict
        and shared_tokens >= 8
    ):
        decision = "SUPPORTED"
        reason = "V3_NAME_PAYMENT_AND_STRONG_DOCUMENT_SUPPORT"
    elif hard_conflict:
        decision = "REJECTED"
        reason = "V3_HARD_OBJECT_CONFLICT"
    else:
        decision = "UNRESOLVED"
        reason = "V3_INSUFFICIENT_JOINT_EVIDENCE"

    result = dict(result)
    result.update(
        {
            "policy_id": POLICY_ID,
            "base_v2_decision": base_decision,
            "decision": decision,
            "reason": reason,
            "v3_numeric_conflict_veto": numeric_conflict,
            "v3_exact_id_rescue": (
                decision == "SUPPORTED"
                and reason == "V3_EXACT_ID_PAYMENT_AND_DOCUMENT_OBJECT_SUPPORT"
            ),
        }
    )
    return result
