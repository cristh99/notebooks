from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class GoldRule:
    rule_id: str
    contract_or_project_codes: tuple[str, ...]
    any_phrases: tuple[str, ...]
    expected: str
    source_url: str
    rationale: str


GOLD_RULES = (
    GoldRule(
        "SIT_GA_001_PUBLICATION",
        ("SIT-GA-001-2024",),
        ("PUBLICACION", "PUBLICAR", "PERIODICO", "AVISO DE PRENSA"),
        "REJECTED",
        "https://app.notion.com/p/3ae790f0ca6981ca9f93e50a39917e5f",
        "El código aparece en el gasto de publicación; no es pago al proveedor de sellos.",
    ),
    GoldRule(
        "SIT_GA_001_SEALS",
        ("SIT-GA-001-2024",),
        ("SELLOS", "PRINT COLOR"),
        "SUPPORTED",
        "https://app.notion.com/p/3ae790f0ca6981719727d9abcc01c6c0",
        "Código, proveedor y objeto de los sellos son compatibles.",
    ),
    GoldRule(
        "SIT_CO_057_PAVEMENT_CONFLICT",
        ("SIT-CO-057-2024",),
        ("ORLY", "PAVIMENTACION", "AGALTECA", "MOCHITO"),
        "REJECTED",
        "https://app.notion.com/p/3ae790f0ca6981f99f67f4a143a9a657",
        "El mismo código se reutiliza con contraparte y objeto incompatibles.",
    ),
    GoldRule(
        "FHIS_108877_CONTRACTOR_PAYMENT",
        ("108877",),
        ("ANTICIPO", "PRIMERA ESTIMACION", "ESTIMACION"),
        "SUPPORTED",
        "https://app.notion.com/p/3ae790f0ca6981699facc35a6da2aace",
        "Anticipo y primera estimación pertenecen al contratista LEMPIRA.",
    ),
    GoldRule(
        "FHIS_108877_ANCILLARY",
        ("108877",),
        ("VIATICO", "COMBUSTIBLE", "SOCIALIZACION", "VISITA TECNICA", "ASAMBLEA"),
        "REJECTED",
        "https://app.notion.com/p/3ae790f0ca698199abd3cedffce1bb32",
        "Gasto relacionado con el proyecto, pero no pago contractual.",
    ),
    GoldRule(
        "ENP_05_23_EXPLICIT_PAYMENT",
        ("ENP-05-23", "ENP 05 23", "CONTRATO ENP 05 23"),
        ("PAGO", "FACTURA", "SERVICIO"),
        "SUPPORTED",
        "https://app.notion.com/p/3ae790f0ca6981bca881e29b33e77833",
        "SEFIN cita contrato, factura, servicio, institución y contraparte.",
    ),
    GoldRule(
        "SIT_CO_496_TEMPORAL_CONFLICT",
        ("SIT-CO-496-2024",),
        (),
        "UNRESOLVED",
        "https://app.notion.com/p/3ae790f0ca6981068938d4fba9f25a15",
        "Transacción 364 días antes de la firma publicada: requiere documento y fecha jurídica.",
    ),
    GoldRule(
        "SIT_SU_038_CONSORTIUM_MEMBER",
        ("SIT-SU-038-2024",),
        (),
        "UNRESOLVED",
        "https://app.notion.com/p/3ae790f0ca6981429d60ffc8ae1c2bb2",
        "Un miembro no equivale automáticamente al consorcio ni a la cuenta autorizada.",
    ),
    GoldRule(
        "FHIS_111585_111595_MULTICARDINAL",
        ("111585", "111595", "81789"),
        (),
        "UNRESOLVED",
        "https://app.notion.com/p/3ae790f0ca6981bda444e833b6373e74",
        "Un contrato cubre varios proyectos; el pago no puede distribuirse sin desglose.",
    ),
)


def normalize(value: str) -> str:
    value = value.upper().replace("Ñ", "N")
    return " ".join(re.findall(r"[A-Z0-9]+", value))


def flatten_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from flatten_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from flatten_strings(item)


def row_text(row: dict[str, Any]) -> str:
    return normalize(" | ".join(flatten_strings(row)))


def _contains_code(text: str, code: str) -> bool:
    normalized = normalize(code)
    if normalized.isdigit() and len(normalized) == 6:
        return bool(re.search(rf"\b{re.escape(normalized)}\b", text))
    return normalized in text


def matching_rules(row: dict[str, Any]) -> list[GoldRule]:
    text = row_text(row)
    matches: list[GoldRule] = []
    for rule in GOLD_RULES:
        if not any(_contains_code(text, code) for code in rule.contract_or_project_codes):
            continue
        if rule.any_phrases and not any(normalize(phrase) in text for phrase in rule.any_phrases):
            continue
        matches.append(rule)
    # Prefer phrase-specific rules over code-only fallbacks.
    matches.sort(key=lambda rule: (not bool(rule.any_phrases), rule.rule_id))
    if matches and matches[0].any_phrases:
        return [rule for rule in matches if rule.any_phrases]
    return matches[:1]


def actual_decision(row: dict[str, Any]) -> str:
    for key in ("decision", "object_decision", "final_decision", "status"):
        value = row.get(key)
        if value in {"SUPPORTED", "REJECTED", "UNRESOLVED"}:
            return value
    for key in ("object_evidence", "adjudication", "evidence_decision"):
        nested = row.get(key)
        if isinstance(nested, dict):
            value = nested.get("decision")
            if value in {"SUPPORTED", "REJECTED", "UNRESOLVED"}:
                return value
    return "UNKNOWN"


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    for row in rows:
        for rule in matching_rules(row):
            actual = actual_decision(row)
            safe = (
                actual == "SUPPORTED"
                if rule.expected == "SUPPORTED"
                else actual != "SUPPORTED"
            )
            evaluations.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "rule_id": rule.rule_id,
                    "expected": rule.expected,
                    "actual": actual,
                    "exact_agreement": actual == rule.expected,
                    "promotion_safe": safe,
                    "unsafe_overpromotion": rule.expected != "SUPPORTED" and actual == "SUPPORTED",
                    "source_url": rule.source_url,
                    "rationale": rule.rationale,
                }
            )
    matched_candidates = {item["candidate_id"] for item in evaluations}
    unsafe = sum(item["unsafe_overpromotion"] for item in evaluations)
    exact = sum(item["exact_agreement"] for item in evaluations)
    safe = sum(item["promotion_safe"] for item in evaluations)
    supported_expected = [item for item in evaluations if item["expected"] == "SUPPORTED"]
    supported_correct = sum(item["actual"] == "SUPPORTED" for item in supported_expected)
    return {
        "schema": "fin-rvi-002/known-adversarial-gold-evaluation/1",
        "gold_rules": len(GOLD_RULES),
        "holdout_rows": len(rows),
        "matched_candidates": len(matched_candidates),
        "evaluated_rule_hits": len(evaluations),
        "exact_agreements": exact,
        "promotion_safe": safe,
        "unsafe_overpromotions": unsafe,
        "supported_expected": len(supported_expected),
        "supported_recovered": supported_correct,
        "gate_no_unsafe_overpromotion": unsafe == 0,
        "evaluations": evaluations,
    }


def sha256_payload(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    output = Path("reports/fin_rvi_002_stage1")
    if len(__import__("sys").argv) > 1:
        output = Path(__import__("sys").argv[1])
    rows_path = output / "holdout_decisions.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line]
    result = evaluate(rows)
    result["sha256"] = sha256_payload(result)
    target = output / "known_adversarial_gold_evaluation.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "known_adversarial_gold_evaluation.sha256").write_text(
        f"{hashlib.sha256(target.read_bytes()).hexdigest()}  known_adversarial_gold_evaluation.json\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
