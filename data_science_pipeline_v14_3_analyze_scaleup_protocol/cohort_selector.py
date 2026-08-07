from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any


class ProtocolError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProtocolError(f"NON_OBJECT_ROW:{line_number}")
        records.append(value)
    return records


def _exact_sha(value: Any, field: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ProtocolError(f"INVALID_SHA256:{field}")
    return text


def _method(value: Any, mapping: dict[str, str]) -> str | None:
    return mapping.get(str(value or "").strip().lower())


def _date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ProtocolError("INVALID_EVENT_DATE") from exc


def validate_candidate(row: dict[str, Any], protocol: dict[str, Any]) -> tuple[str | None, str]:
    contract = protocol["candidate_contract"]
    forbidden = set(protocol["discovery_blinding"]["forbidden_fields"])
    leaked = sorted(forbidden.intersection(row))
    if leaked:
        raise ProtocolError("FORBIDDEN_DISCOVERY_FIELDS:" + ",".join(leaked))
    missing = [field for field in contract["required_fields"] if field not in row]
    if missing:
        raise ProtocolError("MISSING_REQUIRED_FIELDS:" + ",".join(sorted(missing)))

    commitment = _exact_sha(row["event_commitment_sha256"], "event_commitment_sha256")
    _exact_sha(row["lineage_sha256"], "lineage_sha256")
    if str(row["event_role"]).upper() != contract["event_role"]:
        return None, commitment
    if str(row["amount_role"]).upper() != contract["amount_role"]:
        return None, commitment
    if str(row["date_role"]).upper() != contract["date_role"]:
        return None, commitment
    if str(row["currency"]).upper() != contract["allowed_currency"]:
        return None, commitment
    if str(row["resolution_state"]).upper() not in set(contract["allowed_resolution_states"]):
        return None, commitment
    if _date(row["event_date"]) > date.fromisoformat(contract["cutoff_date"]):
        return None, commitment
    return _method(row["procurement_method"], contract["method_mapping"]), commitment


def selection_key(seed: str, commitment: str) -> str:
    return hashlib.sha256(f"{seed}:{commitment}".encode()).hexdigest()


def select(records: list[dict[str, Any]], protocol: dict[str, Any]) -> dict[str, Any]:
    sampling = protocol["sampling"]
    groups = list(sampling["groups"])
    primary_n = int(sampling["primary_per_group"])
    reserve_n = int(sampling["reserve_per_group"])
    seed = sampling["seed"]
    by_group: dict[str, list[str]] = {group: [] for group in groups}
    seen: set[str] = set()
    excluded = 0

    for row in records:
        group, commitment = validate_candidate(row, protocol)
        if commitment in seen:
            raise ProtocolError("DUPLICATE_EVENT_COMMITMENT")
        seen.add(commitment)
        if group is None:
            excluded += 1
            continue
        by_group[group].append(commitment)

    selected: dict[str, dict[str, list[str]]] = {}
    insufficient: dict[str, int] = {}
    for group in groups:
        ordered = sorted(by_group[group], key=lambda item: (selection_key(seed, item), item))
        if len(ordered) < primary_n + reserve_n:
            insufficient[group] = len(ordered)
        selected[group] = {
            "primary": ordered[:primary_n],
            "reserve": ordered[primary_n:primary_n + reserve_n],
        }

    if insufficient:
        terminal = "COHORT_NOT_EVALUABLE_INSUFFICIENT_ELIGIBLE_EVENTS"
        selected = {group: {"primary": [], "reserve": []} for group in groups}
    else:
        terminal = "COHORT_FROZEN_BLIND"

    selected_count = sum(len(parts["primary"]) + len(parts["reserve"]) for parts in selected.values())
    if selected_count > int(protocol["governance"]["maximum_selected_events"]):
        raise ProtocolError("MAXIMUM_SELECTED_EVENTS_EXCEEDED")

    result = {
        "schema": "data-science-pipeline/analyze-scaleup-cohort-manifest/1",
        "coordination_id": protocol["coordination_id"],
        "protocol_sha256": sha256_value(protocol),
        "terminal_state": terminal,
        "input": {
            "candidate_rows": len(records),
            "unique_event_commitments": len(seen),
            "eligible_counts": {group: len(by_group[group]) for group in groups},
            "excluded_rows": excluded,
            "input_commitment_set_sha256": sha256_value(sorted(seen)),
        },
        "sampling": {
            "seed": seed,
            "selection_key": sampling["selection_key"],
            "primary_per_group": primary_n,
            "reserve_per_group": reserve_n,
            "selected": selected,
            "selected_event_count": selected_count,
        },
        "blinding": {
            "outcome_accessed": False,
            "bid_count_accessed": False,
            "low_competition_accessed": False,
            "raw_identity_exported": False,
        },
        "readiness": {
            "outcome_reveal_allowed": terminal == "COHORT_FROZEN_BLIND",
            "analysis_allowed": False,
            "stage10_unblocked": False,
        },
        "governance": protocol["governance"],
    }
    return result


def run(protocol_path: Path, input_path: Path, output_path: Path) -> dict[str, Any]:
    protocol = json.loads(protocol_path.read_text())
    records = load_jsonl(input_path)
    result = select(records, protocol)
    output_path.write_bytes(canonical_bytes(result))
    return result


def make_fixture(output_path: Path, per_group: int = 20) -> None:
    rows = []
    index = 0
    for method in ["direct", "open"]:
        for _ in range(per_group):
            commitment = hashlib.sha256(f"fixture-event-{index}".encode()).hexdigest()
            rows.append({
                "event_commitment_sha256": commitment,
                "procurement_method": method,
                "event_role": "CONTRACT",
                "amount_role": "CONTRACT_VALUE",
                "date_role": "CONTRACT_DATE",
                "currency": "HNL",
                "event_date": "2025-01-15",
                "resolution_state": "MATCH_OFFICIAL",
                "lineage_sha256": hashlib.sha256(f"fixture-lineage-{index}".encode()).hexdigest(),
            })
            index += 1
    output_path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--protocol", type=Path, required=True)
    freeze.add_argument("--input", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    fixture = sub.add_parser("make-fixture")
    fixture.add_argument("--output", type=Path, required=True)
    fixture.add_argument("--per-group", type=int, default=20)
    args = parser.parse_args()
    if args.command == "freeze":
        result = run(args.protocol, args.input, args.output)
        print(result["terminal_state"])
    else:
        make_fixture(args.output, args.per_group)


if __name__ == "__main__":
    main()
