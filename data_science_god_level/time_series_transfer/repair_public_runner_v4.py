from __future__ import annotations

import hashlib
import json
from pathlib import Path

SOURCE_SHA256 = "a63cf1accd745268e27b53eee511e8043a8f666f57e2d3ee2382dbe7a528f8fe"
TARGET_SHA256 = "d3532e15300f75f22e8c28b2c4da62da4afcada9d4d12bbbc2b8e9c9b8dd8fc7"
REPAIRS = {
    "hashlib.shaa256": "hashlib.sha256",
    "**{ey: value for key": "**{key: value for key",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path("data_science_god_level/time_series_transfer")
    path = root / "public_runner_v4.py"
    if digest(path) != SOURCE_SHA256:
        raise SystemExit("unexpected transported runner hash")
    text = path.read_text(encoding="utf-8")
    for old, new in REPAIRS.items():
        if text.count(old) != 1:
            raise SystemExit(f"runner repair anchor is not unique: {old}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    if digest(path) != TARGET_SHA256:
        raise SystemExit("repaired runner hash mismatch")
    receipt = {
        "schema": "data-science-god-level/time-series-runner-transport-repair/1",
        "source_sha256": SOURCE_SHA256,
        "target_sha256": TARGET_SHA256,
        "repairs": REPAIRS,
        "candidate_or_gate_semantics_changed": False,
        "official_suite_accessed": False,
    }
    (root / "runner-transport-repair-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
