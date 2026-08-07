"""CLI and stable public surface for the OpenVINO v7 full-gate pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .openvino_full_gate_aggregate_v7 import (
    aggregate_from_files,
    aggregate_partition_reports,
    exact_summary,
)
from .openvino_full_gate_contract_v7 import (
    ABSTAIN_DEDUP_OR_INTEGRITY,
    ACTIVE,
    BLOCKED_ENGINEERING,
    EXPECTED_PARTITION_COUNTS,
    PARTITION_COUNT,
    canonical_pixel_sha256,
    stable_payload,
    verify_execution_authorization,
    verify_manifest_bundle,
    write_hash_manifest,
)
from .openvino_full_gate_prepare_v7 import prepare_registry_from_source
from .openvino_full_gate_registry_v7 import (
    build_physical_registry,
    verify_registry_bundle,
    write_registry_bundle,
)
from .openvino_full_gate_runner_v7 import evaluate_partition_from_source

__all__ = [
    "ABSTAIN_DEDUP_OR_INTEGRITY",
    "ACTIVE",
    "BLOCKED_ENGINEERING",
    "EXPECTED_PARTITION_COUNTS",
    "PARTITION_COUNT",
    "aggregate_from_files",
    "aggregate_partition_reports",
    "build_physical_registry",
    "canonical_pixel_sha256",
    "evaluate_partition_from_source",
    "exact_summary",
    "prepare_registry_from_source",
    "stable_payload",
    "verify_execution_authorization",
    "verify_manifest_bundle",
    "verify_registry_bundle",
    "write_hash_manifest",
    "write_registry_bundle",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    verify_manifest = commands.add_parser("verify-manifest")
    verify_manifest.add_argument("--manifest-root", type=Path, required=True)

    prepare = commands.add_parser("prepare-registry")
    prepare.add_argument("--manifest-root", type=Path, required=True)
    prepare.add_argument("--prior-registry", type=Path, required=True)
    prepare.add_argument("--prior-registry-sha256", required=True)
    prepare.add_argument("--authorization", type=Path, required=True)
    prepare.add_argument("--authorization-sha256", required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--manifest-root", type=Path, required=True)
    evaluate.add_argument("--registry-root", type=Path, required=True)
    evaluate.add_argument("--partition", type=int, required=True)
    evaluate.add_argument("--model-zip", type=Path, required=True)
    evaluate.add_argument("--authorization", type=Path, required=True)
    evaluate.add_argument("--authorization-sha256", required=True)
    evaluate.add_argument("--output-dir", type=Path, required=True)

    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--registry-root", type=Path, required=True)
    aggregate.add_argument("report_roots", nargs="+", type=Path)
    aggregate.add_argument("--authorization", type=Path, required=True)
    aggregate.add_argument("--authorization-sha256", required=True)
    aggregate.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "verify-manifest":
        result = verify_manifest_bundle(args.manifest_root)
    elif args.command == "prepare-registry":
        result = prepare_registry_from_source(
            manifest_root=args.manifest_root,
            prior_registry_path=args.prior_registry,
            prior_registry_sha256=args.prior_registry_sha256,
            authorization_path=args.authorization,
            authorization_sha256=args.authorization_sha256,
            output_dir=args.output_dir,
        )
    elif args.command == "evaluate":
        result = evaluate_partition_from_source(
            manifest_root=args.manifest_root,
            registry_root=args.registry_root,
            partition=args.partition,
            model_zip=args.model_zip,
            authorization_path=args.authorization,
            authorization_sha256=args.authorization_sha256,
            output_dir=args.output_dir,
        )
    else:
        result = aggregate_from_files(
            registry_root=args.registry_root,
            report_roots=args.report_roots,
            authorization_path=args.authorization,
            authorization_sha256=args.authorization_sha256,
            output_dir=args.output_dir,
        )
    printable = dict(result)
    printable.pop("records", None)
    printable.pop("physical_groups", None)
    printable.pop("observations", None)
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    if result.get("status") in {
        ABSTAIN_DEDUP_OR_INTEGRITY,
        BLOCKED_ENGINEERING,
    }:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
