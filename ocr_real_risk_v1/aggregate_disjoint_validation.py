"""Aggregate every sealed shard of process-disjoint OCR validation.

Process-disjoint sampling does not guarantee evidence-disjoint sampling: two
procurement processes can publish byte-identical PDFs at different URLs. Yield
therefore remains process-associated, while OCR risk is computed on unique
physical evidence locations only. Any conflicting truth or outcome attached to
the same physical location fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import Candidate, canonical_json, p95, sha256_bytes
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .final_partition import process_key

SCHEMA = "ocr-real-risk-isolated-disjoint-aggregate/2"
EVIDENCE_REUSE_SCHEMA = "ocr-real-risk-physical-evidence-reuse/1"


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


def physical_location_identity(
    observation: Mapping[str, Any],
) -> tuple[str, int, tuple[float, ...]]:
    """Return the process-independent identity of one measured pixel location."""
    bbox = tuple(round(float(value), 4) for value in observation["bbox_pt"])
    if len(bbox) != 4:
        raise ValueError("bbox_pt must contain four coordinates")
    return (
        str(observation["source_sha256"]),
        int(observation["page_number"]),
        bbox,
    )


def _physical_evidence_key(
    identity: tuple[str, int, tuple[float, ...]],
) -> str:
    source_sha256, page_number, bbox_pt = identity
    return sha256_bytes(
        canonical_json(
            {
                "source_sha256": source_sha256,
                "page_number": page_number,
                "bbox_pt": list(bbox_pt),
            }
        ).encode("utf-8")
    )


def deduplicate_physical_evidence(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return one deterministic row per physical location plus reuse evidence."""
    groups: dict[
        tuple[str, int, tuple[float, ...]],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for observation in observations:
        row = dict(observation)
        process_key_value = str(row.get("_process_key") or "")
        if len(process_key_value) != 64:
            raise RuntimeError("annotated observation lacks a process key")
        groups[physical_location_identity(row)].append(row)

    outcome_fields = (
        "truth",
        "bbox_px",
        "crop_id",
        "crop_sha256",
        "selection_rank_sha256",
        "native_index_selection_rank_sha256",
        "tesseract_claim",
        "claim_correct",
        "verifier_status",
        "verifier_prediction",
        "accepted",
        "false_accepted",
        "counterfactual_claim",
        "counterfactual_status",
        "counterfactual_prediction",
        "counterfactual_false_accept",
    )
    unique: list[dict[str, Any]] = []
    reused_groups: list[dict[str, Any]] = []
    multiplicities: Counter[int] = Counter()
    for identity in sorted(groups):
        rows = sorted(
            groups[identity],
            key=lambda row: (
                str(row["_process_key"]),
                int(row["_shard_index"]),
                str(row["document_id"]),
            ),
        )
        representative = rows[0]
        for other in rows[1:]:
            conflicts = [
                field
                for field in outcome_fields
                if other.get(field) != representative.get(field)
            ]
            if conflicts:
                raise RuntimeError(
                    "conflicting truth or OCR outcome for reused physical "
                    f"evidence {_physical_evidence_key(identity)}: {conflicts}"
                )
        unique.append(representative)
        multiplicities[len(rows)] += 1
        if len(rows) > 1:
            source_sha256, page_number, bbox_pt = identity
            reused_groups.append(
                {
                    "evidence_key": _physical_evidence_key(identity),
                    "source_sha256": source_sha256,
                    "page_number": page_number,
                    "bbox_pt": list(bbox_pt),
                    "truth": representative["truth"],
                    "crop_sha256": representative["crop_sha256"],
                    "associated_process_count": len(rows),
                    "associated_process_keys": [
                        str(row["_process_key"]) for row in rows
                    ],
                    "associated_document_ids": [
                        str(row["document_id"]) for row in rows
                    ],
                    "associated_url_sha256": [
                        str(row["url_sha256"]) for row in rows
                    ],
                    "associated_shards": [
                        int(row["_shard_index"]) for row in rows
                    ],
                    "outcomes_identical": True,
                }
            )

    reuse = {
        "schema": EVIDENCE_REUSE_SCHEMA,
        "process_associated_locations": len(observations),
        "unique_physical_locations": len(unique),
        "duplicate_process_associations": len(observations) - len(unique),
        "reused_physical_location_groups": len(reused_groups),
        "maximum_processes_per_physical_location": max(
            multiplicities, default=0
        ),
        "physical_location_multiplicity": {
            str(key): value for key, value in sorted(multiplicities.items())
        },
        "risk_denominator": "unique physical evidence locations",
        "yield_denominator": "attempted procurement processes",
        "groups": reused_groups,
    }
    return unique, reuse


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
            "process_associated_locations": int(
                report["execution"]["documents_with_tokens"]
            ),
            "stable_payload_sha256": report["stable_payload_sha256"],
            "report_sha256": _sha256(
                root / "reports/real_numeric_risk_holdout.json"
            ),
        }
        local_documents: dict[str, tuple[str, Candidate]] = {}
        for document in report["documents"]:
            candidate = Candidate(**document["candidate"])
            key = process_key(candidate)
            document_id = str(document["document_id"])
            if document_id in local_documents:
                raise RuntimeError("duplicate document_id within one shard")
            local_documents[document_id] = (key, candidate)
            annotated_document = dict(document)
            annotated_document["_process_key"] = key
            annotated_document["_shard_index"] = shard_index
            all_documents.append(annotated_document)
        for observation in report["observations"]:
            document_id = str(observation["document_id"])
            if document_id not in local_documents:
                raise RuntimeError("observation has no bound shard document")
            key, candidate = local_documents[document_id]
            annotated = dict(observation)
            annotated["_process_key"] = key
            annotated["_process"] = candidate.process
            annotated["_ocid"] = candidate.ocid
            annotated["_shard_index"] = shard_index
            all_observations.append(annotated)

    declared_counts = {row["shard_count"] for row in shards.values()}
    if len(declared_counts) != 1:
        raise RuntimeError("shards disagree on shard_count")
    shard_count = declared_counts.pop()
    if set(shards) != set(range(shard_count)):
        raise RuntimeError("aggregate is missing one or more shards")
    if len(seen_manifest_hashes) != 1:
        raise RuntimeError("shards used different seen-process manifests")

    process_keys = [str(row["_process_key"]) for row in all_documents]
    if len(process_keys) != len(set(process_keys)):
        raise RuntimeError("process overlap across validation shards")
    expected_population = sum(row["selected_processes"] for row in shards.values())
    if len(all_documents) != expected_population:
        raise RuntimeError("aggregate document count differs from sealed population")

    unique_observations, evidence_reuse = deduplicate_physical_evidence(
        all_observations
    )
    acquired = [
        row
        for row in all_documents
        if row.get("acquisition", {}).get("status") == "ACQUIRED"
    ]
    acquired_source_counts = Counter(
        str(row["acquisition"]["sha256"]) for row in acquired
    )
    reused_source_groups = sum(
        count > 1 for count in acquired_source_counts.values()
    )
    duplicate_source_associations = sum(
        count - 1 for count in acquired_source_counts.values() if count > 1
    )

    baseline = [row for row in unique_observations if row["tesseract_claim"]]
    baseline_false = sum(not row["claim_correct"] for row in baseline)
    accepted = [row for row in unique_observations if row["accepted"]]
    accepted_false = sum(row["false_accepted"] for row in accepted)
    counterfactual_false = sum(
        row["counterfactual_false_accept"] for row in unique_observations
    )
    baseline_lower = clopper_pearson_lower(baseline_false, len(baseline))
    accepted_upper = clopper_pearson_upper(accepted_false, len(accepted))
    coverage_lower = clopper_pearson_lower(
        len(accepted), len(unique_observations)
    )
    coverage_upper = clopper_pearson_upper(
        len(accepted), len(unique_observations)
    )
    counterfactual_upper = clopper_pearson_upper(
        counterfactual_false, len(unique_observations)
    )
    reduction_lower = (
        baseline_lower / accepted_upper if accepted_upper > 0 else None
    )
    process_yield = (
        len(all_observations) / len(all_documents) if all_documents else 0.0
    )
    unique_evidence_yield = (
        len(unique_observations) / len(all_documents) if all_documents else 0.0
    )
    verifier_times = [
        float(row["verifier_runtime_ms"])
        for row in unique_observations
        if float(row["verifier_runtime_ms"]) > 0
    ]
    tesseract_times = [
        float(row["tesseract_runtime_ms"]) for row in unique_observations
    ]
    document_frontier = {
        str(locations_required): (
            math.ceil(locations_required / unique_evidence_yield)
            if unique_evidence_yield
            else None
        )
        for locations_required in (583, 760, 1090, 2200, 3840)
    }
    institutions = {
        str(row["institution_code"]) for row in unique_observations
    }
    readiness = {
        "baseline_informative": baseline_false > 0 and baseline_lower > 0,
        "minimum_unique_locations_200": len(unique_observations) >= 200,
        "minimum_accepted_100": len(accepted) >= 100,
        "minimum_institutions_10": len(institutions) >= 10,
        "coverage_lower_at_least_0_25": coverage_lower >= 0.25,
        "coverage_lower_at_least_0_30": coverage_lower >= 0.30,
        "counterfactual_minimum_100": len(unique_observations) >= 100,
        "counterfactual_upper_at_most_0_03": counterfactual_upper <= 0.03,
        "relative_10x_certificate_possible_from_observed_baseline": (
            baseline_false > 0 and baseline_lower > 0
        ),
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
            "documents_acquired": len(acquired),
            "unique_source_pdfs_acquired": len(acquired_source_counts),
            "reused_source_pdf_groups": reused_source_groups,
            "duplicate_source_pdf_process_associations": (
                duplicate_source_associations
            ),
            "processes_with_locations": len(all_observations),
            "process_associated_location_yield": process_yield,
            "unique_physical_locations": len(unique_observations),
            "unique_evidence_yield_per_attempted_process": unique_evidence_yield,
            "institutions_with_unique_locations": len(institutions),
            "document_frontier_at_unique_evidence_yield": document_frontier,
            "physical_evidence_reuse": {
                key: value
                for key, value in evidence_reuse.items()
                if key != "groups"
            },
        },
        "baseline": {
            "risk_unit": "unique physical evidence location",
            "predictions": len(baseline),
            "false_predictions": baseline_false,
            "observed_error_rate": (
                baseline_false / len(baseline) if baseline else None
            ),
            "simultaneous_95pct_lower": baseline_lower,
        },
        "verifier": {
            "risk_unit": "unique physical evidence location",
            "accepted": len(accepted),
            "false_accepted": accepted_false,
            "accepted_coverage_of_unique_locations": (
                len(accepted) / len(unique_observations)
                if unique_observations
                else 0.0
            ),
            "simultaneous_95pct_coverage_lower": coverage_lower,
            "simultaneous_95pct_coverage_upper": coverage_upper,
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
            "risk_unit": "unique physical evidence location",
            "cases": len(unique_observations),
            "false_accepts": counterfactual_false,
            "rejection_or_abstention_rate": (
                1 - counterfactual_false / len(unique_observations)
                if unique_observations
                else None
            ),
            "simultaneous_95pct_upper": counterfactual_upper,
        },
        "timing": {
            "median_tesseract_crop_ms": (
                statistics.median(tesseract_times) if tesseract_times else None
            ),
            "p95_tesseract_crop_ms": p95(tesseract_times),
        },
        "certificate_readiness": readiness,
        "decision": {
            "development_validation_complete": True,
            "pass_statistical_10x": False,
            "automatic_production_change": False,
            "final_holdout_should_remain_sealed": True,
            "verdict": (
                "DEVELOPMENT_VALIDATED_BASELINE_TOO_CLEAN_FOR_RELATIVE_10X"
                if not readiness["baseline_informative"]
                else "DEVELOPMENT_VALIDATED_FINAL_CERTIFICATE_NOT_RUN"
            ),
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
    reuse_path = output_dir / "physical_evidence_reuse.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reuse_path.write_text(
        json.dumps(evidence_reuse, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            [
                f"{_sha256(output_path)}  {output_path.name}",
                f"{_sha256(reuse_path)}  {reuse_path.name}",
            ]
        )
        + "\n",
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
