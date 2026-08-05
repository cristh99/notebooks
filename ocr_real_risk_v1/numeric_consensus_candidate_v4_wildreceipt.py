"""Freeze numeric-consensus-v4 after geometry discovery but before OCR.

The immutable WildReceipt objects were reserved before v4 development. A later
manifest-only attempt revealed that the mirror uses LayoutLM-normalized boxes;
no OCR binary or candidate inference ran. This candidate binds the corrected
projection, detector, byte-frozen forest, guard, risk unit, exact gates, and
runtime before any OCR outcome is generated.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .cord_detector_crops_v4 import SELECTED_CONFIGURATION
from .core import canonical_json, sha256_bytes, sha256_file
from .numeric_consensus_candidate_v4 import (
    DEVELOPMENT_ARTIFACT_ID,
    DEVELOPMENT_ARTIFACT_ZIP_SHA256,
    DEVELOPMENT_STABLE_SHA256,
    MODEL_ARTIFACT_ID,
    MODEL_ARTIFACT_ZIP_SHA256,
    MODEL_CANDIDATE_STABLE_SHA256,
    MODEL_SHA256,
    REQUIREMENTS,
    _full_hex,
    _verify_development,
)
from .numeric_digit_forest_deterministic import load_frozen_candidate
from .wildreceipt_adapter import (
    BBOX_COORDINATE_SPACE,
    DATASET_ID,
    DATASET_REVISION,
    REQUIRED_COLUMNS,
)
from .wildreceipt_source_seal import verify as verify_source_seal

CANDIDATE_SCHEMA = "ocr-numeric-consensus-wildreceipt-candidate/5"
CANDIDATE_ID = "numeric-consensus-v4-wildreceipt-schema-v2"
SCHEMA_DISCOVERY = {
    "workflow_run_id": 30991994931,
    "failure_stage": "outcome_blind_manifest_build_before_ocr",
    "opened_source_scope": (
        "prefix of the WildReceipt test split during manifest-only "
        "geometry census"
    ),
    "source_objects_downloaded": 3,
    "ocr_binary_installed": False,
    "ocr_executed": False,
    "candidate_inference_executed": False,
    "observed_schema_defect": (
        "LayoutLM-normalized 0-1000 bboxes were interpreted as "
        "image pixels"
    ),
    "repair_scope": "deterministic coordinate projection only",
    "numeric_text_scope_changed": False,
    "model_or_threshold_changed": False,
}
SOURCE_SEAL_STABLE_SHA256 = (
    "7775f57d92aa293b05e45298179154f54a3ffec1adb73087434fe54a1aa731f5"
)
SOURCE_OBJECTS = {
    "data/test-00000-of-00001.parquet": {
        "sha256": "43254778a33b83ae65f9a152b2b559a043f4d4239c4d903b4aca315d129efca0",
        "size_bytes": 427468952,
        "split": "test",
        "shard_id": "test-00000-of-00001",
    },
    "data/train-00000-of-00002.parquet": {
        "sha256": "f11bd09c7373df1726aa3fba02b6513c436809b3417c5b85a24cd0dd4226fc07",
        "size_bytes": 449790572,
        "split": "train",
        "shard_id": "train-00000-of-00002",
    },
    "data/train-00001-of-00002.parquet": {
        "sha256": "e988eeff3ad994f77c1c0fed0a85675f5f132f7911cb5574e8439c2661b0cce7",
        "size_bytes": 490390793,
        "split": "train",
        "shard_id": "train-00001-of-00002",
    },
}
SOURCE_FILES = (
    "ocr_real_risk_v1/__init__.py",
    "ocr_real_risk_v1/core.py",
    "ocr_real_risk_v1/exact_bounds.py",
    "ocr_real_risk_v1/pixel_digit_alignment.py",
    "ocr_real_risk_v1/numeric_digit_forest.py",
    "ocr_real_risk_v1/numeric_digit_forest_deterministic.py",
    "ocr_real_risk_v1/sroie_natural_holdout.py",
    "ocr_real_risk_v1/cord_natural_holdout.py",
    "ocr_real_risk_v1/cord_consensus_detector_v4.py",
    "ocr_real_risk_v1/wildreceipt_adapter.py",
    "ocr_real_risk_v1/wildreceipt_external.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py",
)


def external_protocol() -> dict[str, Any]:
    return {
        "protocol_id": (
            "wildreceipt-one-numeric-word-per-receipt-v2-layoutlm-geometry"
        ),
        "dataset": DATASET_ID,
        "revision": DATASET_REVISION,
        "lineage": {
            "upstream_dataset": "WildReceipt",
            "upstream_declared_license": "apache-2.0",
            "mirror_declared_license": None,
        },
        "source_objects": dict(SOURCE_OBJECTS),
        "required_columns": list(REQUIRED_COLUMNS),
        "annotation_geometry": {
            "source_coordinate_space": BBOX_COORDINATE_SPACE,
            "source_canvas": [1000, 1000],
            "target_coordinate_space": "original_image_pixels",
            "projection": (
                "floor lower bounds and ceil upper bounds after "
                "independent width/height scaling"
            ),
            "clipping": (
                "clip to normalized 0-1000 canvas; fail closed on "
                "non-positive, fully outside, or pixel-collapsed boxes"
            ),
            "repair_fixed_before_ocr": True,
        },
        "schema_discovery": dict(SCHEMA_DISCOVERY),
        "risk_unit": (
            "one SHA-256-selected eligible numeric annotation per unique physical "
            "receipt image; at most one unit survives per decoded image SHA-256"
        ),
        "selection": {
            "performed_before_ocr": True,
            "uses_candidate_outcome": False,
            "uses_ocr_output": False,
            "eligible_text": (
                "4-12 ASCII digits after separator/currency removal; standalone "
                "years, repeated-digit junk, letters, and non-ASCII digits excluded"
            ),
            "rank": (
                "SHA-256(dataset revision, shard, receipt id, image SHA-256, "
                "projected pixel bbox, canonical truth)"
            ),
            "deduplicate_candidates_within_receipt": "canonical truth plus bbox",
            "deduplicate_receipts_across_shards": "decoded image SHA-256",
            "duplicate_image_conflict": "fail_closed",
        },
        "baseline": {
            "engine": "Tesseract 5.3.4",
            "language": "eng",
            "oem": 1,
            "psm": 3,
            "input": "complete original receipt image",
            "spatial_truth_matching_only_for_scoring": True,
            "eligible_equal_canonical_length_required": True,
        },
        "candidate": {
            "detector_configuration": dict(SELECTED_CONFIGURATION),
            "input": "complete original receipt image",
            "claim_resolution": "selected spatial detector cluster only for scoring",
            "forest_threshold": 0.25,
            "crop_guard": "independent PSM-7 gray or autocontrast reading equals claim",
            "truth_available_at_inference": False,
            "annotation_bbox_available_at_inference": False,
            "threshold_change_after_outcomes": False,
        },
        "counterfactual": {
            "one_equal_length_digit_substitution_per_selected_receipt": True,
            "generated_before_candidate_inference": True,
        },
        "exact_gates": {
            "family_alpha": 0.05,
            "alpha_per_leg_bonferroni": 0.0125,
            "target_error_reduction": 10.0,
            "minimum_selected_unique_receipts": 1200,
            "minimum_accepted": 400,
            "minimum_coverage_lower": 0.25,
            "counterfactual_maximum_upper": 0.01,
            "baseline_errors_must_be_positive": True,
            "candidate_upper_must_not_exceed_baseline_lower_divided_by_10": True,
            "leave_one_source_shard_out_minimum_pass_fraction": 2.0 / 3.0,
        },
        "power_plan": {
            "published_receipt_rows_from_hub_metadata": 1739,
            "maximum_possible_selected_unique_receipts": 1739,
            "minimum_selected_unique_receipts": 1200,
            "minimum_selection_yield_required": 0.6900517538815412,
            "development_selected": 993,
            "development_accepted": 319,
            "development_acceptance_rate": 0.32124874118831825,
            "minimum_selected_for_projected_400_accepts": 1246,
            "minimum_selection_yield_for_projected_400_accepts": (
                0.7165037377803335
            ),
            "finite_population_feasibility": True,
            "underpower_is_an_allowed_terminal_result": True,
            "planning_only_not_a_certificate": True,
        },
        "runtime": {
            "source_shards": 3,
            "one_worker_per_source_shard": True,
            "same_candidate_bytes_and_runtime_in_every_worker": True,
            "aggregate_recomputes_deduplication_and_all_exact_bounds": True,
        },
        "claim_limits": {
            "schema_repaired_external_numeric_certificate_only": True,
            "untouched_external_certificate_claimed": False,
            "general_ocr_superiority_claimed": False,
            "honduras_production_readiness_claimed": False,
            "production_change_automatic": False,
        },
    }


def verify_manifest(payload: Mapping[str, Any]) -> bool:
    stable = dict(payload)
    observed = str(stable.pop("stable_payload_sha256", ""))
    return observed == sha256_bytes(canonical_json(stable).encode("utf-8"))


def _copy_sources(repository_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in SOURCE_FILES:
        source = repository_root / relative
        if not source.is_file():
            raise RuntimeError(f"candidate source file missing: {relative}")
        destination = output_dir / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        records.append(
            {
                "path": relative,
                "sha256": sha256_file(destination),
                "size_bytes": destination.stat().st_size,
            }
        )
    return records


def build_candidate(
    *,
    repository_root: Path,
    model_root: Path,
    development_report_path: Path,
    source_seal_path: Path,
    source_commit: str,
    output_dir: Path,
) -> dict[str, Any]:
    source_commit = _full_hex(source_commit, 40)
    if not source_commit:
        raise RuntimeError("candidate source commit is not a full SHA")
    development = json.loads(development_report_path.read_text(encoding="utf-8"))
    _verify_development(development)
    source_seal = json.loads(source_seal_path.read_text(encoding="utf-8"))
    if not verify_source_seal(source_seal):
        raise RuntimeError("WildReceipt source seal stable payload failed")
    if source_seal.get("stable_payload_sha256") != SOURCE_SEAL_STABLE_SHA256:
        raise RuntimeError("WildReceipt source seal changed")
    if source_seal.get("resolved_revision") != DATASET_REVISION:
        raise RuntimeError("WildReceipt revision changed")
    for field in (
        "parquet_shards_downloaded",
        "dataset_rows_read",
        "images_opened",
        "annotations_opened",
    ):
        if int(source_seal.get(field, -1)) != 0:
            raise RuntimeError(f"WildReceipt was opened before candidate freeze: {field}")
    observed_objects = {
        row["path"]: {
            "sha256": row["identity"]["digest"],
            "size_bytes": int(row["size_bytes"]),
        }
        for row in source_seal.get("objects", [])
    }
    expected_objects = {
        path: {
            "sha256": spec["sha256"],
            "size_bytes": spec["size_bytes"],
        }
        for path, spec in SOURCE_OBJECTS.items()
    }
    if observed_objects != expected_objects:
        raise RuntimeError("WildReceipt sealed object set changed")

    model_candidate, model = load_frozen_candidate(model_root)
    if model_candidate.get("stable_payload_sha256") != MODEL_CANDIDATE_STABLE_SHA256:
        raise RuntimeError("digit-forest-v3 stable payload changed")
    if model_candidate.get("model", {}).get("sha256") != MODEL_SHA256:
        raise RuntimeError("digit-forest-v3 model SHA-256 changed")
    if float(model_candidate.get("inference", {}).get("threshold", -1.0)) != 0.25:
        raise RuntimeError("digit-forest-v3 threshold changed")
    if len(model.estimators_) != 500:
        raise RuntimeError("digit-forest-v3 tree count changed")

    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_dir = output_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "digit_forest.joblib",
        "frozen_candidate.json",
        "development_report.json",
        "development_decisions.jsonl",
        "SHA256SUMS.txt",
    ):
        source = model_root / name
        if not source.is_file():
            raise RuntimeError(f"digit model artifact missing: {name}")
        shutil.copyfile(source, model_dir / name)
    source_records = _copy_sources(repository_root, output_dir)
    requirements_path = output_dir / "requirements.lock"
    requirements_path.write_text("\n".join(REQUIREMENTS) + "\n", encoding="utf-8")
    seal_copy = output_dir / "wildreceipt_source_seal_v1.json"
    seal_copy.write_text(
        json.dumps(source_seal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    development_copy = output_dir / "cord_v4_development_evidence.json"
    development_copy.write_text(
        json.dumps(development, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "status": (
            "FROZEN_AFTER_WILDRECEIPT_GEOMETRY_SCHEMA_DISCOVERY_"
            "BEFORE_ANY_OCR_OUTCOMES"
        ),
        "source_commit": source_commit,
        "source_files": source_records,
        "runtime": {
            "requirements": list(REQUIREMENTS),
            "requirements_file": requirements_path.name,
            "requirements_sha256": sha256_file(requirements_path),
            "deterministic_threads": 1,
        },
        "detector": {
            "configuration": dict(SELECTED_CONFIGURATION),
            "development_artifact_id": DEVELOPMENT_ARTIFACT_ID,
            "development_artifact_zip_sha256": DEVELOPMENT_ARTIFACT_ZIP_SHA256,
            "development_stable_payload_sha256": DEVELOPMENT_STABLE_SHA256,
            "development_evidence_sha256": sha256_file(development_copy),
        },
        "digit_model": {
            "artifact_id": MODEL_ARTIFACT_ID,
            "artifact_zip_sha256": MODEL_ARTIFACT_ZIP_SHA256,
            "candidate_stable_payload_sha256": MODEL_CANDIDATE_STABLE_SHA256,
            "model_file": "model/digit_forest.joblib",
            "model_sha256": sha256_file(model_dir / "digit_forest.joblib"),
            "threshold": 0.25,
            "tree_count": 500,
        },
        "external_source_binding": {
            "dataset_id": source_seal["dataset_id"],
            "resolved_revision": source_seal["resolved_revision"],
            "source_seal_file": seal_copy.name,
            "source_seal_file_sha256": sha256_file(seal_copy),
            "source_seal_stable_payload_sha256": source_seal[
                "stable_payload_sha256"
            ],
            "original_source_seal_unopened": True,
            "source_rows_opened_before_this_freeze": True,
            "ocr_executed_before_this_freeze": False,
            "candidate_inference_executed_before_this_freeze": False,
            "schema_discovery": dict(SCHEMA_DISCOVERY),
        },
        "external_protocol": external_protocol(),
        "development_evidence": {
            "selected": 993,
            "eligible": 504,
            "baseline_errors": 46,
            "accepted": 319,
            "natural_false_accepts": 0,
            "counterfactual_false_accepts": 0,
            "coverage_lower": development["exact_diagnostics"]["all"][
                "coverage_lower"
            ],
            "reduction_lower": development["exact_diagnostics"]["all"][
                "reduction_lower"
            ],
            "internal_only": True,
        },
        "decision": {
            "candidate_frozen_before_wildreceipt_ocr_outcomes": True,
            "candidate_frozen_before_wildreceipt_source_opening": False,
            "ready_for_one_wildreceipt_schema_repaired_external_evaluation": True,
            "untouched_external_certificate_claimed": False,
            "external_certificate_claimed": False,
            "tenfold_reduction_claimed": False,
            "production_ready": False,
            "honduras_production_ready": False,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    manifest["stable_payload_sha256"] = sha256_bytes(
        canonical_json(manifest).encode("utf-8")
    )
    path = output_dir / "frozen_candidate.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"{sha256_file(file)}  {file.relative_to(output_dir)}"
        for file in sorted(output_dir.rglob("*"))
        if file.is_file() and file.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    if not verify_manifest(manifest):
        raise RuntimeError("WildReceipt candidate manifest did not replay")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--development-report", required=True, type=Path)
    parser.add_argument("--source-seal", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build_candidate(
        repository_root=args.repository_root,
        model_root=args.model_root,
        development_report_path=args.development_report,
        source_seal_path=args.source_seal,
        source_commit=args.source_commit,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
