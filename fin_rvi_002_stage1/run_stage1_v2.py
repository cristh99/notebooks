from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from . import run_stage1 as base
from .identity_v2 import adjudicate_object_v2, compact_identity_pairs_v2
from .ocds import closest_amount, closest_days, sha256_payload

SEPARATOR = "\u241f"
SEED = base.SEED + "-CARDINALITY-PRESERVING-V2"


def generate_candidates_v2(connection, amount_tolerance: float, max_days: int) -> list[dict[str, Any]]:
    del amount_tolerance
    candidates: dict[tuple[int, int], dict[str, Any]] = {}
    query = """
    SELECT
      o.release_pk,
      s.release_pk,
      o.composite_key,
      o.identity_basis,
      s.identity_basis
    FROM party_pairs AS o
    JOIN party_pairs AS s
      ON ABS(s.source_year - o.source_year) <= 1
     AND s.composite_key = o.composite_key
    JOIN releases AS ro ON ro.release_pk = o.release_pk
    JOIN releases AS rs ON rs.release_pk = s.release_pk
    WHERE o.source = 'ONCAE'
      AND s.source = 'SEFIN'
      AND o.identity_basis LIKE '%_CODE'
      AND s.identity_basis LIKE '%_CODE'
      AND ro.min_day IS NOT NULL
      AND rs.min_day IS NOT NULL
      AND ro.max_day >= rs.min_day - ?
      AND rs.max_day >= ro.min_day - ?
    """
    cursor = connection.execute(query, (max_days, max_days))
    cache = {}

    def summary(pk: int):
        if pk not in cache:
            cache[pk] = base.load_summary(connection, pk)
        return cache[pk]

    for oncae_pk, sefin_pk, composite_key, left_basis, right_basis in cursor:
        pair_key = (int(oncae_pk), int(sefin_pk))
        left = summary(pair_key[0])
        right = summary(pair_key[1])
        days = closest_days(left.dates, right.dates)
        if days is None or days > max_days:
            continue
        amount_match = closest_amount(left.amounts, right.amounts)
        if amount_match is None:
            continue
        shared_code = composite_key.split(SEPARATOR, 1)[1]
        candidate = {
            "oncae_release_pk": pair_key[0],
            "sefin_release_pk": pair_key[1],
            "ocid_oncae": left.ocid,
            "ocid_sefin": right.ocid,
            "source_year": left.source_year,
            "sefin_year": right.source_year,
            "identity_basis": min(left_basis, right_basis),
            "shared_code": shared_code,
            "amount_oncae": amount_match[1],
            "amount_sefin": amount_match[2],
            "relative_amount_difference": round(amount_match[0], 8),
            "absolute_days": days,
            "linkage_rule": "CANONICAL_BUYER_ALIAS_AND_SHARED_CODE",
        }
        candidate["candidate_id"] = sha256_payload(candidate)
        previous = candidates.get(pair_key)
        if previous is None or (candidate["shared_code"], candidate["absolute_days"]) < (
            previous["shared_code"], previous["absolute_days"]
        ):
            candidates[pair_key] = candidate

    output = list(candidates.values())
    by_oncae = Counter(item["oncae_release_pk"] for item in output)
    by_sefin = Counter(item["sefin_release_pk"] for item in output)
    for item in output:
        item["candidates_for_oncae"] = by_oncae[item["oncae_release_pk"]]
        item["candidates_for_sefin"] = by_sefin[item["sefin_release_pk"]]
        left_count = item["candidates_for_oncae"]
        right_count = item["candidates_for_sefin"]
        if left_count == 1 and right_count == 1:
            cardinality = "ONE_TO_ONE"
        elif left_count > 1 and right_count == 1:
            cardinality = "ONE_ONCAE_TO_MANY_SEFIN"
        elif left_count == 1 and right_count > 1:
            cardinality = "MANY_ONCAE_TO_ONE_SEFIN"
        else:
            cardinality = "MANY_TO_MANY"
        item["cardinality_type"] = cardinality
        item["linkage_status"] = (
            "STRICT_1_TO_1" if cardinality == "ONE_TO_ONE" else "AMBIGUOUS"
        )
    return sorted(output, key=lambda item: item["candidate_id"])


def freeze_holdout_v2(candidates: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Freeze a blind holdout while preserving real payment cardinality.

    Half of the capacity is allocated to breadth (one pair per shared code),
    and half to additional pairs from codes with multiple financial events.
    Selection uses only code/cardinality and a fixed hash seed; supplier and
    object evidence are not inspected.
    """
    if size <= 0:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        candidate["holdout_order_key"] = hashlib.sha256(
            f"{candidate['candidate_id']}|{SEED}".encode("utf-8")
        ).hexdigest()
        grouped.setdefault(candidate["shared_code"], []).append(candidate)
    for group in grouped.values():
        group.sort(key=lambda item: item["holdout_order_key"])

    code_order = sorted(
        grouped,
        key=lambda code: hashlib.sha256(f"{code}|{SEED}".encode("utf-8")).hexdigest(),
    )
    breadth_target = min((size + 1) // 2, len(code_order))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for code in code_order[:breadth_target]:
        candidate = dict(grouped[code][0])
        candidate["holdout_stratum"] = "BREADTH_FIRST_PER_CODE"
        selected.append(candidate)
        selected_ids.add(candidate["candidate_id"])

    ambiguity_pool: list[dict[str, Any]] = []
    for code in code_order:
        for candidate in grouped[code][1:]:
            item = dict(candidate)
            item["holdout_stratum"] = "WITHIN_CODE_AMBIGUITY"
            ambiguity_pool.append(item)
    ambiguity_pool.sort(key=lambda item: item["holdout_order_key"])
    for candidate in ambiguity_pool:
        if len(selected) >= size:
            break
        if candidate["candidate_id"] not in selected_ids:
            selected.append(candidate)
            selected_ids.add(candidate["candidate_id"])

    fallback_pool = [
        dict(candidate)
        for candidate in candidates
        if candidate["candidate_id"] not in selected_ids
    ]
    fallback_pool.sort(key=lambda item: item["holdout_order_key"])
    for candidate in fallback_pool:
        if len(selected) >= size:
            break
        candidate["holdout_stratum"] = "DETERMINISTIC_FILL"
        selected.append(candidate)
        selected_ids.add(candidate["candidate_id"])

    selected.sort(key=lambda item: item["holdout_order_key"])
    return selected[:size]


_DOCUMENT_PRIORITY = {
    "financialTransaction": 120,
    "contractSigned": 110,
    "contractNotice": 100,
    "awardNotice": 90,
    "contractAmendment": 80,
    "completionCertificate": 75,
    "physicalProgressReport": 70,
    "recordOpeningTendersReceived": 40,
    "biddingDocuments": 30,
    "tenderNotice": 20,
}


def _best_document(left, right) -> dict[str, str] | None:
    candidates: list[tuple[int, int, str, dict[str, str]]] = []
    for source_rank, summary in enumerate((right, left)):
        for document in summary.documents:
            url = str(document.get("url") or "").strip()
            if not url:
                continue
            document_type = str(document.get("documentType") or "")
            priority = _DOCUMENT_PRIORITY.get(document_type, 10)
            candidates.append((-priority, source_rank, url, dict(document)))
    if not candidates:
        return None
    return min(candidates)[3]


def evaluate_holdout_v2(
    connection,
    holdout: list[dict[str, Any]],
    acquire_documents: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    acquisition_cache: dict[str, dict[str, Any]] = {}
    document_references = 0
    acquisition_seconds = 0.0

    for candidate in holdout:
        left = base.load_summary(connection, candidate["oncae_release_pk"])
        right = base.load_summary(connection, candidate["sefin_release_pk"])
        adjudication = adjudicate_object_v2(left, right)
        document = _best_document(left, right)
        document_acquisition: dict[str, Any] | None = None
        if acquire_documents and document is not None:
            document_references += 1
            url = document["url"]
            if url not in acquisition_cache:
                acquisition_cache[url] = base.acquire_public_document(url)
                acquisition_seconds += float(acquisition_cache[url].get("seconds", 0.0))
            document_acquisition = dict(acquisition_cache[url])
            document_acquisition["selected_document_type"] = document.get("documentType", "")
            document_acquisition["selected_document_title"] = document.get("title", "")
            document_acquisition["cache_reuse"] = sum(
                1 for row in decisions
                if isinstance(row.get("document_acquisition"), dict)
                and row["document_acquisition"].get("url") == url
            ) > 0

        decisions.append({
            **candidate,
            "object_adjudication": adjudication,
            "baseline_decision": "PROMOTE_CONTRACTOR_PAYMENT",
            "evidence_policy_decision": (
                "PROMOTE_SUPPORTED"
                if adjudication["decision"] == "SUPPORTED"
                else "ABSTAIN_OR_REJECT"
            ),
            "oncae_object_text": left.object_text[:5000],
            "sefin_object_text": right.object_text[:5000],
            "oncae_documents": list(left.documents)[:20],
            "sefin_documents": list(right.documents)[:20],
            "document_acquisition": document_acquisition,
        })

    decision_counts = Counter(
        item["object_adjudication"]["decision"] for item in decisions
    )
    unsupported_baseline = (
        decision_counts["REJECTED"] + decision_counts["UNRESOLVED"]
    )
    amount_at_risk = sum(
        float(item["amount_sefin"])
        for item in decisions
        if item["object_adjudication"]["decision"] != "SUPPORTED"
    )
    successes = sum(
        record.get("status") == "ACQUIRED" for record in acquisition_cache.values()
    )
    acquired_bytes = sum(
        int(record.get("bytes", 0))
        for record in acquisition_cache.values()
        if record.get("status") == "ACQUIRED"
    )
    metrics = {
        "holdout_size": len(decisions),
        "decision_counts": dict(decision_counts),
        "baseline_promotions": len(decisions),
        "baseline_unsupported_promotions": unsupported_baseline,
        "baseline_unsupported_promotion_rate": (
            unsupported_baseline / len(decisions) if decisions else None
        ),
        "evidence_policy_promotions": decision_counts["SUPPORTED"],
        "evidence_policy_unsupported_promotions": 0,
        "unsupported_amount_at_risk_avoided": round(amount_at_risk, 2),
        "document_references": document_references,
        "document_acquisition_attempts": len(acquisition_cache),
        "document_acquisition_cache_reuses": max(
            0, document_references - len(acquisition_cache)
        ),
        "document_acquisition_successes": successes,
        "document_acquisition_bytes": acquired_bytes,
        "document_acquisition_seconds": round(acquisition_seconds, 3),
    }
    return decisions, metrics


def _rewrite_report(output: Path) -> None:
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = report["payload"]
    payload["schema"] = "fin-rvi-002/stage1-public-data/2"
    payload["configuration"]["selection_blinding"] = (
        "canonical buyer alias + exact shared contract/project code + cardinality only; supplier identity and object text evaluated after freeze"
    )
    payload["configuration"]["holdout_design"] = (
        "50% breadth across shared codes, then within-code ambiguity, then deterministic fill; all ordered by fixed SHA-256 seed"
    )
    payload["candidate_reconstruction"]["rule"] = (
        "same or adjacent year + canonical buyer alias + exact shared contract/project code; amount and date retained as diagnostics; <=366-day temporal gate"
    )
    payload["candidate_reconstruction"]["identity_grammar"] = (
        "SIT/FHIS-SEDECOAS/ENP institutional aliases, normalized buyer cores, exact contract/project codes"
    )
    decisions_path = output / "holdout_decisions.jsonl"
    decision_rows = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line
    ] if decisions_path.exists() else []
    payload["holdout_metrics"]["cardinality_counts"] = dict(
        Counter(row.get("cardinality_type", "UNKNOWN") for row in decision_rows)
    )
    payload["holdout_metrics"]["stratum_counts"] = dict(
        Counter(row.get("holdout_stratum", "UNKNOWN") for row in decision_rows)
    )
    payload["holdout_metrics"]["unique_shared_codes"] = len(
        {row.get("shared_code") for row in decision_rows if row.get("shared_code")}
    )
    report["sha256"] = sha256_payload(payload)
    base.write_json(report_path, report)
    (output / "report.md").write_text(
        base.build_markdown({**payload, "sha256": report["sha256"]}), encoding="utf-8"
    )
    (output / "report.sha256").write_text(
        f"{base.sha256_file(report_path)}  report.json\n", encoding="utf-8"
    )

    decisions = decision_rows
    replay_payload = json.loads(json.dumps(payload))
    for record in replay_payload.get("downloads", []):
        for key in ("seconds", "attempt", "cached", "path"):
            record.pop(key, None)
    for record in replay_payload.get("dataset_stats", []):
        record.pop("seconds", None)
    replay_payload.get("holdout_metrics", {}).pop("document_acquisition_seconds", None)
    for decision in decisions:
        acquisition = decision.get("document_acquisition")
        if isinstance(acquisition, dict):
            acquisition.pop("seconds", None)
    deterministic = {
        "schema": "fin-rvi-002/stage1-deterministic-replay/2",
        "report_payload_without_timing": replay_payload,
        "holdout_decisions": decisions,
    }
    deterministic["sha256"] = sha256_payload(deterministic)
    base.write_json(output / "deterministic_replay.json", deterministic)


def main() -> None:
    base.compact_identity_pairs = compact_identity_pairs_v2
    base.generate_candidates = generate_candidates_v2
    base.freeze_holdout = freeze_holdout_v2
    base.adjudicate_object = adjudicate_object_v2
    base.evaluate_holdout = evaluate_holdout_v2
    output = Path("reports/fin_rvi_002_stage1")
    if "--output" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output") + 1])
    try:
        base.main()
    except SystemExit as exc:
        if exc.code not in (None, 0, 2):
            raise
    _rewrite_report(output)


if __name__ == "__main__":
    main()
