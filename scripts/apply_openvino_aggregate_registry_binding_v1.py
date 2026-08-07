from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "ocr_real_risk_v1/openvino_full_gate_aggregate_v7.py"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match, found {count}: {old[:80]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    _read_json,\n",
        "    _read_json,\n    _read_jsonl,\n",
    )
    insert = '''\n\ndef _registry_observation_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row.get("row_index", -1)),
        str(row.get("image_id") or ""),
        int(row.get("partition_id", row.get("partition", -1))),
        str(row.get("selection_rank_sha256") or ""),
        str(row.get("encoded_sha256") or ""),
        str(row.get("pixel_sha256") or ""),
    )
\n\ndef _verify_partition_registry_rows(
    partition: int,
    observations: Sequence[Mapping[str, Any]],
    expected_rows: Sequence[Mapping[str, Any]],
) -> None:
    if any(int(row.get("partition_id", -1)) != partition for row in observations):
        raise RuntimeError("partition report contains rows assigned to another partition")
    observed = [_registry_observation_identity(row) for row in observations]
    expected = [_registry_observation_identity(row) for row in expected_rows]
    if observed != expected:
        raise RuntimeError("partition observations differ from active registry identities")
\n\n'''
    text = replace_once(
        text,
        "\ndef aggregate_partition_reports(\n",
        insert + "def aggregate_partition_reports(\n",
    )
    text = replace_once(
        text,
        "    expected_preexecution: Mapping[str, Any] | None = None,\n"
        "    minimum_active: int = MINIMUM_ACTIVE_AFTER_DEDUP,\n",
        "    expected_preexecution: Mapping[str, Any] | None = None,\n"
        "    expected_registry_rows: Mapping[\n"
        "        int, Sequence[Mapping[str, Any]]\n"
        "    ] | None = None,\n"
        "    minimum_active: int = MINIMUM_ACTIVE_AFTER_DEDUP,\n",
    )
    text = replace_once(
        text,
        "        if len(rows) != int(expected_partition_counts[partition]):\n"
        "            raise RuntimeError(\"partition report differs from registry denominator\")\n"
        "        by_partition[partition] = report\n",
        "        if len(rows) != int(expected_partition_counts[partition]):\n"
        "            raise RuntimeError(\"partition report differs from registry denominator\")\n"
        "        if expected_registry_rows is not None:\n"
        "            expected_rows = expected_registry_rows.get(partition)\n"
        "            if expected_rows is None:\n"
        "                raise RuntimeError(\"active registry partition is missing\")\n"
        "            _verify_partition_registry_rows(partition, rows, expected_rows)\n"
        "        elif any(\n"
        "            int(row.get(\"partition_id\", -1)) != partition for row in rows\n"
        "        ):\n"
        "            raise RuntimeError(\n"
        "                \"partition report contains rows assigned to another partition\"\n"
        "            )\n"
        "        by_partition[partition] = report\n",
    )
    text = replace_once(
        text,
        "                \"retuning_authorized\": False,\n"
        "                \"automatic_production_change\": False,\n",
        "                \"retuning_authorized\": False,\n"
        "                \"post_outcome_retry_authorized\": False,\n"
        "                \"automatic_production_change\": False,\n",
    )
    text = replace_once(
        text,
        "    reports: list[dict[str, Any]] = []\n",
        "    expected_registry_rows = {\n"
        "        partition: _read_jsonl(\n"
        "            Path(registry_root) / f\"active_partition_{partition:02d}.jsonl\"\n"
        "        )\n"
        "        for partition in range(PARTITION_COUNT)\n"
        "    }\n"
        "    reports: list[dict[str, Any]] = []\n",
    )
    text = replace_once(
        text,
        "        expected_preexecution=preexecution,\n"
        "    )\n",
        "        expected_preexecution=preexecution,\n"
        "        expected_registry_rows=expected_registry_rows,\n"
        "    )\n",
    )
    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
