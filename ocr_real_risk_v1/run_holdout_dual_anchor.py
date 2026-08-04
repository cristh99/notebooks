"""CLI for the process-disjoint, dual-source OCR risk holdout."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import evaluate
from .core import parse_candidate_sources
from .evaluate import write_outputs
from .evaluate_dual_anchor import execute_dual_anchor
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .run_holdout import parse_partitions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--partitions", default="0-9")
    parser.add_argument(
        "--stage",
        choices=("canary", "final"),
        default="canary",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_real_risk_v1/run"),
    )
    parser.add_argument("--max-documents", type=int, default=80)
    parser.add_argument("--target-tokens", type=int, default=60)
    args = parser.parse_args()

    partitions = parse_partitions(args.partitions)
    os.environ["OCR_HOLDOUT_SOURCE_FILES"] = os.pathsep.join(
        str(path) for path in args.source
    )
    os.environ["OCR_HOLDOUT_PARTITIONS"] = args.partitions
    candidates, census = parse_candidate_sources(
        args.source,
        partitions=partitions,
    )

    # Preserve the existing holdout implementation while replacing its
    # unstable numerical primitive before report construction.
    evaluate.clopper_pearson_lower = clopper_pearson_lower
    evaluate.clopper_pearson_upper = clopper_pearson_upper
    report, anchor_census = execute_dual_anchor(
        candidates,
        args.output_dir,
        args.max_documents,
        args.target_tokens,
        args.stage,
        args.source,
    )
    combined_census = dict(census)
    combined_census["dual_source_anchor"] = anchor_census
    write_outputs(report, combined_census, args.output_dir)
    print(
        json.dumps(
            {
                "census": combined_census,
                "summary": {
                    "execution": report["execution"],
                    "baseline": report["baseline"],
                    "verifier": report["verifier"],
                    "decision": report["decision"],
                    "stable_payload_sha256": report[
                        "stable_payload_sha256"
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
