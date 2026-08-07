from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


UPSTREAM_COMMIT = "8aef2f48befdab5c57cc383a521711fe11c2df98"
MIN_ADAPTED_STATEMENTS_TO_EXECUTE = 10


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_statement(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        isinstance(value, dict)
        and isinstance(value.get("income_statement"), dict)
        and isinstance(value.get("balance_sheet", {}).get("current_year"), dict)
        and isinstance(value.get("cash_flow_statement"), dict)
        and bool(value.get("company"))
    )


def build(adapted_dir: Path, output_dir: Path, upstream_src: Path) -> dict[str, Any]:
    sys.path.insert(0, str(upstream_src))
    from benchmark.dataset_builder import build_benchmark_dataset  # type: ignore

    source_files = [path for path in sorted(adapted_dir.glob("*.json")) if is_statement(path)]
    if len(source_files) < MIN_ADAPTED_STATEMENTS_TO_EXECUTE:
        raise ValueError(f"too few adapted statements to execute: {len(source_files)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fin-abs-001a-") as temp:
        staging = Path(temp)
        for path in source_files:
            shutil.copy2(path, staging / path.name)
        instances, stats = build_benchmark_dataset(
            processed_dir=staging,
            output_dir=output_dir,
            seed=42,
            write_individual_files=False,
        )

    benchmark_path = output_dir / "benchmark.json"
    stats_path = output_dir / "benchmark_stats.json"
    manifest = {
        "schema": "fin-abs-001a/benchmark-build/2",
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_src": str(upstream_src),
        "minimum_adapted_statements_to_execute": MIN_ADAPTED_STATEMENTS_TO_EXECUTE,
        "adapted_statement_count": len(source_files),
        "breadth_target": 40,
        "breadth_gate_met": len(source_files) >= 40,
        "adapted_statement_files": [path.name for path in source_files],
        "benchmark_instances": len(instances),
        "clean_instances": stats.clean_instances,
        "error_instances": stats.error_instances,
        "benchmark_sha256": sha256_file(benchmark_path),
        "stats_sha256": sha256_file(stats_path),
        "seed": 42,
        "boundary": (
            "Execution is allowed with at least ten transparent company slices so diagnostic behavior can be measured. "
            "The separate breadth gate remains forty and must fail honestly when fewer companies are comparable. "
            "The benchmark uses the pinned FinVerBench error taxonomy and builders on a transparent adapter from the committed SEC-XBRL line-item corpus and is not byte-identical to the published diagnostic subset."
        ),
    }
    (output_dir / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("adapted_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("upstream_src", type=Path)
    args = parser.parse_args()
    manifest = build(args.adapted_dir, args.output_dir, args.upstream_src)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
