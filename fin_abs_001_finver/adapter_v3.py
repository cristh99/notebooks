from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from . import adapter as base


SCHEMA = "fin-abs-001a/finver-adapter/3"


def value_by_year_fallback(
    statement: Mapping[str, Any],
    section: str,
    key: str,
    fiscal_year: str,
) -> float | None:
    """Use the first mapped XBRL concept that has a value for the requested year.

    The upstream SEC map often stores one economic field under several XBRL
    concepts over time. The v2 adapter stopped at the first concept that existed
    anywhere in the file, even if that concept had no observation for the selected
    year. This function resolves the concept *per fiscal year* and never combines
    multiple concepts for one value.
    """
    items = statement.get(section, {}).get("line_items", {})
    if not isinstance(items, Mapping):
        return None
    for label in base.LABELS[key]:
        item = items.get(label)
        if not isinstance(item, Mapping):
            continue
        periods = item.get("periods")
        if not isinstance(periods, Mapping):
            continue
        node = periods.get(fiscal_year)
        if not isinstance(node, Mapping):
            continue
        value = node.get("value")
        if base._is_number(value):
            return float(value)
    return None


def install() -> None:
    base._value = value_by_year_fallback


def adapt_directory(processed_dir: Path, output_dir: Path) -> dict[str, Any]:
    install()
    manifest = base.adapt_directory(processed_dir, output_dir)
    manifest["schema"] = SCHEMA
    manifest["concept_resolution"] = (
        "mapped XBRL concepts are tried in declared order for each fiscal year; "
        "one numeric concept is selected and concepts are never summed"
    )
    manifest["boundary"] = (
        str(manifest["boundary"])
        + " Concept fallback only repairs temporal XBRL taxonomy drift; it does not infer a missing economic quantity."
    )
    (output_dir / "adapter_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("processed_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    install()
    audit = base.audit_upstream_schema(args.processed_dir)
    if args.audit_output:
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(
            json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    manifest = adapt_directory(args.processed_dir, args.output_dir)
    print(
        json.dumps(
            {
                "audit": audit["pipeline_status"],
                "adapted": manifest["adapted"],
                "excluded": manifest["excluded"],
                "schema": manifest["schema"],
            },
            sort_keys=True,
        )
    )
    return 0 if manifest["adapted"] >= 10 else 2


if __name__ == "__main__":
    raise SystemExit(main())
