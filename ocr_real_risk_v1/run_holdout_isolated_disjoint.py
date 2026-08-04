"""CLI for disjoint all-page OCR validation with isolated native-word crops."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import evaluate
from .core import canonical_json, parse_candidate_sources, sha256_bytes
from .disjoint_validation import load_seen_processes, select_disjoint_shard
from .evaluate import write_outputs
from .evaluate_dual_anchor import partition_process_disjoint_candidates
from .evaluate_full_native_index_isolated import (
    execute_full_native_index_isolated,
)
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .run_holdout import parse_partitions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--seen-processes", type=Path, required=True)
    parser.add_argument("--partitions", default="0-9")
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
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
    parser.add_argument("--max-documents", type=int, default=1000)
    parser.add_argument("--target-tokens", type=int, default=1000)
    args = parser.parse_args()

    partitions = parse_partitions(args.partitions)
    os.environ["OCR_HOLDOUT_SOURCE_FILES"] = os.pathsep.join(
        str(path) for path in args.source
    )
    os.environ["OCR_HOLDOUT_PARTITIONS"] = args.partitions

    all_candidates, census = parse_candidate_sources(
        args.source,
        partitions=None,
    )
    development_candidates, partition_census = (
        partition_process_disjoint_candidates(all_candidates, partitions)
    )
    seen_processes, seen_census = load_seen_processes(args.seen_processes)
    candidates, shard_census = select_disjoint_shard(
        development_candidates,
        seen_processes,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
    )
    if args.max_documents < len(candidates):
        raise RuntimeError(
            "max_documents is below the sealed shard population; refusing truncation"
        )
    if args.target_tokens < len(candidates):
        raise RuntimeError(
            "target_tokens is below the shard population; refusing outcome-dependent stop"
        )

    evaluate.clopper_pearson_lower = clopper_pearson_lower
    evaluate.clopper_pearson_upper = clopper_pearson_upper
    report, anchor_census = execute_full_native_index_isolated(
        candidates,
        args.output_dir,
        args.max_documents,
        args.target_tokens,
        args.stage,
        args.source,
    )
    report["protocol"]["process_partition"] = partition_census
    report["protocol"]["disjoint_validation"] = {
        **shard_census,
        "seen_process_manifest": seen_census,
        "outcome_dependent_stopping": False,
        "entire_selected_shard_attempted": True,
    }
    report["execution"]["process_partition"] = {
        "partitions": partition_census["partitions"],
        "population_unique_processes": partition_census["unique_processes"],
        "eligible_processes_in_partition": partition_census[
            "eligible_processes_in_partition"
        ],
        "selected_process_key_set_sha256": partition_census[
            "selected_process_key_set_sha256"
        ],
    }
    report["execution"]["disjoint_validation"] = {
        **shard_census,
        "seen_process_manifest_sha256": seen_census["manifest_sha256"],
        "documents_attempted_equals_shard_population": (
            report["execution"]["documents_attempted"]
            == shard_census["selected_processes"]
        ),
    }
    if report["execution"]["documents_attempted"] != shard_census[
        "selected_processes"
    ]:
        raise RuntimeError("not every process in the sealed shard was attempted")
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )

    combined_census = dict(census)
    combined_census["process_partition"] = partition_census
    combined_census["dual_source_anchor"] = anchor_census
    combined_census["disjoint_validation"] = {
        **shard_census,
        "seen_process_manifest": seen_census,
    }
    combined_census["crop_geometry"] = report["protocol"]["crop_geometry"]
    write_outputs(report, combined_census, args.output_dir)
    print(
        json.dumps(
            {
                "shard": shard_census,
                "execution": report["execution"],
                "baseline": report["baseline"],
                "verifier": report["verifier"],
                "counterfactual": report["counterfactual"],
                "decision": report["decision"],
                "stable_payload_sha256": report[
                    "stable_payload_sha256"
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
