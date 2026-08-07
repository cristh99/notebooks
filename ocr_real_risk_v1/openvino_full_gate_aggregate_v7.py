"""Fail-closed exact aggregation for the OpenVINO v7 full external gate."""
from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import sha256_file
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .openvino_full_gate_contract_v7 import (
    ABSTAIN_DEDUP_OR_INTEGRITY,
    AGGREGATE_SCHEMA,
    ALPHA_PER_LEG,
    CANDIDATE_STABLE_PAYLOAD_SHA256,
    COUNTERFACTUAL_MAXIMUM_UPPER,
    FAIL_FULL_EXTERNAL_GATE,
    MACROFOLD_COUNT,
    MINIMUM_ACTIVE_AFTER_DEDUP,
    MINIMUM_COVERAGE_LOWER,
    MINIMUM_MACROFOLD_PASS_FRACTION,
    MODEL_ARTIFACT_ID,
    MODEL_CANDIDATE_STABLE_SHA256,
    MODEL_SHA256,
    MODEL_ZIP_SHA256,
    PARTITION_COUNT,
    PARTITION_REPORT_SCHEMA,
    PASS_FULL_EXTERNAL_GATE,
    SCIENTIFIC_MANIFEST_SHA256,
    SOURCE_COMMIT,
    TARGET_ERROR_REDUCTION,
    _is_sha256,
    _read_json,
    _write_json,
    stable_payload,
    verify_hash_manifest,
    verify_stable_payload,
    write_hash_manifest,
)
from .openvino_full_gate_execution_v7 import (
    claim_binding,
    current_code_bundle,
    verify_bound_execution_authorization,
    verify_execution_claim,
)
from .openvino_full_gate_registry_v7 import verify_registry_bundle
from .openvino_preexecution_gate_v7 import verify_preexecution_gate


def exact_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    minimum_selected: int = MINIMUM_ACTIVE_AFTER_DEDUP,
) -> dict[str, Any]:
    selected = list(rows)
    baseline = [row for row in selected if row.get("baseline", {}).get("eligible")]
    baseline_false = sum(
        row.get("baseline", {}).get("claim_correct") is False for row in baseline
    )
    accepted = [row for row in selected if row.get("candidate", {}).get("accepted")]
    accepted_false = sum(
        bool(row.get("candidate", {}).get("false_accept")) for row in accepted
    )
    counterfactual_false = sum(
        bool(row.get("counterfactual", {}).get("accepted")) for row in selected
    )
    baseline_lower = (
        clopper_pearson_lower(baseline_false, len(baseline), ALPHA_PER_LEG)
        if baseline
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(accepted_false, len(accepted), ALPHA_PER_LEG)
        if accepted
        else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(len(accepted), len(selected), ALPHA_PER_LEG)
        if selected
        else 0.0
    )
    counterfactual_upper = (
        clopper_pearson_upper(counterfactual_false, len(selected), ALPHA_PER_LEG)
        if selected
        else 1.0
    )
    reduction_lower = (
        baseline_lower / candidate_upper if candidate_upper > 0.0 else None
    )
    passed = bool(
        len(selected) >= minimum_selected
        and baseline_false > 0
        and coverage_lower >= MINIMUM_COVERAGE_LOWER
        and candidate_upper <= baseline_lower / TARGET_ERROR_REDUCTION
        and counterfactual_upper <= COUNTERFACTUAL_MAXIMUM_UPPER
    )
    return {
        "selected": len(selected),
        "baseline_eligible": len(baseline),
        "baseline_false": baseline_false,
        "accepted": len(accepted),
        "accepted_false": accepted_false,
        "counterfactual_false": counterfactual_false,
        "baseline_lower": baseline_lower,
        "candidate_upper": candidate_upper,
        "coverage_lower": coverage_lower,
        "counterfactual_upper": counterfactual_upper,
        "reduction_lower": reduction_lower,
        "minimum_selected_required": minimum_selected,
        "pass": passed,
    }


def _scaled_minimum(full_minimum: int, subset: int, full: int) -> int:
    return max(1, math.ceil(full_minimum * subset / max(full, 1)))


def _validate_report_identity(
    report: Mapping[str, Any],
    *,
    expected_code_bundle: Mapping[str, str],
    authorization_binding: Mapping[str, Any],
    expected_preexecution: Mapping[str, Any] | None = None,
) -> None:
    source = report.get("source_identity")
    runtime = report.get("runtime")
    model = report.get("model")
    if (
        report.get("authorization_binding") != authorization_binding
        or (
            expected_preexecution is not None
            and report.get("preexecution_binding") != expected_preexecution
        )
        or report.get("code_bundle") != expected_code_bundle
        or report.get("executor_source_sha256")
        != expected_code_bundle[
            "ocr_real_risk_v1/openvino_full_gate_runner_v7.py"
        ]
        or not isinstance(source, Mapping)
        or source.get("source_commit") != SOURCE_COMMIT
        or source.get("all_match_frozen_commit") is not True
        or not isinstance(runtime, Mapping)
        or runtime.get("strict_match") is not True
        or not isinstance(model, Mapping)
        or model.get("artifact_id") != MODEL_ARTIFACT_ID
        or model.get("artifact_zip_sha256") != MODEL_ZIP_SHA256
        or model.get("model_sha256") != MODEL_SHA256
        or model.get("candidate_stable_payload_sha256")
        != MODEL_CANDIDATE_STABLE_SHA256
        or model.get("tree_count") != 500
        or report.get("annotation_query_executed_after_detector_barrier") is not True
        or report.get("detector_barrier_rows") != report.get("record_count")
        or not _is_sha256(report.get("detector_barrier_sha256"))
    ):
        raise RuntimeError("partition frozen identity/barrier contract failed")


def aggregate_partition_reports(
    reports: Sequence[Mapping[str, Any]],
    *,
    expected_partition_counts: Sequence[int],
    registry_stable_payload_sha256: str,
    expected_code_bundle: Mapping[str, str],
    authorization_binding: Mapping[str, Any],
    expected_preexecution: Mapping[str, Any] | None = None,
    minimum_active: int = MINIMUM_ACTIVE_AFTER_DEDUP,
) -> dict[str, Any]:
    if len(expected_partition_counts) != PARTITION_COUNT:
        raise RuntimeError("twelve expected partition counts are required")
    if dict(expected_code_bundle) != current_code_bundle():
        raise RuntimeError("aggregate code bundle differs from checked-out executor")
    by_partition: dict[int, Mapping[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for report in reports:
        if (
            report.get("schema") != PARTITION_REPORT_SCHEMA
            or not verify_stable_payload(report)
            or report.get("candidate_stable_payload_sha256")
            != CANDIDATE_STABLE_PAYLOAD_SHA256
            or report.get("registry_stable_payload_sha256")
            != registry_stable_payload_sha256
            or report.get("scientific_manifest_sha256")
            != SCIENTIFIC_MANIFEST_SHA256
            or report.get("partition_count") != PARTITION_COUNT
            or report.get("execution_complete") is not True
        ):
            raise RuntimeError("partition report contract failed")
        _validate_report_identity(
            report,
            expected_code_bundle=expected_code_bundle,
            authorization_binding=authorization_binding,
            expected_preexecution=expected_preexecution,
        )
        partition = int(report.get("partition_id", -1))
        if not 0 <= partition < PARTITION_COUNT or partition in by_partition:
            raise RuntimeError("missing/duplicate/invalid partition report")
        rows = list(report.get("observations") or [])
        if len(rows) != int(report.get("record_count") or -1):
            raise RuntimeError("partition report record count drift")
        if len(rows) != int(expected_partition_counts[partition]):
            raise RuntimeError("partition report differs from registry denominator")
        by_partition[partition] = report
        observations.extend(dict(row) for row in rows)
    if set(by_partition) != set(range(PARTITION_COUNT)):
        raise RuntimeError("all twelve partition reports are required")

    integrity_reasons: list[str] = []
    seen_rows: set[int] = set()
    seen_images: set[str] = set()
    seen_encoded: set[str] = set()
    seen_pixels: set[str] = set()
    for row in observations:
        partition = int(row.get("partition_id", -1))
        row_index = int(row.get("row_index", -1))
        image_id = str(row.get("image_id") or "")
        encoded = str(row.get("encoded_sha256") or "")
        pixels = str(row.get("pixel_sha256") or "")
        quarantine = row.get("outcome_quarantine") or {}
        if (
            partition not in by_partition
            or int(row.get("macrofold_id", -1)) != partition // 3
        ):
            integrity_reasons.append("PARTITION_OR_MACROFOLD_MISMATCH")
        if row_index in seen_rows or image_id in seen_images:
            integrity_reasons.append("DUPLICATE_ROW_OR_IMAGE_ID")
        if encoded in seen_encoded or pixels in seen_pixels:
            integrity_reasons.append("DUPLICATE_PHYSICAL_EVIDENCE")
        if not _is_sha256(encoded) or not _is_sha256(pixels):
            integrity_reasons.append("INVALID_PHYSICAL_HASH")
        if row.get("terminal") is not True:
            integrity_reasons.append("NONTERMINAL_OBSERVATION")
        if (
            quarantine.get("detector_completed_before_annotation_query") is not True
            or quarantine.get("annotation_query_after_partition_detector_barrier")
            is not True
        ):
            integrity_reasons.append("OUTCOME_QUARANTINE_VIOLATION")
        detector = row.get("detector")
        if isinstance(detector, Mapping) and detector.get("all_calls_terminal") is False:
            integrity_reasons.append("OCR_TIMEOUT")
        seen_rows.add(row_index)
        seen_images.add(image_id)
        seen_encoded.add(encoded)
        seen_pixels.add(pixels)

    detector_seconds = sum(
        float(row.get("baseline", {}).get("wall_seconds") or 0.0)
        for row in observations
    )
    verifier_seconds = sum(
        float(row.get("candidate", {}).get("verifier_wall_seconds") or 0.0)
        for row in observations
    )
    common = {
        "schema": AGGREGATE_SCHEMA,
        "candidate_stable_payload_sha256": CANDIDATE_STABLE_PAYLOAD_SHA256,
        "registry_stable_payload_sha256": registry_stable_payload_sha256,
        "scientific_manifest_sha256": SCIENTIFIC_MANIFEST_SHA256,
        "authorization_binding": authorization_binding,
        "preexecution_binding": expected_preexecution,
        "code_bundle": dict(expected_code_bundle),
    }
    if integrity_reasons:
        return stable_payload(
            {
                **common,
                "status": ABSTAIN_DEDUP_OR_INTEGRITY,
                "scientific_verdict": ABSTAIN_DEDUP_OR_INTEGRITY,
                "integrity": {
                    "pass": False,
                    "reasons": sorted(set(integrity_reasons)),
                },
                "execution": {
                    "selected": len(observations),
                    "partition_count": len(by_partition),
                    "macrofold_count": MACROFOLD_COUNT,
                },
                "speed": {
                    "measured": True,
                    "detector_wall_seconds": detector_seconds,
                    "verifier_wall_seconds": verifier_seconds,
                    "verifier_to_detector_ratio": (
                        verifier_seconds / detector_seconds
                        if detector_seconds
                        else None
                    ),
                    "claim_authorized": False,
                },
                "retuning_authorized": False,
                "automatic_production_change": False,
            }
        )

    overall = exact_summary(observations, minimum_selected=minimum_active)
    folds: list[dict[str, Any]] = []
    for held_out in range(MACROFOLD_COUNT):
        subset = [
            row for row in observations if int(row["macrofold_id"]) != held_out
        ]
        folds.append(
            {
                "held_out_macrofold": held_out,
                "summary": exact_summary(
                    subset,
                    minimum_selected=_scaled_minimum(
                        minimum_active, len(subset), len(observations)
                    ),
                ),
            }
        )
    stability_passes = sum(bool(fold["summary"]["pass"]) for fold in folds)
    stability_fraction = stability_passes / MACROFOLD_COUNT
    stability_pass = stability_fraction >= MINIMUM_MACROFOLD_PASS_FRACTION
    scientific_pass = bool(overall["pass"] and stability_pass)
    status = PASS_FULL_EXTERNAL_GATE if scientific_pass else FAIL_FULL_EXTERNAL_GATE
    return stable_payload(
        {
            **common,
            "status": status,
            "scientific_verdict": status,
            "integrity": {"pass": True, "reasons": []},
            "execution": {
                "selected": len(observations),
                "partition_count": PARTITION_COUNT,
                "partition_counts": list(expected_partition_counts),
                "macrofold_count": MACROFOLD_COUNT,
                "unique_rows": len(seen_rows),
                "unique_image_ids": len(seen_images),
                "unique_encoded_images": len(seen_encoded),
                "unique_decoded_pixels": len(seen_pixels),
            },
            "overall": overall,
            "stability": {
                "semantics": "leave_one_macrofold_out",
                "macrofold_groups": [
                    [0, 1, 2],
                    [3, 4, 5],
                    [6, 7, 8],
                    [9, 10, 11],
                ],
                "passes": stability_passes,
                "pass_fraction": stability_fraction,
                "minimum_pass_fraction": MINIMUM_MACROFOLD_PASS_FRACTION,
                "pass": stability_pass,
                "details": folds,
            },
            "speed": {
                "measured": True,
                "detector_wall_seconds": detector_seconds,
                "verifier_wall_seconds": verifier_seconds,
                "verifier_to_detector_ratio": (
                    verifier_seconds / detector_seconds if detector_seconds else None
                ),
                "tenfold_threshold": 0.1,
                "claim_authorized": False,
                "reason": "frozen candidate speed_gate.claim_authorized=false",
            },
            "claims": {
                "end_to_end_ocr_superiority": False,
                "honduras_transfer": False,
                "production_readiness": False,
                "fraud_detection": False,
            },
            "retuning_authorized": False,
            "post_outcome_retry_authorized": False,
            "automatic_production_change": False,
        }
    )


def aggregate_from_files(
    *,
    registry_root: Path,
    report_roots: Sequence[Path],
    authorization_path: Path,
    authorization_sha256: str,
    execution_claim_path: Path,
    execution_claim_sha256: str,
    output_dir: Path,
) -> dict[str, Any]:
    authorization = verify_bound_execution_authorization(
        authorization_path, authorization_sha256, "AGGREGATE"
    )
    preexecution = verify_preexecution_gate(authorization)
    claim = verify_execution_claim(
        execution_claim_path, execution_claim_sha256, authorization
    )
    expected_binding = claim_binding(
        authorization,
        claim,
        authorization_file_sha256=authorization_sha256,
        claim_file_sha256=execution_claim_sha256,
    )
    registry = verify_registry_bundle(registry_root)
    registry_receipt = _read_json(Path(registry_root) / "registry_receipt.json")
    if (
        registry.get("evaluation_authorized") is not True
        or registry.get("authorization_binding") != expected_binding
        or registry_receipt.get("preexecution_binding") != preexecution
        or registry_receipt.get("code_bundle") != authorization["code_bundle"]
        or registry_receipt.get("prior_registry", {}).get("stable_payload_sha256")
        != authorization["prior_registry_stable_payload_sha256"]
    ):
        raise RuntimeError("registry and aggregate one-shot bindings differ")
    reports: list[dict[str, Any]] = []
    for root in report_roots:
        verify_hash_manifest(
            root,
            exact_files={"partition_report.json", "detector_barrier.jsonl"},
        )
        report = _read_json(Path(root) / "partition_report.json")
        actual_barrier = sha256_file(Path(root) / "detector_barrier.jsonl")
        if report.get("detector_barrier_sha256") != actual_barrier:
            raise RuntimeError("partition report/barrier cross-hash mismatch")
        reports.append(report)
    aggregate = aggregate_partition_reports(
        reports,
        expected_partition_counts=registry["partition_counts"],
        registry_stable_payload_sha256=registry["stable_payload_sha256"],
        expected_code_bundle=authorization["code_bundle"],
        authorization_binding=expected_binding,
        expected_preexecution=preexecution,
    )
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "openvino_v7_external_aggregate.json", aggregate)
    write_hash_manifest(output_dir)
    return aggregate
