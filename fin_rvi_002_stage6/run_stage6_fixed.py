"""Technical adapter for Stage 6 evidence serialization.

The empirical run writes policy evidence under ``structured_policy``. The first
Stage 6 wrapper looked for the legacy Stage 1 key ``object_adjudication`` after
all empirical gates had already passed. This adapter adds the legacy alias and
exports the exact frozen policy-v3 inputs for the independent Node
implementation. It does not alter selection, policy, labels, metrics, seed, or
gate thresholds.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import run_stage6 as stage6


def _decision_rows(output: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (output / "holdout_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def _add_serialization_alias(output: Path) -> None:
    path = output / "holdout_decisions.jsonl"
    rows = _decision_rows(output)
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


def _export_exact_policy_inputs(output: Path) -> None:
    decisions = _decision_rows(output)
    by_id = {row["candidate_id"]: row for row in decisions}
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    compact_rows = report["payload"]["stage6"]["compact_rows"]
    for row in compact_rows:
        policy = by_id[row["candidate_id"]]["structured_policy"]
        row.update(
            {
                "policy_numeric_conflict": bool(policy["numeric_conflict"]),
                "policy_exact_numeric_support": bool(
                    policy["exact_numeric_support"]
                ),
                "policy_name_support": bool(policy["name_support"]),
                "policy_payment_language": bool(policy["payment_language"]),
                "policy_hard_category_conflict": bool(
                    policy.get("hard_category_conflict")
                ),
                "policy_shared_object_token_count": int(
                    policy["shared_object_token_count"]
                ),
                "policy_shared_classifications": list(
                    policy.get("shared_classifications", ())
                ),
                "policy_base_v2_decision": str(policy["base_v2_decision"]),
            }
        )
    report["payload"]["stage6"]["independence_contract"][
        "exact_policy_v3_inputs_exported"
    ] = True
    report["sha256"] = stage6.sha256_payload(report["payload"])
    stage6.base.write_json(report_path, report)
    (output / "stage6_compact_rows.jsonl").write_text(
        "\n".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False)
            for row in compact_rows
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "report.sha256").write_text(
        f"{stage6.base.sha256_file(report_path)}  report.json\n",
        encoding="utf-8",
    )


def main() -> None:
    original_rewrite = stage6.rewrite_stage6

    def rewrite_with_exact_policy_inputs(output: Path) -> None:
        _add_serialization_alias(output)
        original_rewrite(output)
        _export_exact_policy_inputs(output)

    stage6.rewrite_stage6 = rewrite_with_exact_policy_inputs
    stage6.main()


if __name__ == "__main__":
    main()
