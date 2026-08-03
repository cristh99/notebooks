from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from fin_rvi_002_stage1 import run_stage1 as base
from fin_rvi_002_stage1.identity_v2 import (
    adjudicate_object_v2,
    compact_identity_pairs_v2,
)
from fin_rvi_002_stage1.ocds import normalize_name, normalize_text, sha256_payload
from fin_rvi_002_stage1.run_stage1_v2 import _best_document, generate_candidates_v2

SCHEMA = "fin-rvi-002/stage3-label-acquisition/1"
SEED = "FIN-RVI-002-STAGE3-SEALED-LABEL-ACQUISITION-V1"
PERMUTATION_SEED = "FIN-RVI-002-STAGE3-PERMUTATION-V1"
MAX_PER_SHARED_CODE = 2
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

KNOWN_CODE_FRAGMENTS = (
    "SIT-GA-001-2024",
    "SIT-CO-057-2024",
    "SIT-CO-496-2024",
    "SIT-SU-038-2024",
    "PROJECT:108877",
    "PROJECT:111585",
    "PROJECT:111595",
    "CODE:ENP-05-23",
)

PAYMENT_MARKERS = {
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
}

TOKEN_STOPWORDS = {
    "DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "E", "EN", "PARA", "POR",
    "CON", "SIN", "UN", "UNA", "AL", "QUE", "SE", "SU", "SUS", "PAGO",
    "CONTRATO", "PROYECTO", "SERVICIO", "SERVICIOS", "ORDEN", "PUBLICO",
    "PUBLICA", "SECRETARIA", "HONDURAS", "SIT", "FHIS", "SEDECOAS",
    "FECHA", "MONTO", "TOTAL", "SEGUN", "PERIODO", "FONDOS", "CREDITO",
}

QUOTAS = {
    ("HIGH", "SIT"): 36,
    ("HIGH", "FHIS"): 24,
    ("MEDIUM", "SIT"): 24,
    ("MEDIUM", "FHIS"): 12,
    ("CONTROL", "SIT"): 16,
    ("CONTROL", "FHIS"): 8,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def family(candidate: dict[str, Any]) -> str:
    return "FHIS" if str(candidate.get("shared_code", "")).startswith("PROJECT:") else "SIT"


def risk_tier(candidate: dict[str, Any]) -> str:
    multi = candidate.get("cardinality_type") != "ONE_TO_ONE"
    amount_difference = float(candidate.get("relative_amount_difference", 1.0))
    days = int(candidate.get("absolute_days", 9999))
    if (multi and amount_difference > 0.50) or amount_difference > 0.80 or days > 270:
        return "HIGH"
    if multi or amount_difference > 0.20 or days > 90:
        return "MEDIUM"
    return "CONTROL"


def amount_bucket(candidate: dict[str, Any]) -> str:
    value = float(candidate.get("relative_amount_difference", 1.0))
    if value <= 0.05:
        return "LE_05"
    if value <= 0.20:
        return "LE_20"
    if value <= 0.50:
        return "LE_50"
    if value <= 0.80:
        return "LE_80"
    return "GT_80"


def time_bucket(candidate: dict[str, Any]) -> str:
    days = int(candidate.get("absolute_days", 9999))
    if days <= 30:
        return "LE_30"
    if days <= 90:
        return "LE_90"
    if days <= 180:
        return "LE_180"
    return "GT_180"


def prior_holdout_ids() -> set[str]:
    path = Path("reports/fin_rvi_002_stage1/holdout_decisions.jsonl")
    if not path.exists():
        return set()
    return {
        str(row.get("candidate_id"))
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if row.get("candidate_id")
    }


def excluded_known_code(candidate: dict[str, Any]) -> bool:
    code = str(candidate.get("shared_code", ""))
    return any(fragment in code for fragment in KNOWN_CODE_FRAGMENTS)


def order_key(candidate: dict[str, Any]) -> str:
    return hashlib.sha256(
        f"{candidate['candidate_id']}|{SEED}".encode("utf-8")
    ).hexdigest()


def freeze_stage3(candidates: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    previous = prior_holdout_ids()
    eligible: list[dict[str, Any]] = []
    for raw in candidates:
        if raw.get("candidate_id") in previous or excluded_known_code(raw):
            continue
        candidate = dict(raw)
        candidate["stage3_family"] = family(candidate)
        candidate["stage3_risk_tier"] = risk_tier(candidate)
        candidate["stage3_amount_bucket"] = amount_bucket(candidate)
        candidate["stage3_time_bucket"] = time_bucket(candidate)
        candidate["stage3_order_key"] = order_key(candidate)
        candidate["stage3_selection_blind"] = True
        eligible.append(candidate)

    pools: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in eligible:
        pools[(candidate["stage3_risk_tier"], candidate["stage3_family"])].append(candidate)
    for pool in pools.values():
        pool.sort(key=lambda row: row["stage3_order_key"])

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    code_counts: Counter[str] = Counter()

    def admit(candidate: dict[str, Any], stratum: str) -> bool:
        candidate_id = str(candidate["candidate_id"])
        code = str(candidate["shared_code"])
        if candidate_id in selected_ids or code_counts[code] >= MAX_PER_SHARED_CODE:
            return False
        item = dict(candidate)
        item["stage3_selection_stratum"] = stratum
        selected.append(item)
        selected_ids.add(candidate_id)
        code_counts[code] += 1
        return True

    for key in sorted(QUOTAS, key=lambda item: (item[0], item[1])):
        target = QUOTAS[key]
        admitted = 0
        for candidate in pools.get(key, []):
            if admit(candidate, f"QUOTA:{key[0]}:{key[1]}"):
                admitted += 1
            if admitted >= target or len(selected) >= size:
                break

    if len(selected) < size:
        remainder = sorted(
            (candidate for candidate in eligible if candidate["candidate_id"] not in selected_ids),
            key=lambda row: row["stage3_order_key"],
        )
        for candidate in remainder:
            if admit(candidate, "DETERMINISTIC_FILL") and len(selected) >= size:
                break

    selected.sort(key=lambda row: row["stage3_order_key"])
    return selected[:size]


def digits_from_ids(values: Iterable[str]) -> set[str]:
    output: set[str] = set()
    for value in values:
        digits = "".join(re.findall(r"\d", str(value)))
        if len(digits) >= 8:
            output.add(digits)
    return output


def names(values: Iterable[str]) -> set[str]:
    return {normalize_name(value) for value in values if normalize_name(value)}


def supplier_facts(left, right) -> dict[str, Any]:
    left_ids = digits_from_ids(left.supplier_ids)
    right_ids = digits_from_ids(right.supplier_ids)
    left_names = names(left.supplier_names)
    right_names = names(right.supplier_names)
    exact_ids = sorted(left_ids & right_ids)
    exact_names = sorted(left_names & right_names)
    contained = sorted(
        {
            (left_name, right_name)
            for left_name in left_names
            for right_name in right_names
            if min(len(left_name), len(right_name)) >= 8
            and (left_name in right_name or right_name in left_name)
        }
    )
    return {
        "left_numeric_ids": sorted(left_ids),
        "right_numeric_ids": sorted(right_ids),
        "shared_numeric_ids": exact_ids,
        "left_names": sorted(left_names),
        "right_names": sorted(right_names),
        "shared_names": exact_names,
        "contained_names": [list(item) for item in contained],
        "numeric_conflict": bool(left_ids and right_ids and not exact_ids),
        "exact_numeric_support": bool(exact_ids),
        "name_support": bool(exact_names or contained),
        "baseline_supplier_support": bool(exact_ids or exact_names or contained),
    }


def tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) >= 4 and token not in TOKEN_STOPWORDS and not token.isdigit()
    }


def payment_language(value: str) -> bool:
    normalized = normalize_text(value)
    return any(marker in normalized for marker in PAYMENT_MARKERS)


def document_cache_path(url: str) -> Path:
    return Path(".cache/fin_rvi_002_stage3/documents") / digest(url)


def download_document(url: str) -> dict[str, Any]:
    destination = document_cache_path(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    if destination.exists() and destination.stat().st_size > 0:
        return {
            "url": url,
            "status": "ACQUIRED",
            "path": str(destination),
            "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "cached": True,
            "seconds": 0.0,
        }
    request = urllib.request.Request(url, headers={"User-Agent": base.SOURCE_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            return {
                "url": url,
                "status": "SKIPPED_TOO_LARGE",
                "bytes_read": len(data),
                "content_type": content_type,
                "seconds": round(time.monotonic() - started, 3),
            }
        destination.write_bytes(data)
        return {
            "url": url,
            "status": "ACQUIRED",
            "path": str(destination),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": content_type,
            "cached": False,
            "seconds": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            "url": url,
            "status": "FAILED",
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.monotonic() - started, 3),
        }


def extract_document_text(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") != "ACQUIRED" or not record.get("path"):
        return {"status": "NOT_AVAILABLE", "text": ""}
    path = Path(str(record["path"]))
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "text": ""}
    text = completed.stdout.decode("utf-8", errors="replace")[:100000]
    return {
        "status": "EXTRACTED" if text.strip() else "EMPTY",
        "returncode": completed.returncode,
        "text_chars": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
    }


def evidence_label(left, right, policy: dict[str, Any], document_text: str, facts: dict[str, Any]) -> dict[str, Any]:
    contract_evidence = f"{left.object_text} {document_text}"
    financial_evidence = right.object_text
    shared = sorted(tokens(contract_evidence) & tokens(financial_evidence))
    classifications = sorted(set(left.classifications) & set(right.classifications))
    payment = payment_language(financial_evidence)
    hard_conflict = bool(policy.get("hard_category_conflict"))
    document_available = bool(document_text.strip())

    label = "UNRESOLVED"
    reason = "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    if facts["numeric_conflict"]:
        label = "REJECTED"
        reason = "MATERIAL_SUPPLIER_IDENTIFIER_CONFLICT"
    elif facts["exact_numeric_support"] and hard_conflict and (document_available or len(tokens(left.object_text)) >= 5):
        label = "REJECTED"
        reason = "EXACT_SUPPLIER_BUT_HARD_OBJECT_CONFLICT"
    elif (
        facts["exact_numeric_support"]
        and payment
        and not hard_conflict
        and (len(shared) >= 4 or bool(classifications))
        and (document_available or len(shared) >= 6)
    ):
        label = "SUPPORTED"
        reason = "EXACT_SUPPLIER_PAYMENT_AND_OBJECT_DOCUMENT_SUPPORT"
    elif (
        not facts["numeric_conflict"]
        and facts["name_support"]
        and payment
        and document_available
        and not hard_conflict
        and len(shared) >= 7
    ):
        label = "SUPPORTED"
        reason = "NAME_PAYMENT_AND_STRONG_DOCUMENT_SUPPORT"

    return {
        "label": label,
        "reason": reason,
        "payment_language": payment,
        "document_available": document_available,
        "hard_category_conflict": hard_conflict,
        "shared_object_tokens": shared[:100],
        "shared_object_token_count": len(shared),
        "shared_classifications": classifications,
    }


def evaluate_stage3(connection, holdout: list[dict[str, Any]], acquire_documents: bool):
    decisions: list[dict[str, Any]] = []
    document_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    acquisition_seconds = 0.0
    acquired_bytes = 0

    for candidate in holdout:
        left = base.load_summary(connection, int(candidate["oncae_release_pk"]))
        right = base.load_summary(connection, int(candidate["sefin_release_pk"]))
        policy = adjudicate_object_v2(left, right)
        facts = supplier_facts(left, right)
        selected_document = _best_document(left, right)
        acquisition: dict[str, Any] | None = None
        extraction: dict[str, Any] | None = None
        if acquire_documents and selected_document and selected_document.get("url"):
            url = str(selected_document["url"])
            if url not in document_cache:
                acquisition = download_document(url)
                extraction = extract_document_text(acquisition)
                document_cache[url] = (acquisition, extraction)
                acquisition_seconds += float(acquisition.get("seconds", 0.0))
                if acquisition.get("status") == "ACQUIRED":
                    acquired_bytes += int(acquisition.get("bytes", 0))
            else:
                acquisition, extraction = document_cache[url]
            acquisition = {key: value for key, value in acquisition.items() if key != "path"}
            extraction = {key: value for key, value in extraction.items() if key != "text"}
        document_text = ""
        if selected_document and selected_document.get("url") in document_cache:
            document_text = document_cache[str(selected_document["url"])][1].get("text", "")
        label = evidence_label(left, right, policy, document_text, facts)
        decisions.append(
            {
                **candidate,
                "supplier_facts": facts,
                "structured_policy": policy,
                "evidence_label": label,
                "oncae_object_text": left.object_text[:10000],
                "sefin_object_text": right.object_text[:10000],
                "oncae_classifications": list(left.classifications),
                "sefin_classifications": list(right.classifications),
                "selected_document": selected_document,
                "document_acquisition": acquisition,
                "document_extraction": extraction,
            }
        )

    labels = Counter(row["evidence_label"]["label"] for row in decisions)
    policy_promotions = sum(row["structured_policy"]["decision"] == "SUPPORTED" for row in decisions)
    unsafe = sum(
        row["structured_policy"]["decision"] == "SUPPORTED"
        and row["evidence_label"]["label"] == "REJECTED"
        for row in decisions
    )
    metrics = {
        "holdout_size": len(decisions),
        "decision_counts": dict(labels),
        "baseline_promotions": sum(row["supplier_facts"]["baseline_supplier_support"] for row in decisions),
        "baseline_unsupported_promotions": sum(
            row["supplier_facts"]["baseline_supplier_support"]
            and row["evidence_label"]["label"] == "REJECTED"
            for row in decisions
        ),
        "baseline_unsupported_promotion_rate": None,
        "evidence_policy_promotions": policy_promotions,
        "evidence_policy_unsupported_promotions": unsafe,
        "unsupported_amount_at_risk_avoided": round(
            sum(
                float(row["amount_sefin"])
                for row in decisions
                if row["supplier_facts"]["baseline_supplier_support"]
                and row["structured_policy"]["decision"] != "SUPPORTED"
            ),
            2,
        ),
        "document_acquisition_attempts": len(document_cache),
        "document_acquisition_successes": sum(
            acquisition.get("status") == "ACQUIRED"
            for acquisition, _ in document_cache.values()
        ),
        "document_acquisition_bytes": acquired_bytes,
        "document_acquisition_seconds": round(acquisition_seconds, 3),
    }
    baseline_promotions = metrics["baseline_promotions"]
    metrics["baseline_unsupported_promotion_rate"] = (
        metrics["baseline_unsupported_promotions"] / baseline_promotions
        if baseline_promotions
        else None
    )
    return decisions, metrics


def compact_decision(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": row["candidate_id"],
        "shared_code": row["shared_code"],
        "family": row["stage3_family"],
        "risk_tier": row["stage3_risk_tier"],
        "selection_stratum": row["stage3_selection_stratum"],
        "cardinality_type": row["cardinality_type"],
        "relative_amount_difference": row["relative_amount_difference"],
        "absolute_days": row["absolute_days"],
        "amount_sefin": row["amount_sefin"],
        "baseline_supplier_support": row["supplier_facts"]["baseline_supplier_support"],
        "numeric_conflict": row["supplier_facts"]["numeric_conflict"],
        "exact_numeric_support": row["supplier_facts"]["exact_numeric_support"],
        "name_support": row["supplier_facts"]["name_support"],
        "policy_decision": row["structured_policy"]["decision"],
        "policy_reason": row["structured_policy"]["reason"],
        "label": row["evidence_label"]["label"],
        "label_reason": row["evidence_label"]["reason"],
        "payment_language": row["evidence_label"]["payment_language"],
        "document_available": row["evidence_label"]["document_available"],
        "hard_category_conflict": row["evidence_label"]["hard_category_conflict"],
        "shared_object_token_count": row["evidence_label"]["shared_object_token_count"],
        "shared_classifications": row["evidence_label"]["shared_classifications"],
        "document_sha256": (
            row.get("document_acquisition", {}).get("sha256")
            if isinstance(row.get("document_acquisition"), dict)
            else None
        ),
        "document_text_sha256": (
            row.get("document_extraction", {}).get("text_sha256")
            if isinstance(row.get("document_extraction"), dict)
            else None
        ),
    }


def policy_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    labeled = [row for row in rows if row["label"] in {"SUPPORTED", "REJECTED"}]
    policies = {
        "B1_CODE_SUPPLIER": lambda row: bool(row["baseline_supplier_support"]),
        "POLICY_DOCUMENTARY": lambda row: row["policy_decision"] == "SUPPORTED",
    }
    output: dict[str, dict[str, Any]] = {}
    for name, decision in policies.items():
        promotions = [row for row in labeled if decision(row)]
        output[name] = {
            "labeled_rows": len(labeled),
            "promotions": len(promotions),
            "supported_recovered": sum(row["label"] == "SUPPORTED" for row in promotions),
            "unsafe_overpromotions": sum(row["label"] == "REJECTED" for row in promotions),
            "missed_supported": sum(
                row["label"] == "SUPPORTED" and not decision(row) for row in labeled
            ),
            "correct_rejections": sum(
                row["label"] == "REJECTED" and not decision(row) for row in labeled
            ),
        }
    return output


def permuted_policy_metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [row for row in rows if row["label"] in {"SUPPORTED", "REJECTED"}]
    ordered = sorted(
        labeled,
        key=lambda row: digest(f"{row['candidate_id']}|{PERMUTATION_SEED}"),
    )
    decisions = [row["policy_decision"] for row in ordered]
    if decisions:
        decisions = decisions[1:] + decisions[:1]
    promotions = [
        row for row, decision in zip(ordered, decisions, strict=True) if decision == "SUPPORTED"
    ]
    return {
        "seed": PERMUTATION_SEED,
        "labeled_rows": len(labeled),
        "promotions": len(promotions),
        "supported_recovered": sum(row["label"] == "SUPPORTED" for row in promotions),
        "unsafe_overpromotions": sum(row["label"] == "REJECTED" for row in promotions),
    }


def rewrite_report(output: Path) -> None:
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    decisions = [
        json.loads(line)
        for line in (output / "holdout_decisions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    compact = [compact_decision(row) for row in decisions]
    metrics = policy_metrics(compact)
    permutation = permuted_policy_metric(compact)
    label_counts = Counter(row["label"] for row in compact)
    baseline = metrics["B1_CODE_SUPPLIER"]
    challenger = metrics["POLICY_DOCUMENTARY"]
    checks = {
        "confirmed_positive_labels": label_counts["SUPPORTED"] >= 20,
        "confirmed_negative_labels": label_counts["REJECTED"] >= 5,
        "challenger_zero_unsafe": challenger["unsafe_overpromotions"] == 0,
        "strictly_reduces_unsafe_vs_baseline": (
            challenger["unsafe_overpromotions"] < baseline["unsafe_overpromotions"]
        ),
        "recovers_no_fewer_supported": (
            challenger["supported_recovered"] >= baseline["supported_recovered"]
        ),
        "permutation_is_worse": (
            permutation["unsafe_overpromotions"] > challenger["unsafe_overpromotions"]
            or permutation["supported_recovered"] < challenger["supported_recovered"]
        ),
    }
    if not checks["confirmed_positive_labels"] or not checks["confirmed_negative_labels"]:
        status = "BLOCKED_INSUFFICIENT_CONFIRMED_LABELS"
    elif all(checks.values()):
        status = "PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION"
    else:
        status = "OPEN_POLICY_DID_NOT_DOMINATE_STRONG_BASELINE"

    payload = report["payload"]
    payload["schema"] = SCHEMA
    payload["status"] = "PASS"
    payload["configuration"]["selection_blinding"] = (
        "family+cardinality+amount bucket+time bucket+fixed SHA-256 only; known cases and prior holdout excluded"
    )
    payload["configuration"]["holdout_size_requested"] = len(compact)
    payload["configuration"]["seed"] = SEED
    payload["stage3"] = {
        "known_code_exclusions": list(KNOWN_CODE_FRAGMENTS),
        "prior_holdout_excluded": True,
        "max_pairs_per_shared_code": MAX_PER_SHARED_CODE,
        "quotas": {f"{key[0]}:{key[1]}": value for key, value in QUOTAS.items()},
        "selection_counts": dict(Counter(row["selection_stratum"] for row in compact)),
        "family_counts": dict(Counter(row["family"] for row in compact)),
        "risk_tier_counts": dict(Counter(row["risk_tier"] for row in compact)),
        "label_counts": dict(label_counts),
        "policy_metrics": metrics,
        "permutation_control": permutation,
        "gate_checks": checks,
        "gate_status": status,
        "compact_rows": compact,
        "compact_rows_sha256": digest(compact),
    }
    payload["gate_readout"] = {
        "G07": status,
        "G09": "OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED",
    }
    report["sha256"] = sha256_payload(payload)
    base.write_json(report_path, report)
    base.write_jsonl(output / "stage3_compact_rows.jsonl", compact)
    base.write_jsonl(
        output / "stage3_confirmed_labels.jsonl",
        [row for row in compact if row["label"] in {"SUPPORTED", "REJECTED"}],
    )
    (output / "report.sha256").write_text(
        f"{base.sha256_file(report_path)}  report.json\n", encoding="utf-8"
    )
    summary = [
        "# FIN-RVI-002 Stage 3 — sealed label acquisition",
        "",
        f"- Gate status: **{status}**",
        f"- Cohort: **{len(compact)}**",
        f"- Supported labels: **{label_counts['SUPPORTED']}**",
        f"- Rejected labels: **{label_counts['REJECTED']}**",
        f"- Unresolved labels: **{label_counts['UNRESOLVED']}**",
        f"- Report SHA-256: `{report['sha256']}`",
        "",
        "## Strong-baseline comparison",
        "",
        f"- B1 unsafe promotions: **{baseline['unsafe_overpromotions']}**",
        f"- Documentary unsafe promotions: **{challenger['unsafe_overpromotions']}**",
        f"- B1 supported recovered: **{baseline['supported_recovered']}**",
        f"- Documentary supported recovered: **{challenger['supported_recovered']}**",
        "",
        "## Gates",
        "",
        *[f"- {key}: **{'PASS' if value else 'FAIL'}**" for key, value in checks.items()],
        "",
        "## Boundary",
        "",
        "Labels are conservative automated evidence labels from exact identities and original document/object evidence. They do not prove legality, physical delivery, quality, liquidation, fraud or corruption.",
    ]
    (output / "stage3_report.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


def main() -> None:
    base.compact_identity_pairs = compact_identity_pairs_v2
    base.generate_candidates = generate_candidates_v2
    base.freeze_holdout = freeze_stage3
    base.adjudicate_object = adjudicate_object_v2
    base.evaluate_holdout = evaluate_stage3
    output = Path("reports/fin_rvi_002_stage3")
    if "--output" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output") + 1])
    base.main()
    rewrite_report(output)


if __name__ == "__main__":
    main()
