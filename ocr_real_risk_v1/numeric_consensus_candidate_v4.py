"""Freeze the complete numeric-consensus-v4 pipeline before CORU outcomes.

The candidate combines the byte-frozen digit-forest-v3 model with the selected
full-image multi-PSM detector and independent PSM-7 crop guard. Development
outcomes from CORD are bound as evidence only. The candidate is valid solely
for one untouched CORU Receipt test evaluation and never changes production.
"""
from __future__ import annotations

import argparse
import json
import shutil
import string
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cord_consensus_detector_v4 import (
    AGGREGATE_SCHEMA as DEVELOPMENT_SCHEMA,
    STATUS as DEVELOPMENT_STATUS,
)
from .cord_detector_crops_v4 import SELECTED_CONFIGURATION
from .core import canonical_json, sha256_bytes, sha256_file
from .coru_source_seal import (
    DATASET_ID as CORU_DATASET_ID,
    verify as verify_coru_source_seal,
)
from .numeric_digit_forest_deterministic import load_frozen_candidate
from .sroie_natural_holdout import verify_stable_payload

CANDIDATE_SCHEMA = "ocr-numeric-consensus-candidate/4"
CANDIDATE_ID = "numeric-consensus-v4"
MODEL_ARTIFACT_ID = 8917522937
MODEL_ARTIFACT_ZIP_SHA256 = (
    "080b0efd4b91a180a1a5c6acd767d72e0a8f286718e64eb90d8ec9d370d2dc17"
)
MODEL_SHA256 = "53229915331c2bbea2454f9e7cb5768a26e9edb30de750747f4397f1ff4cf92c"
MODEL_CANDIDATE_STABLE_SHA256 = (
    "0f88d94af81e0f7921e654e452059d2075b07ee35bcffd83dd8b02ebdd9e93a1"
)
DEVELOPMENT_ARTIFACT_ID = 8919281422
DEVELOPMENT_ARTIFACT_ZIP_SHA256 = (
    "766be199eafc3f87437359a39d1685fb4dd67772643cb459f845a24a838bf6a1"
)
DEVELOPMENT_STABLE_SHA256 = (
    "cdad9018a3049848ad86fc53ce9a4a201391b8d36c2106d8239160226692b58b"
)
CORU_SOURCE_SEAL_STABLE_SHA256 = (
    "d97900ffadd1871f2062bb33f44dd69a10a2bcb298b187e079673037e87edeb3"
)
CORU_REVISION = "c3c4b97b232bbe03046c78a974f516d439c1124e"

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
    "ocr_real_risk_v1/numeric_consensus_candidate_v4.py",
)
REQUIREMENTS = (
    "python==3.11",
    "tesseract==5.3.4",
    "Pillow==12.2.0",
    "numpy==2.2.6",
    "opencv-python-headless==4.10.0.84",
    "scikit-learn==1.8.0",
    "joblib==1.5.3",
    "pyarrow==18.1.0",
    "pytesseract==0.3.13",
)


def _full_hex(value: object, length: int) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != length or any(character not in string.hexdigits for character in raw):
        return ""
    return raw


def external_protocol() -> dict[str, Any]:
    """Return the frozen external protocol without touching CORU content."""
    return {
        "protocol_id": "coru-receipt-test-numeric-v1",
        "dataset": CORU_DATASET_ID,
        "component": "Receipt",
        "revision": CORU_REVISION,
        "evaluation_files": [
            "Receipt/labels.txt",
            "Receipt/test.json",
            "Receipt/test.zip",
        ],
        "expected_published_test_receipts": 3700,
        "risk_unit": (
            "one SHA-256-selected 4-12 digit annotation per physical receipt"
        ),
        "selection": {
            "performed_before_ocr": True,
            "uses_candidate_outcome": False,
            "uses_ocr_output": False,
            "deduplicate_by": "decoded image SHA-256 plus annotation bbox",
            "normalization": (
                "Unicode digits normalized to ASCII; currency and separators "
                "removed; standalone years and repeated-digit junk excluded"
            ),
        },
        "inference": {
            "input": "complete original receipt image",
            "candidate_psms": list(SELECTED_CONFIGURATION["psms"]),
            "minimum_distinct_psm_votes": SELECTED_CONFIGURATION[
                "minimum_distinct_psm_votes"
            ],
            "reject_equal_length_conflict": SELECTED_CONFIGURATION[
                "reject_equal_length_conflict"
            ],
            "crop_guard": "independent PSM-7 gray or autocontrast reading equals claim",
            "digit_forest_threshold": 0.25,
            "truth_available": False,
            "annotation_bbox_available": False,
            "threshold_change_after_outcomes": False,
        },
        "exact_gates": {
            "family_alpha": 0.05,
            "alpha_per_leg_bonferroni": 0.0125,
            "target_error_reduction": 10.0,
            "minimum_selected_physical_locations": 3000,
            "minimum_accepted": 900,
            "minimum_coverage_lower": 0.25,
            "counterfactual_maximum_upper": 0.01,
            "baseline_errors_must_be_positive": True,
            "candidate_upper_must_not_exceed_baseline_lower_divided_by_10": True,
        },
        "power_plan": {
            "development_selected": 993,
            "development_accepted": 319,
            "development_baseline_errors": 46,
            "plugin_projection_selected_for_10x_if_rates_hold": 1889,
            "conservative_selected_target": 3065,
            "coru_test_expected_receipts": 3700,
            "planning_only_not_a_certificate": True,
        },
        "post_pass_limit": {
            "honduras_production_readiness_claimed": False,
            "production_change_automatic": False,
            "separate_honduras_domain_validation_required": True,
        },
    }


def verify_manifest(payload: Mapping[str, Any]) -> bool:
    stable = dict(payload)
    observed = str(stable.pop("stable_payload_sha256", ""))
    return observed == sha256_bytes(canonical_json(stable).encode("utf-8"))


def _verify_development(report: Mapping[str, Any]) -> None:
    if report.get("schema") != DEVELOPMENT_SCHEMA:
        raise RuntimeError("unexpected detector-v4 development schema")
    if report.get("status") != DEVELOPMENT_STATUS:
        raise RuntimeError("detector-v4 development status changed")
    if not verify_stable_payload(report, "stable_payload_sha256"):
        raise RuntimeError("detector-v4 development stable payload failed")
    if report.get("stable_payload_sha256") != DEVELOPMENT_STABLE_SHA256:
        raise RuntimeError("detector-v4 development evidence is not frozen")
    if report.get("selection_rule", {}).get("configuration") != SELECTED_CONFIGURATION:
        raise RuntimeError("detector-v4 selected configuration changed")
    expected = {
        "selected": 993,
        "eligible": 504,
        "baseline_errors": 46,
        "final_accepted": 319,
        "accepted_correct": 319,
        "natural_false_accepts": 0,
        "counterfactual_false_accepts": 0,
    }
    all_metrics = report.get("metrics", {}).get("all", {})
    for key, value in expected.items():
        if int(all_metrics.get(key, -1)) != value:
            raise RuntimeError(f"detector-v4 development metric changed: {key}")
    for split in ("train", "validation", "test"):
        metrics = report.get("metrics", {}).get(split, {})
        if int(metrics.get("natural_false_accepts", -1)) != 0:
            raise RuntimeError(f"detector-v4 has a natural false accept in {split}")
        if int(metrics.get("counterfactual_false_accepts", -1)) != 0:
            raise RuntimeError(f"detector-v4 has a counterfactual false accept in {split}")
    decision = report.get("decision", {})
    if decision.get("internal_generalization_pass") is not True:
        raise RuntimeError("detector-v4 internal generalization did not pass")
    if decision.get("external_certificate") is not False:
        raise RuntimeError("development artifact improperly claims external certification")
    if decision.get("production_ready") is not False:
        raise RuntimeError("development artifact improperly claims production readiness")


def _copy_sources(repository_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    source_root = output_dir / "source"
    for relative in SOURCE_FILES:
        source = repository_root / relative
        if not source.is_file():
            raise RuntimeError(f"candidate source file missing: {relative}")
        destination = source_root / relative
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
    coru_source_seal_path: Path,
    source_commit: str,
    output_dir: Path,
) -> dict[str, Any]:
    source_commit = _full_hex(source_commit, 40)
    if not source_commit:
        raise RuntimeError("candidate source commit is not a full SHA")
    development = json.loads(development_report_path.read_text(encoding="utf-8"))
    _verify_development(development)
    source_seal = json.loads(coru_source_seal_path.read_text(encoding="utf-8"))
    if not verify_coru_source_seal(source_seal):
        raise RuntimeError("CORU source seal stable payload failed")
    if source_seal.get("stable_payload_sha256") != CORU_SOURCE_SEAL_STABLE_SHA256:
        raise RuntimeError("CORU source seal changed")
    if source_seal.get("resolved_revision") != CORU_REVISION:
        raise RuntimeError("CORU source revision changed")
    if source_seal.get("outcomes_opened") is not False:
        raise RuntimeError("CORU outcomes were opened before candidate freeze")
    if int(source_seal.get("images_opened", -1)) != 0:
        raise RuntimeError("CORU images were opened before candidate freeze")
    if int(source_seal.get("annotation_bytes_read", -1)) != 0:
        raise RuntimeError("CORU annotations were opened before candidate freeze")

    model_candidate, model = load_frozen_candidate(model_root)
    if model_candidate.get("candidate_id") != "digit-forest-v3":
        raise RuntimeError("unexpected frozen digit model candidate")
    if model_candidate.get("stable_payload_sha256") != MODEL_CANDIDATE_STABLE_SHA256:
        raise RuntimeError("digit model stable payload changed")
    if model_candidate.get("model", {}).get("sha256") != MODEL_SHA256:
        raise RuntimeError("digit model SHA-256 changed")
    if float(model_candidate.get("inference", {}).get("threshold", -1.0)) != 0.25:
        raise RuntimeError("digit model threshold changed")
    if len(model.estimators_) != 500:
        raise RuntimeError("digit model tree count changed")

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
            raise RuntimeError(f"digit model artifact is missing {name}")
        shutil.copyfile(source, model_dir / name)
    source_records = _copy_sources(repository_root, output_dir)
    requirements_path = output_dir / "requirements.lock"
    requirements_path.write_text("\n".join(REQUIREMENTS) + "\n", encoding="utf-8")
    source_seal_copy = output_dir / "coru_receipt_source_seal_v1.json"
    source_seal_copy.write_text(
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
        "status": "FROZEN_FOR_UNTOUCHED_CORU_EXTERNAL_VALIDATION_ONLY",
        "source_commit": source_commit,
        "source_files": source_records,
        "runtime": {
            "requirements_file": requirements_path.name,
            "requirements_sha256": sha256_file(requirements_path),
            "requirements": list(REQUIREMENTS),
            "deterministic_threads": 1,
        },
        "detector": {
            "configuration": dict(SELECTED_CONFIGURATION),
            "development_artifact_id": DEVELOPMENT_ARTIFACT_ID,
            "development_artifact_zip_sha256": DEVELOPMENT_ARTIFACT_ZIP_SHA256,
            "development_stable_payload_sha256": DEVELOPMENT_STABLE_SHA256,
            "development_evidence_file": development_copy.name,
            "development_evidence_sha256": sha256_file(development_copy),
        },
        "digit_model": {
            "candidate_id": "digit-forest-v3",
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
            "source_seal_file": source_seal_copy.name,
            "source_seal_file_sha256": sha256_file(source_seal_copy),
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
            "coverage_observed": development["metrics"]["all"][
                "coverage_of_selected"
            ],
            "coverage_lower": development["exact_diagnostics"]["all"][
                "coverage_lower"
            ],
            "reduction_lower": development["exact_diagnostics"]["all"][
                "reduction_lower"
            ],
            "internal_only": True,
        },
        "decision": {
            "candidate_frozen_before_coru_outcomes": True,
            "ready_for_one_coru_external_evaluation": True,
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
    manifest_path = output_dir / "frozen_candidate.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"{sha256_file(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    if not verify_manifest(manifest):
        raise RuntimeError("numeric-consensus-v4 candidate did not replay")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--development-report", required=True, type=Path)
    parser.add_argument("--coru-source-seal", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = build_candidate(
        repository_root=args.repository_root,
        model_root=args.model_root,
        development_report_path=args.development_report,
        coru_source_seal_path=args.coru_source_seal,
        source_commit=args.source_commit,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
