"""CLI for OCR Real Risk Holdout v1."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .core import parse_candidate_sources
from .evaluate import execute, write_outputs


def parse_partitions(value: str) -> frozenset[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part: continue
        if "-" in part:
            left, right = part.split("-", 1)
            result.update(range(int(left), int(right) + 1))
        else:
            result.add(int(part))
    if not result or min(result) < 0 or max(result) > 99:
        raise ValueError("partitions must be within 0..99")
    return frozenset(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--partitions", default="0-9")
    parser.add_argument("--stage", choices=("canary", "final"), default="canary")
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_real_risk_v1/run"))
    parser.add_argument("--max-documents", type=int, default=80)
    parser.add_argument("--target-tokens", type=int, default=60)
    args = parser.parse_args()
    partitions = parse_partitions(args.partitions)
    os.environ["OCR_HOLDOUT_SOURCE_FILES"] = os.pathsep.join(str(x) for x in args.source)
    os.environ["OCR_HOLDOUT_PARTITIONS"] = args.partitions
    candidates, census = parse_candidate_sources(args.source, partitions=partitions)
    report = execute(candidates, args.output_dir, args.max_documents, args.target_tokens, args.stage)
    write_outputs(report, census, args.output_dir)
    print(json.dumps({
        "census": census,
        "summary": {
            "execution": report["execution"], "baseline": report["baseline"],
            "verifier": report["verifier"], "decision": report["decision"],
            "stable_payload_sha256": report["stable_payload_sha256"],
        },
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
