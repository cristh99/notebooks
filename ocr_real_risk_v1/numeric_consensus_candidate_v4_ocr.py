"""Freeze numeric-consensus-v4 for untouched CORU OCR line images.

This binding uses all three CORU OCR archives, whose metadata was sealed before
any member was listed. The claim scope is explicitly limited to ASCII numeric
line labels. The detector, forest, guard, parser, gates, and runtime are frozen
before archive inspection or OCR execution.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .cord_detector_crops_v4 import SELECTED_CONFIGURATION
from .core import canonical_json, sha256_bytes, sha256_file
from .coru_ocr_source_seal import (
    DATASET_ID,
    EXPECTED_FILES,
    verify as verify_source_seal,
)
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

CANDIDATE_SCHEMA = "ocr-numeric-consensus-ocr-candidate/4"
CANDIDATE_ID = "numeric-consensus-v4-coru-ocr"
CORU_OCR_SOURCE_SEAL_STABLE_SHA256 = (
    "4929ee6035d37f46b591c49858b5280c2941dfd9edd98b6581a27667bfb43c2b"
)
CORU_REVISION = "c3c4b97b232bbe03046c78a974f516d439c1124e"
EXPECTED_SPLITS = {"train": 21000, "validation": 4500, "test": 4500}
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
    "ocr_real_risk_v1/coru_ocr_archive.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_ocr.py",
)


def external_protocol() -> dict[str, Any]:
    return {
        "protocol_id": "coru-ocr-ascii-numeric-all-splits-v1",
        "dataset": DATASET_ID,
        "component": "OCR",
        "revision": CORU_REVISION,
        "archives": list(EXPECTED_FILES),
        "expected_images": dict(EXPECTED_SPLITS),
        "expected_total_images": sum(EXPECTED_SPLITS.values()),
        "archive_adapter": {
            "module": "ocr_real_risk_v1.coru_ocr_archive",
            "explicit_pairing_priority": [
                "same_stem_label_file",
                "json_record_or_dictionary",
                "delimited_manifest",
                "double_underscore_filename_label_only_if_coverage_at_least_99pct",
            ],
            "conflicting_labels": "fail_closed",
            "unresolved_labels": "fail_closed",
            "unsafe_members": "fail_closed",
            "nested_archives": "unsupported_fail_closed",
            "schema_change_after_opening": False,
        },
        "risk_unit": (
            "one unique physical line image paired to one explicit transcription; "
            "all labels that reduce to 4-12 ASCII digits after separator and "
            "currency removal, excluding standalone years and repeated-digit junk"
        ),
        "selection": {
            "all_three_published_splits": True,
            "selection_uses_ocr": False,
            "selection_uses_candidate_outcome": False,
            "only_ascii_digit_glyphs": True,
            "unicode_non_ascii_digits_out_of_scope": True,
            "deduplicate_by": "decoded image SHA-256 plus canonical label",
            "one_evaluation_per_physical_pair": True,
        },
        "baseline": {
            "engine": "Tesseract 5.3.4",
            "language": "eng",
            "psm": 7,
            "input": "original complete line image",
            "canonicalization": "ASCII digits only; separators and currency removed",
            "eligible_only_when_equal_length_4_to_12_digit_claim": True,
        },
        "candidate": {
            "detector_configuration": dict(SELECTED_CONFIGURATION),
            "detector_language": "eng",
            "input": "original complete line image",
            "claim_resolution": (
                "exactly one resolved canonical digit string across spatial clusters; "
                "otherwise abstain"
            ),
            "forest_threshold": 0.25,
            "crop_guard": "PSM-7 gray or autocontrast reading equals claim",
            "truth_available_at_inference": False,
            "threshold_change_after_outcomes": False,
        },
        "counterfactual": {
            "one_equal_length_digit_substitution_per_selected_pair": True,
            "generated_before_candidate_inference": True,
        },
        "exact_gates": {
            "family_alpha": 0.05,
            "alpha_per_leg_bonferroni": 0.0125,
            "target_error_reduction": 10.0,
            "minimum_selected_physical_pairs": 3000,
            "minimum_accepted": 900,
            "minimum_coverage_lower": 0.25,
            "counterfactual_maximum_upper": 0.01,
            "baseline_errors_must_be_positive": True,
            "candidate_upper_must_not_exceed_baseline_lower_divided_by_10": True,
            "leave_one_split_out_minimum_pass_fraction": 2.0 / 3.0,
        },
        "runtime": {
            "partitions": 60,
            "partition_assignment": "SHA-256(image bytes) modulo 60",
            "same_bytes_and_configuration_in_every_partition": True,
            "aggregate_recomputes_all_exact_bounds": True,
        },
        "claim_limits": {
            "external_numeric_quality_certificate_only": True,
            "general_ocr_superiority_claimed": False,
            "arabic_digit_superiority_claimed": False,
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
        raise RuntimeError("CORU OCR source seal stable payload failed")
    if source_seal.get("stable_payload_sha256") != CORU_OCR_SOURCE_SEAL_STABLE_SHA256:
        raise RuntimeError("CORU OCR source seal changed")
    if source_seal.get("resolved_revision") != CORU_REVISION:
        raise RuntimeError("CORU OCR revision changed")
    if source_seal.get("outcomes_opened") is not False:
        raise RuntimeError("CORU OCR outcomes were opened before freeze")
    for field in (
        "archives_downloaded",
        "archive_members_listed",
        "labels_read",
        "images_opened",
    ):
        if int(source_seal.get(field, -1)) != 0:
            raise RuntimeError(f"CORU OCR source was opened before freeze: {field}")
    if {row["path"] for row in source_seal.get("objects", [])} != set(EXPECTED_FILES):
        raise RuntimeError("CORU OCR archive set changed")

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
    seal_copy = output_dir / "coru_ocr_source_seal_v1.json"
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
        "status": "FROZEN_FOR_UNTOUCHED_CORU_OCR_EXTERNAL_VALIDATION_ONLY",
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
            "component": source_seal["component"],
            "resolved_revision": source_seal["resolved_revision"],
            "source_seal_file": seal_copy.name,
            "source_seal_file_sha256": sha256_file(seal_copy),
            "source_seal_stable_payload_sha256": source_seal[
                "stable_payload_sha256"
            ],
            "outcomes_opened_before_freeze": False,
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
            "candidate_frozen_before_coru_ocr_outcomes": True,
            "ready_for_one_coru_ocr_external_evaluation": True,
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
        raise RuntimeError("CORU OCR candidate manifest did not replay")
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
