"""Fail-closed evidence ladder for contractor-payment attribution.

The policy never receives gold labels or split metadata. It promotes only the
maximum claim supported by payment nature, payee authority, object, chronology,
and allocation/cardinality evidence.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

AUXILIARY_PHRASES = (
    "GASTOS DE VIAJE",
    "GASTO DE VIAJE",
    "VIATICO",
    "VIATICOS",
    "COMBUSTIBLE PARA LA VISITA",
    "COMBUSTIBLE PARA REALIZAR VISITA",
    "SOCIALIZACION",
    "ASAMBLEAS INFORMATIVAS",
    "PUBLICACION",
    "PERIODICO",
    "AVISO DE PRENSA",
)
PAYMENT_PHRASES = (
    "PAGO DE ANTICIPO",
    "PAGO 20 DE ANTICIPO",
    "PAGO DE COMPRA",
    "ANTICIPO DE CONTRATO",
    "ANTICIPO DE INVERSION",
    "PAGO ESTIMACION",
    "PAGO DE ESTIMACION",
    "PAGO UNICO",
    "PAGO PARCIAL",
    "PARCIAL DEL PAGO",
    "PARCIAL DE PAGO",
    "COMPLEMENTO DE PAGO",
    "COMPLEMENTO DEL PAGO",
    "PAGO COMPLEMENTARIO",
    "FACTURA",
    "ESTIMACION",
    "INFORME FINAL",
)
REVERSAL_PHRASES = ("REVERSION", "REVERSA")
RESERVATION_PHRASES = (
    "RESERVA DE FONDOS",
    "RESERVA DE CREDITO",
    "RESERVA DE PAGO",
)
CONSORTIUM_TERMS = {"ASOCIACION", "CONSORCIO", "UNION", "UTE"}
GENERIC_OBJECT_TOKENS = {
    "PAGO",
    "CONTRATO",
    "PROYECTO",
    "COMPRA",
    "SERVICIO",
    "SERVICIOS",
    "SECRETARIA",
    "SEGUN",
    "PARA",
    "DIFERENTES",
    "UNIDADES",
    "FACTURA",
    "FACT",
}
DISTINCTIVE_OBJECT_TOKENS = {
    "SELLOS",
    "LIMPIEZA",
    "PAVIMENTACION",
    "ANTICIPO",
    "ESTIMACION",
}
POLICY_FIELDS = (
    "target",
    "oncae_ocid",
    "sefin_ocid",
    "oncae_supplier_names",
    "sefin_supplier_names",
    "oncae_supplier_ids",
    "sefin_supplier_ids",
    "supplier_supported",
    "documentary_decision",
    "oncae_object_text",
    "sefin_object_text",
    "oncae_dates",
    "sefin_dates",
    "relative_amount_difference",
    "amount_sefin",
)
FORBIDDEN_POLICY_FIELDS = {
    "gold_expected",
    "gold_rule",
    "split",
    "source_url",
}


def normalize(value: object) -> str:
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(character)
    ).upper()
    return " ".join(re.findall(r"[A-Z0-9]+", text))


def policy_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only fields visible to the policy and reject missing inputs."""
    if FORBIDDEN_POLICY_FIELDS & set(POLICY_FIELDS):
        raise AssertionError("gold leakage in POLICY_FIELDS")
    missing = [field for field in POLICY_FIELDS if field not in row]
    if missing:
        raise ValueError(f"policy row is missing fields: {missing}")
    return {field: row[field] for field in POLICY_FIELDS}


def _numeric_identifiers(values: list[str] | tuple[str, ...]) -> set[str]:
    output: set[str] = set()
    for value in values:
        digits = "".join(re.findall(r"\d", str(value)))
        if len(digits) >= 8:
            output.add(digits)
    return output


def consortium_authority_ambiguous(row: Mapping[str, Any]) -> bool:
    if _numeric_identifiers(row["oncae_supplier_ids"]) & _numeric_identifiers(
        row["sefin_supplier_ids"]
    ):
        return False
    left_names = [set(normalize(value).split()) for value in row["oncae_supplier_names"]]
    right_names = [set(normalize(value).split()) for value in row["sefin_supplier_names"]]
    for left in left_names:
        for right in right_names:
            if left & CONSORTIUM_TERMS and right and right < left and len(left - right) >= 2:
                return True
    return False


def event_kind(row: Mapping[str, Any]) -> str:
    text = normalize(row["sefin_object_text"])
    if any(phrase in text for phrase in AUXILIARY_PHRASES):
        return "AUXILIARY"
    has_payment = any(phrase in text for phrase in PAYMENT_PHRASES)
    has_reversal = any(phrase in text for phrase in REVERSAL_PHRASES)
    has_reservation = any(phrase in text for phrase in RESERVATION_PHRASES)
    if has_reversal:
        return "MIXED_ACCOUNTING" if has_payment else "NONPAYMENT_ACCOUNTING"
    if has_reservation and not has_payment:
        return "NONPAYMENT_ACCOUNTING"
    if has_payment:
        return "CONTRACT_PAYMENT"
    return "UNKNOWN"


def semantic_object_support(row: Mapping[str, Any]) -> bool:
    if row["documentary_decision"] == "SUPPORTED":
        return True
    left = {
        token
        for token in normalize(row["oncae_object_text"]).split()
        if len(token) >= 5 and token not in GENERIC_OBJECT_TOKENS
    }
    right = {
        token
        for token in normalize(row["sefin_object_text"]).split()
        if len(token) >= 5 and token not in GENERIC_OBJECT_TOKENS
    }
    shared = left & right
    return len(shared) >= 2 or bool(shared & DISTINCTIVE_OBJECT_TOKENS)


def temporal_status(row: Mapping[str, Any]) -> str:
    try:
        oncae_dates = [date.fromisoformat(value) for value in row["oncae_dates"]]
        sefin_dates = [date.fromisoformat(value) for value in row["sefin_dates"]]
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not oncae_dates or not sefin_dates:
        return "UNKNOWN"
    source_span_days = (max(oncae_dates) - min(oncae_dates)).days
    if source_span_days >= 300 and min(sefin_dates) <= max(oncae_dates):
        return "UNKNOWN_SOURCE_DATE_SEMANTICS"
    if min(sefin_dates) < min(oncae_dates):
        lead_days = (min(oncae_dates) - min(sefin_dates)).days
        if lead_days > 45:
            return "UNKNOWN_PAYMENT_PRECEDES_PROCUREMENT_EVIDENCE"
    return "CONSISTENT"


def cardinality_status(row: Mapping[str, Any]) -> str:
    text = normalize(row["sefin_object_text"])
    text = re.sub(
        r"\b(?:OP|REF|CTTO|CONTRATO|FACTURA|PAGO|ORDEN)\s*(?:NO)?\s*\d[0-9 ]{3,}",
        " ",
        text,
    )
    six_digit_codes = set(re.findall(r"\b\d{6}\b", text))
    target = normalize(row["target"])
    if target.isdigit() and len(target) == 6 and six_digit_codes - {target}:
        return "AMBIGUOUS_MULTI_PROJECT"
    return "RESOLVED"


def evidence_ladder(row: Mapping[str, Any]) -> dict[str, Any]:
    row = policy_view(row)
    kind = event_kind(row)
    authority = (
        "UNKNOWN_CONSORTIUM_AUTHORITY"
        if consortium_authority_ambiguous(row)
        else ("SUPPORTED" if row["supplier_supported"] else "REJECTED")
    )
    chronology = temporal_status(row)
    cardinality = cardinality_status(row)
    object_supported = semantic_object_support(row)
    blockers: list[str] = []

    if kind == "AUXILIARY":
        blockers.append("AUXILIARY_EXPENDITURE")
    elif kind in {"NONPAYMENT_ACCOUNTING", "MIXED_ACCOUNTING"}:
        blockers.append(kind)
    elif kind != "CONTRACT_PAYMENT":
        blockers.append("PAYMENT_NATURE_UNKNOWN")
    if authority != "SUPPORTED":
        blockers.append(f"PAYEE_AUTHORITY_{authority}")
    if not object_supported:
        blockers.append("OBJECT_NOT_SUPPORTED")
    if chronology != "CONSISTENT":
        blockers.append(f"TEMPORAL_{chronology}")
    if cardinality != "RESOLVED":
        blockers.append(f"CARDINALITY_{cardinality}")

    promote = not blockers
    if promote:
        decision = "SUPPORTED"
    elif kind == "AUXILIARY" or authority == "REJECTED":
        decision = "REJECTED"
    else:
        decision = "UNRESOLVED"
    return {
        "promote": promote,
        "decision": decision,
        "event_kind": kind,
        "authority": authority,
        "temporal": chronology,
        "cardinality": cardinality,
        "object_supported": object_supported,
        "blockers": blockers,
    }


def amount_decimal(row: Mapping[str, Any]) -> Decimal:
    return Decimal(str(row["amount_sefin"]))
