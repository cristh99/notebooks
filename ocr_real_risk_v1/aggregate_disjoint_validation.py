"""Aggregate every sealed shard of process-disjoint OCR validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable

from .core import Candidate, canonical_json, p95, sha256_bytes
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .final_partition import process_key

SCHEMA = "ocr-real-risk-isolated-disjoint-aggregate/1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hash_manifest(root: Path) -> None:
    path = root / "SHA256SUMS.txt"
    if not path.exists():
        raise RuntimeError(f"missing SHA256SUMS.txt in {root}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        expected, relative = raw.split("  ", 1)
        target = root / relative
        if _sha256(target) != expected:
            raise RuntimeError(f"hash mismatch: {target}")


def _stable_payload_hash(report: dict[str, Any]) -> str:
    payload = dict(report)
    expected = str(payload.pop("stable_payload_sha256"))
    observed = sha256_bytes(canonical_json(payload).encode("utf-8"))
    if observed != expected:
        raise RuntimeError("shard stable payload hash mismatch")
    return expected


def aggregate(roots: Iterable[Path], output_dir: Path) -> dict[str, Any]:
    reports: list[tuple[Path, dict[str, Any]]] = []
    for root in sorted(roots):
        _verify_hash_manifest(root)
        report_path = root / "reports/real_numeric_risk_holdout.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        _stable_payload_hash(report)
        reports.append((root, report))
    if not reports:
        raise RuntimeError("no shard reports supplied")

    shards: dict[int, dict[str, Any]] = {}
    all_documents: list[dict[str, Any]] = []
    all_observations: list[dict[str, Any]] = []
    seen_manifest_hashes: set[str] = set()
    for root, report in reports:
        protocol = report["protocol"]["disjoint_validation"]
        shard_index = int(protocol["shard_index"])
        shard_count = int(protocol["shard_count"])
        if shard_index in shards:
            raise RuntimeError(f"duplicate shard index: {shard_index}")
        if report["source"]["stage"] != "canary":
            raise RuntimeError("aggregate accepts development canaries only")
        if report["decision"]["pass_statistical_10x"] is not False:
            raise RuntimeError("development shard claimed a production certificate")
        if report["protocol"]["crop_geometry"]["schema"] != (
            "ocr-real-risk-isolated-native-word-crop/1"
        ):
            raise RuntimeError("unexpected crop geometry")
        if report["execution"]["documents_attempted"] != protocol[
            "selected_processes"
        ]:
            raise RuntimeError("shard did not attempt its entire sealed population")
        seen_manifest_hashes.add(
            str(protocol["seen_process_manifest"]["manifest_sha256"])
        )
        shards[shard_index] = {
            "root": str(root),
            "shard_count": shard_count,
            "selected_processes": int(protocol["selected_processes"]),
            "documents_attempted": int(report["execution"]["documents_attempted"]),
            "documents_with_tokens": int(report["execution"]["documents_with_tokens"]),
            "stable_payload_sha256": report["stable_payload_sha256"],
            "report_sha256": _sha256(
                root / "reports/real_numeric_risk_holdout.json"
            ),
        }
        all_documents.extend(report["documents"])
        all_observations.extend(report["observations"])

    declared_counts = {row["shard_count"] for row in shards.values()}
    if len(declared_counts) != 1:
        raise RuntimeError("shards disagree on shard_count")
    shard_count = declared_counts.pop()
    if set(shards) != set(range(shard_count)):
        raise RuntimeError("aggregate is missing one or more shards")
    if len(seen_manifest_hashes) != 1:
        raise RuntimeError("shards used different seen-process manifests")

    candidates = [Candidate(**row["candidate"]) for row in all_documents]
    process_keys = [process_key(candidate) for candidate in candidates]
    if len(process_keys) != len(set(process_keys)):
        raise RuntimeError("process overlap across validation shards")
    expected_population = sum(row["selected_processes"] for row in shards.values())
    if len(all_documents) != expected_population:
        raise RuntimeError("aggregate document count differs from sealed population")

    locations = {
        (
            str(row["source_sha256"]),
            int(row["page_number"]),
            tuple(float(value) for value in row["bbox_pt"]),
        )
        for row in all_observations
    }
    if len(locations) != len(all_observations):
        raise RuntimeError("location identity overlap across shards")

    baseline = [row for row in all_observations if row["tesseract_claim"]]
    baseline_false = sum(not row["claim_correct"] for row in baseline)
    accepted = [row for row in all_observations if row["accepted"]]
    accepted_false = sum(row["false_accepted"] for row in accepted)
    counterfactual_false = sum(
        row["counterfactual_false_accept"] for row in all_observations
    )
    baseline_lower = clopper_pearson_lower(baseline_false, len(baseline))
    accepted_upper = clopper_pearson_upper(accepted_false, len(accepted))
    reduction_lower = (
        baseline_lower / accepted_upper if accepted_upper > 0 else None
    )
    yield_rate = len(all_observations) / len(all_documents) if all_documents else 0.0
    verifier_times = [
        float(row["verifier_runtime_ms"])
        for row in all_observations
        if float(row["verifier_runtime_ms"]) > 0
    ]
    tesseract_times = [
        float(row["tesseract_runtime_ms"]) for row in all_observations
    ]
    document_frontier = {
        str(locations_required): (
            math.ceil(locations_required / yield_rate) if yield_rate else None
        )
        for locations_required in (583, 760, 1090, 2200, 3840)
    }

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "inputs": {
            "shard_count": shard_count,
            "seen_process_manifest_sha256": next(iter(seen_manifest_hashes)),
            "processes": len(all_documents),
            "process_key_set_sha256": sha256_bytes(
                canonical_json(sorted(process_keys)).encode("utf-8")
            ),
            "shards": {str(key): value for key, value in sorted(shards.items())},
        },
        "execution": {
            "documents_attempted": len(all_documents),
            "documents_with_locations": len(all_observations),
            "yield_per_attempted_document": yield_rate,
            "institutions_with_locations": len(
                {row["institution_code"] for row in all_observations}
            ),
            "locations": len(all_observations),
            "document_frontier_at_observed_yield": document_frontier,
        },
        "baseline": {
            "predictions": len(baseline),
            "false_predictions": baseline_false,
            "observed_error_rate": (
                baseline_false / len(baseline) if baseline else None
            ),
            "simultaneous_95pct_lower": baseline_lower,
        },
        "verifier": {
            "accepted": len(accepted),
            "false_accepted": accepted_false,
            "accepted_coverage_of_locations": (
                len(accepted) / len(all_observations) if all_observations else 0.0
            ),
            "observed_false_acceptance_rate": (
                accepted_false / len(accepted) if accepted else None
            ),
            "simultaneous_95pct_upper": accepted_upper,
            "certified_error_reduction_lower": reduction_lower,
            "median_runtime_ms": (
                statistics.median(verifier_times) if verifier_times else None
            ),
            "p95_runtime_ms": p95(verifier_times),
        },
        "counterfactual": {
            "cases": len(all_observations),
            "false_accepts": counterfactual_false,
            "rejection_or_abstention_rate": (
                1 - counterfactual_false / len(all_observations)
                if all_observations
                else None
            ),
        },
        "timing": {
            "median_tesseract_crop_ms": (
                statistics.median(tesseract_times) if tesseract_times else None
            ),
            "p95_tesseract_crop_ms": p95(tesseract_times),
        },
        "decision": {
            "development_validation_complete": True,
            "pass_statistical_10x": False,
            "automatic_production_change": False,
            "verdict": "DISJOINT_DEVELOPMENT_COMPLETE_NO_FINAL_CERTIFICATE",
        },
        "constraints": {
            "final_partitions_10_99_opened": False,
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    result["stable_payload_sha256"] = sha256_bytes(
        canonical_json(result).encode("utf-8")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "isolated_disjoint_aggregate.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        f"{_sha256(output_path)}  {output_path.name}\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = aggregate(args.roots, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
