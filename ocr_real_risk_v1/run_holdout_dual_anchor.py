"""CLI for the process-partitioned, dual-source OCR risk holdout."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from . import evaluate
from .core import canonical_json, parse_candidate_sources, sha256_bytes
from .evaluate import write_outputs
from .evaluate_dual_anchor import (
    VECTOR_TRUTH_DOCUMENT_PRIORITY,
    VECTOR_TRUTH_DOCUMENT_TYPES,
    execute_dual_anchor,
)
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .final_partition import process_key, process_partition
from .run_holdout import parse_partitions


def select_one_document_per_process_before_partition(candidates):
    """Choose one born-digital document per canonical process without OCR."""
    grouped = defaultdict(list)
    excluded = 0
    for row in candidates:
        if row.document_type not in VECTOR_TRUTH_DOCUMENT_TYPES:
            excluded += 1
            continue
        grouped[process_key(row)].append(row)
    selected = []
    for key in sorted(grouped):
        rows = grouped[key]
        selected.append(
            min(
                rows,
                key=lambda row: (
                    VECTOR_TRUTH_DOCUMENT_PRIORITY[row.document_type],
                    row.key,
                    row.url,
                ),
            )
        )
    return selected, {
        "input_candidates": len(candidates),
        "excluded_out_of_vector_truth_scope": excluded,
        "eligible_document_references": len(candidates) - excluded,
        "unique_processes": len(grouped),
        "selected_process_disjoint_documents": len(selected),
        "allowed_document_types": sorted(VECTOR_TRUTH_DOCUMENT_TYPES),
        "document_type_priority": VECTOR_TRUTH_DOCUMENT_PRIORITY,
        "process_identity": "SHA-256 of OCID, falling back to process then URL",
        "selection_uses_ocr": False,
    }


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

    # Parse the complete frozen population. Select one document by declared
    # metadata for each canonical process and only then assign the entire
    # process to a partition. No URL-level split can leak sibling documents.
    all_candidates, census = parse_candidate_sources(
        args.source,
        partitions=None,
    )
    process_candidates, document_scope = (
        select_one_document_per_process_before_partition(all_candidates)
    )
    candidates = [
        row
        for row in process_candidates
        if process_partition(row) in partitions
    ]
    selected_process_keys = {process_key(row) for row in candidates}
    if len(selected_process_keys) != len(candidates):
        raise AssertionError("duplicate canonical process after document selection")
    partition_census = {
        **document_scope,
        "partition_unit": "procurement process",
        "partitions": sorted(partitions),
        "eligible_processes_in_partition": len(candidates),
        "selected_process_key_set_sha256": sha256_bytes(
            canonical_json(sorted(selected_process_keys)).encode("utf-8")
        ),
        "partition_uses_ocr": False,
    }

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
