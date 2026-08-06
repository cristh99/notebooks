from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

from .engine import digest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


class VerificationError(ValueError):
    pass


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def verify(root: Path = ROOT) -> dict:
    reports = root / "reports"
    contract = _read(root / "contract.json")
    rows = _read(reports / "rows.json")
    summary = _read(reports / "summary.json")
    receipt = _read(reports / "receipt.json")

    _require(receipt.get("schema") == "byzantine-open-world-power-v1/public-receipt/1", "receipt schema")
    _require(digest(receipt["payload"]) == receipt["sha256"], "receipt self-hash")
    _require(len(rows) == contract["scenario_count"] == 72, "row count")
    _require(summary["status"] == "PASS", "summary status")
    _require(summary["scenario_count"] == 72 and summary["pass_count"] == 72, "summary counts")
    _require(all(row.get("pass") is True for row in rows), "row pass")
    _require(digest(rows) == receipt["payload"]["rows_sha256"], "rows hash")
    _require(digest(summary) == receipt["payload"]["summary_sha256"], "summary hash")
    _require(_file_sha(root / "contract.json") == receipt["payload"]["contract_sha256"], "contract hash")

    for relative, expected in receipt["payload"]["source_sha256"].items():
        _require(_file_sha(root / relative) == expected, f"source hash: {relative}")

    expected_ids = {f"{domain}::{archetype}" for domain in contract["domains"] for archetype in contract["archetypes"]}
    actual_ids = {row["scenario_id"] for row in rows}
    _require(len(actual_ids) == len(rows), "duplicate scenario")
    _require(actual_ids == expected_ids, "scenario matrix completeness")

    counts = dict(sorted(Counter(row["terminal"] for row in rows).items()))
    _require(counts == contract["expected_terminal_counts"], "row terminal counts")
    _require(summary["terminal_counts"] == counts, "summary terminal counts")
    _require(receipt["payload"]["expected_terminal_counts"] == counts, "receipt terminal counts")

    for row in rows:
        expected_terminal = contract["expected_terminal"][row["archetype"]]
        _require(row["terminal"] == expected_terminal, f"terminal: {row['scenario_id']}")
        _require(row["decision"]["terminal"] == row["terminal"], f"decision terminal: {row['scenario_id']}")
        decision_payload = {key: value for key, value in row["decision"].items() if key != "sha256"}
        _require(digest(decision_payload) == row["decision"]["sha256"], f"decision hash: {row['scenario_id']}")

    result = {"status": "PASS", "receipt_sha256": receipt["sha256"], "scenarios": len(rows)}
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    try:
        verify()
    except (KeyError, TypeError, VerificationError, json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"REJECTED: {exc}") from exc
