from __future__ import annotations

import hashlib
from pathlib import Path

BASE_SHA256 = "4893bfa4a24d1385d2f71b4e22676124c533f98a6e24d3bbc45b3d2c30f75412"
TARGET_SHA256 = "c69b3021578c4ca478716415abd4bbb7c98e08896ac5e5d433de6ac445abdda2"
REPLACEMENTS = {
    'CANDIDATE_SHA = "76d240d4f4bb1ed5a87f32c18ae92e7629b971f761577eb16d2b5deccf57ef8f"':
        'CANDIDATE_SHA = "b963b2579756dbe6900da06c2c49de6c81d80354af83073e6572226e25811621"',
    "SYNTHETIC_RUN_ID = 31011091786": "SYNTHETIC_RUN_ID = 31023289206",
    "QUERY_NUMBERS = (5, 6, 7)": "QUERY_NUMBERS = (8, 9, 10)",
    "fresh-usaspending-official-data/2": "fresh-usaspending-official-data/3",
    "fresh-usaspending-sealed-answers/2": "fresh-usaspending-sealed-answers/3",
    "fresh-usaspending-official-validation/2": "fresh-usaspending-official-validation/3",
    "fresh-usaspending-external-receipt/2": "fresh-usaspending-external-receipt/3",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(base_path: Path, output_path: Path) -> None:
    if digest(base_path) != BASE_SHA256:
        raise SystemExit("unexpected V2 official harness")
    text = base_path.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS.items():
        if text.count(old) != 1:
            raise SystemExit(f"non-unique harness replacement anchor: {old}")
        text = text.replace(old, new)
    output_path.write_text(text, encoding="utf-8")
    if digest(output_path) != TARGET_SHA256:
        raise SystemExit("V3 official harness hash mismatch")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    build(root / "official_harness_v2_base.py", root / "official_harness_v3.py")
