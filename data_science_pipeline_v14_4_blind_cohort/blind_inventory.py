from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator


class InventoryError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def normalized_amount(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        raise InventoryError("INVALID_CONTRACT_AMOUNT")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InventoryError("INVALID_CONTRACT_AMOUNT") from exc
    if not amount.is_finite() or amount <= 0:
        raise InventoryError("INVALID_CONTRACT_AMOUNT")
    normalized = format(amount.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def normalized_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise InventoryError("MISSING_CONTRACT_DATE")
    day = text[:10]
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError as exc:
        raise InventoryError("INVALID_CONTRACT_DATE") from exc


def releases_from_object(value: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any]]]:
    releases = value.get("releases")
    if isinstance(releases, list):
        for index, release in enumerate(releases):
            if isinstance(release, dict):
                yield index, release
        return
    records = value.get("records")
    if isinstance(records, list):
        offset = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            compiled = record.get("compiledRelease")
            if isinstance(compiled, dict):
                yield offset, compiled
                offset += 1
            record_releases = record.get("releases")
            if isinstance(record_releases, list):
                for release in record_releases:
                    if isinstance(release, dict):
                        yield offset, release
                        offset += 1
        return
    yield 0, value


def method_group(release: dict[str, Any]) -> tuple[str, str] | None:
    tender = release.get("tender")
    if not isinstance(tender, dict):
        return None
    method = str(tender.get("procurementMethod") or "").strip().lower()
    mapping = {"direct": "DIRECT", "open": "OPEN"}
    group = mapping.get(method)
    return (method, group) if group else None


def candidate_rows_from_release(
    release: dict[str, Any],
    *,
    archive_sha256: str,
    line_sha256: str,
    release_index: int,
    cutoff: str,
) -> Iterator[dict[str, Any]]:
    mapped = method_group(release)
    if mapped is None:
        return
    method, group = mapped
    contracts = release.get("contracts")
    if not isinstance(contracts, list):
        return
    for contract_index, contract in enumerate(contracts):
        if not isinstance(contract, dict):
            continue
        value = contract.get("value")
        if not isinstance(value, dict):
            continue
        currency = str(value.get("currency") or "").strip().upper()
        if currency != "HNL":
            continue
        try:
            amount = normalized_amount(value.get("amount"))
            event_date = normalized_date(contract.get("dateSigned"))
        except InventoryError:
            continue
        if event_date > cutoff:
            continue
        locator = {
            "archive_sha256": archive_sha256,
            "line_sha256": line_sha256,
            "release_index": release_index,
            "contract_index": contract_index,
            "selector_paths": [
                "$.tender.procurementMethod",
                f"$.contracts[{contract_index}].value.amount",
                f"$.contracts[{contract_index}].value.currency",
                f"$.contracts[{contract_index}].dateSigned",
            ],
        }
        projection = {
            "archive_sha256": archive_sha256,
            "line_sha256": line_sha256,
            "release_index": release_index,
            "contract_index": contract_index,
            "procurement_method": method,
            "event_role": "CONTRACT",
            "amount_role": "CONTRACT_VALUE",
            "date_role": "CONTRACT_DATE",
            "currency": currency,
            "event_date": event_date,
            "amount_commitment_sha256": sha256_bytes(amount.encode()),
        }
        yield {
            "event_commitment_sha256": sha256_value(projection),
            "procurement_method": method,
            "event_role": "CONTRACT",
            "amount_role": "CONTRACT_VALUE",
            "date_role": "CONTRACT_DATE",
            "currency": currency,
            "event_date": event_date,
            "resolution_state": "MATCH_OFFICIAL",
            "lineage_sha256": sha256_value(locator),
            "group": group,
        }


def selection_key(seed: str, event_commitment: str) -> str:
    return hashlib.sha256(f"{seed}:{event_commitment}".encode()).hexdigest()


def retain_smallest(items: list[dict[str, Any]], candidate: dict[str, Any], *, limit: int, seed: str) -> None:
    row = dict(candidate)
    row["selection_key_sha256"] = selection_key(seed, row["event_commitment_sha256"])
    items.append(row)
    items.sort(key=lambda value: (value["selection_key_sha256"], value["event_commitment_sha256"]))
    del items[limit:]


def scan_lines(
    lines: Iterable[bytes],
    *,
    archive_sha256: str,
    seed: str,
    retain_per_group: int = 20,
    cutoff: str = "2025-12-31",
) -> dict[str, Any]:
    retained: dict[str, list[dict[str, Any]]] = {"DIRECT": [], "OPEN": []}
    eligible_counts = {"DIRECT": 0, "OPEN": 0}
    line_count = 0
    release_count = 0
    contract_candidates = 0
    parse_errors = 0
    duplicate_commitments = 0
    seen: set[str] = set()

    for raw in lines:
        line_count += 1
        raw = raw.rstrip(b"\r\n")
        if not raw:
            continue
        line_sha = sha256_bytes(raw)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if not isinstance(value, dict):
            parse_errors += 1
            continue
        for release_index, release in releases_from_object(value):
            release_count += 1
            for row in candidate_rows_from_release(
                release,
                archive_sha256=archive_sha256,
                line_sha256=line_sha,
                release_index=release_index,
                cutoff=cutoff,
            ):
                contract_candidates += 1
                commitment = row["event_commitment_sha256"]
                if commitment in seen:
                    duplicate_commitments += 1
                    continue
                seen.add(commitment)
                group = row.pop("group")
                eligible_counts[group] += 1
                retain_smallest(retained[group], row, limit=retain_per_group, seed=seed)

    if parse_errors:
        raise InventoryError(f"JSON_PARSE_ERRORS:{parse_errors}")
    if duplicate_commitments:
        raise InventoryError(f"DUPLICATE_EVENT_COMMITMENTS:{duplicate_commitments}")

    public_rows: list[dict[str, Any]] = []
    for group in ["DIRECT", "OPEN"]:
        for row in retained[group]:
            public_rows.append({
                key: value
                for key, value in row.items()
                if key != "selection_key_sha256"
            })
    public_rows.sort(key=lambda row: (row["procurement_method"], selection_key(seed, row["event_commitment_sha256"]), row["event_commitment_sha256"]))

    return {
        "schema": "data-science-pipeline/analyze-blind-inventory/1",
        "source": {
            "archive_sha256": archive_sha256,
            "line_count": line_count,
            "release_count": release_count,
            "contract_candidates_before_deduplication": contract_candidates,
            "parse_errors": parse_errors,
            "duplicate_commitments": duplicate_commitments,
        },
        "eligible_counts": eligible_counts,
        "retained_per_group": {group: len(retained[group]) for group in ["DIRECT", "OPEN"]},
        "retained_candidate_rows": public_rows,
        "retained_candidate_rows_sha256": sha256_value(public_rows),
        "blinding": {
            "bid_count_accessed": False,
            "tenderer_count_accessed": False,
            "low_competition_accessed": False,
            "outcome_accessed": False,
            "identity_accessed": False,
            "ocid_accessed": False,
            "process_id_accessed": False,
            "raw_source_rows_retained": False,
        },
        "governance": {
            "external_cost_usd": 0.0,
            "production_modified": False,
            "analysis_executed": False,
            "stage10_unblocked": False,
        },
    }


def scan_archive(source_path: Path, source_freeze: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    raw_hash = sha256_bytes(source_path.read_bytes())
    if raw_hash != source_freeze["archive_sha256"]:
        raise InventoryError("SOURCE_ARCHIVE_SHA256_MISMATCH")
    seed = protocol["sampling"]["seed"]
    retain = int(protocol["sampling"]["primary_per_group"]) + int(protocol["sampling"]["reserve_per_group"])
    cutoff = protocol["candidate_contract"]["cutoff_date"]
    with gzip.open(source_path, "rb") as handle:
        result = scan_lines(handle, archive_sha256=raw_hash, seed=seed, retain_per_group=retain, cutoff=cutoff)
    result["coordination_id"] = protocol["coordination_id"]
    result["protocol_sha256"] = sha256_value(protocol)
    result["source"]["publication_id"] = source_freeze["publication_id"]
    result["source"]["source_year"] = source_freeze["source_year"]
    result["source"]["archive_url_commitment_sha256"] = sha256_bytes(source_freeze["archive_url"].encode())
    return result


def write_candidates(inventory: dict[str, Any], output_path: Path) -> None:
    rows = inventory["retained_candidate_rows"]
    output_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-freeze", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--inventory-output", type=Path, required=True)
    parser.add_argument("--candidates-output", type=Path, required=True)
    args = parser.parse_args()
    source_freeze = json.loads(args.source_freeze.read_text())
    protocol = json.loads(args.protocol.read_text())
    result = scan_archive(args.source, source_freeze, protocol)
    args.inventory_output.write_bytes(canonical_bytes(result))
    write_candidates(result, args.candidates_output)
    print(json.dumps({"eligible_counts": result["eligible_counts"], "retained": result["retained_per_group"]}, sort_keys=True))


if __name__ == "__main__":
    main()
