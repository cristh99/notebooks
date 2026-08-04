"""CLI for the process-partitioned, dual-source OCR risk holdout."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import evaluate
from .core import canonical_json, parse_candidate_sources, sha256_bytes
from .evaluate import write_outputs
from .evaluate_dual_anchor import execute_dual_anchor
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .final_partition import process_key, process_partition
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

    # Parse the complete frozen population first. URL-level filtering here
    # would allow different PDFs from one procurement process to leak across
    # canary and final partitions. Every document from a process is therefore
    # filtered by the same process hash before born-digital document selection.
    all_candidates, census = parse_candidate_sources(
        args.source,
        partitions=None,
    )
    population_process_keys = {process_key(row) for row in all_candidates}
    candidates = [
        row
        for row in all_candidates
        if process_partition(row) in partitions
    ]
    selected_process_keys = {process_key(row) for row in candidates}
    partition_census = {
        "partition_unit": "procurement process",
        "partitions": sorted(partitions),
        "population_unique_processes": len(population_process_keys),
        "eligible_processes_in_partition": len(selected_process_keys),
        "candidate_documents_in_partition": len(candidates),
        "selected_process_key_set_sha256": sha256_bytes(
            canonical_json(sorted(selected_process_keys)).encode("utf-8")
        ),
        "partition_uses_ocr": False,
    }

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
    report["protocol"]["process_partition"] = partition_census
    report["execution"]["process_partition"] = partition_census
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )

    combined_census = dict(census)
    combined_census["process_partition"] = partition_census
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
