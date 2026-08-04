"""CLI for the full-native-index dual-source OCR development canary."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import evaluate
from .core import canonical_json, parse_candidate_sources, sha256_bytes
from .evaluate import write_outputs
from .evaluate_dual_anchor import partition_process_disjoint_candidates
from .evaluate_full_native_index import execute_full_native_index
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
    parser.add_argument("--target-tokens", type=int, default=30)
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
    candidates, partition_census = partition_process_disjoint_candidates(
        all_candidates,
        partitions,
    )

    evaluate.clopper_pearson_lower = clopper_pearson_lower
    evaluate.clopper_pearson_upper = clopper_pearson_upper
    report, anchor_census = execute_full_native_index(
        candidates,
        args.output_dir,
        args.max_documents,
        args.target_tokens,
        args.stage,
        args.source,
    )
    report["protocol"]["process_partition"] = partition_census
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
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )

    combined_census = dict(census)
    combined_census["process_partition"] = partition_census
    combined_census["dual_source_anchor"] = anchor_census
    combined_census["native_index"] = {
        "schema": "ocr-real-risk-full-native-index/1",
        "all_native_pages_indexed_before_ocr": True,
        "only_selected_page_rendered": True,
    }
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
