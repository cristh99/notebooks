from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

REQUIRED_EXECUTED = {"Exa", "SciSpace", "Scholar Sidekick", "Parallel Search", "Official and patent search"}
ALLOWED_BLOCKED = {"Elicit", "Scite"}
REQUIRED_NOT_NOVEL = {
    "public_payment_record_linkage",
    "procurement_supplier_name_reconciliation",
    "procurement_spending_knowledge_graphs",
    "OCDS_contract_lifecycle_transactions_and_documents",
    "adaptive_costly_information_acquisition",
    "noisy_expensive_test_selection",
    "provenance_and_refutation",
    "one_to_many_procurement_data_modeling",
    "procurement_payment_red_flags",
    "audit_document_sufficiency_and_three_way_matching",
    "purchase_order_invoice_vendor_reconciliation",
    "many_to_many_purchase_to_pay_process_modeling",
    "open_set_document_rejection",
    "contract_payment_reconciliation_patents",
    "Honduras_procurement_financial_system_integration",
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def verify(log: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if log.get("schema") != "fin-rvi-002/g09-prior-art-search-log/2":
        errors.append("schema")
    if log.get("cut_date") != "2026-08-03" or log.get("claim_id") != "FIN-RVI-002-C1":
        errors.append("identity")
    if log.get("status") != "PASS_BOUNDED_MULTI_INDEX_SEARCH":
        errors.append("status")
    protocol = log.get("protocol")
    if not isinstance(protocol, Mapping) or not all(
        protocol.get(key) for key in ("objective", "inclusion", "exclusion", "deduplication", "saturation_rule")
    ):
        errors.append("protocol")

    engines = log.get("engines")
    if not isinstance(engines, list):
        errors.append("engines")
    else:
        by_name = {engine.get("name"): engine for engine in engines if isinstance(engine, Mapping)}
        for name in REQUIRED_EXECUTED:
            if not str(by_name.get(name, {}).get("status", "")).startswith("EXECUTED"):
                errors.append(f"engine:{name}")
        for name in ALLOWED_BLOCKED:
            if not str(by_name.get(name, {}).get("status", "")).startswith("BLOCKED"):
                errors.append(f"blocked-engine:{name}")
        if not str(by_name.get("Consensus", {}).get("status", "")).startswith("EXECUTED"):
            errors.append("engine:Consensus")

    sources = log.get("primary_sources")
    if not isinstance(sources, list) or len(sources) < 20:
        errors.append("sources")
    else:
        kinds = Counter(source.get("kind") for source in sources if isinstance(source, Mapping))
        if kinds["scholarly"] < 10 or kinds["patent"] < 5:
            errors.append("source-coverage")
        if sum(kinds[kind] for kind in ("official_standard", "official_project", "official_report", "official_research")) < 4:
            errors.append("official-coverage")
        identifiers: list[str] = []
        for source in sources:
            if not isinstance(source, Mapping) or not source.get("title") or not source.get("absorbs"):
                errors.append("source-shape")
                continue
            identifier = next(
                (str(source[key]) for key in ("doi", "identifier", "url", "venue", "publisher") if source.get(key)),
                "",
            )
            identifiers.append(identifier)
        if len(set(identifiers)) != len(identifiers):
            errors.append("source-deduplication")

    disposition = log.get("component_disposition")
    if not isinstance(disposition, Mapping):
        errors.append("disposition")
    else:
        if not REQUIRED_NOT_NOVEL.issubset(set(disposition.get("not_novel", ()))):
            errors.append("not-novel-boundary")
        if disposition.get("exact_claim_match_found") is not False:
            errors.append("exact-match")
        candidate = str(disposition.get("remaining_original_candidate", ""))
        for phrase in ("ONCAE-SEFIN", "20 to 0", "58/58", "clean reconstruction"):
            if phrase not in candidate:
                errors.append("candidate-boundary")
                break

    limitations = log.get("limitations")
    if not isinstance(limitations, list) or len(limitations) < 4:
        errors.append("limitations")
    checks = log.get("completion_checks")
    if not isinstance(checks, Mapping) or not checks or not all(
        value is True or (key == "exact_claim_match_found" and value is False)
        for key, value in checks.items()
    ):
        errors.append("completion-checks")
    return errors


def build_receipt(log: Mapping[str, Any]) -> dict[str, Any]:
    errors = verify(log)
    payload = {
        "schema": "fin-rvi-002/g09-prior-art-receipt/2",
        "claim_id": log.get("claim_id"),
        "log_sha256": digest(log),
        "valid": not errors,
        "errors": errors,
        "status": log.get("status"),
        "exact_claim_match_found": log.get("component_disposition", {}).get("exact_claim_match_found"),
        "source_count": len(log.get("primary_sources", ())),
        "bounded_search_pass": not errors,
    }
    return {"payload": payload, "sha256": digest(payload)}


def main() -> int:
    source = Path("fin_rvi_002_g09/prior_art_search_log_20260803.json")
    log = json.loads(source.read_text(encoding="utf-8"))
    receipt = build_receipt(log)
    output = Path("reports/fin_rvi_002_g09")
    output.mkdir(parents=True, exist_ok=True)
    (output / "prior_art_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True, ensure_ascii=False))
    return 0 if receipt["payload"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
