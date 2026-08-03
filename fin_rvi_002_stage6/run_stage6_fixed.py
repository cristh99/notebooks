"""Technical adapter for Stage 6 evidence serialization.

The empirical run writes policy evidence under ``structured_policy``. The first
Stage 6 wrapper looked for the legacy Stage 1 key ``object_adjudication`` after
all empirical gates had already passed. This adapter adds the legacy alias only
for serialization, then delegates to the frozen Stage 6 implementation. It does
not alter selection, policy, labels, metrics, seed, or gate thresholds.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import run_stage6 as stage6


def _add_serialization_alias(output: Path) -> None:
    path = output / "holdout_decisions.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    changed = False
    for row in rows:
        if "object_adjudication" not in row and "structured_policy" in row:
            row["object_adjudication"] = row["structured_policy"]
            changed = True
    if changed:
        path.write_text(
            "\n".join(
                json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows
            )
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    original_rewrite = stage6.rewrite_stage6

    def rewrite_with_alias(output: Path) -> None:
        _add_serialization_alias(output)
        original_rewrite(output)

    stage6.rewrite_stage6 = rewrite_with_alias
    stage6.main()


if __name__ == "__main__":
    main()
