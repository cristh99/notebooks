"""Freeze numeric-consensus-v6 before any CORU Receipt annotation is opened.

The candidate binds the schema adapter, archive evaluator, selected detector,
byte-frozen digit forest, post-WildReceipt v6 selective policy, exact gates,
source-seal identity, and complete local import closure. It authorizes only a
cheap `labels.txt` + `test.json` schema census. The 1.06 GB test archive may be
opened only if that frozen census proves explicit transcriptions and adequate
power.
"""
from __future__ import annotations

import argparse
import ast
import json
import shutil
import string
from pathlib import Path
from typing import Any, Mapping

from .cord_detector_crops_v4 import SELECTED_CONFIGURATION
from .core import canonical_json, sha256_bytes, sha256_file
from .coru_receipt_schema_adapter_v6 import (
    ADAPTER_SCHEMA,
    DATASET_ID as CORU_DATASET_ID,
    DATASET_REVISION as CORU_REVISION,
    EXPECTED_LABELS_BYTES,
    EXPECTED_LABELS_SHA256,
    EXPECTED_TEST_ARCHIVE_BYTES,
    EXPECTED_TEST_ARCHIVE_SHA256,
    EXPECTED_TEST_JSON_BYTES,
    EXPECTED_TEST_JSON_SHA256,
)
from .coru_source_seal import verify as verify_coru_source_seal
from .numeric_consensus_candidate_v4 import (
    MODEL_ARTIFACT_ID,
    MODEL_ARTIFACT_ZIP_SHA256,
    MODEL_CANDIDATE_STABLE_SHA256,
    MODEL_SHA256,
)
from .numeric_digit_forest_deterministic import load_frozen_candidate
from .wildreceipt_v6_gate_completion_lab import (
    DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST,
    DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN,
    GATE_POLICY,
)

CANDIDATE_SCHEMA = "ocr-numeric-consensus-v6-coru-receipt-candidate/1"
CANDIDATE_ID = "numeric-consensus-v6-coru-receipt"
PACKAGE_NAME = "ocr_real_risk_v1"
SOURCE_CLOSURE_ALGORITHM = "python-ast-local-import-closure-v1"
SOURCE_ROOTS = (
    "ocr_real_risk_v1/numeric_consensus_candidate_v6_coru.py",
    "ocr_real_risk_v1/coru_receipt_schema_adapter_v6.py",
    "ocr_real_risk_v1/coru_receipt_external_v6.py",
)
CORU_SOURCE_SEAL_STABLE_SHA256 = (
    "d97900ffadd1871f2062bb33f44dd69a10a2bcb298b187e079673037e87edeb3"
)
V6_DEVELOPMENT_RECORD_PATH = (
    "ocr_real_risk_v1/run_records/wildreceipt_v6_gate_completion_lab.json"
)
V6_DEVELOPMENT_RECORD_STABLE_SHA256 = (
    "144182c4147834d4e09f159ba70686ecb2563854b9415b83255342d06ca412dc"
)
V6_GATE_LAB_ARTIFACT_ID = 8931899829
V6_GATE_LAB_ARTIFACT_ZIP_SHA256 = (
    "76da23d700cba9e3bbacbaa9670aad8659383177220ed1053aba6a7d03fa7f03"
)
V6_GATE_LAB_STABLE_SHA256 = (
    "2d31bf83f18d22f22b0f010a8ddec1773ce44d686893f3b2fd7b485598295a69"
)
REQUIREMENTS = (
    "python==3.11",
    "tesseract==5.3.4",
    "Pillow==12.2.0",
    "numpy==2.2.6",
    "opencv-python-headless==4.10.0.84",
    "scikit-learn==1.8.0",
    "scipy==1.17.1",
    "threadpoolctl==3.6.0",
    "joblib==1.5.3",
    "pyarrow==18.1.0",
    "pytesseract==0.3.13",
    "packaging==26.3",
)


def _full_hex(value: object, length: int) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != length or any(
        character not in string.hexdigits for character in raw
    ):
        return ""
    return raw


def _module_source_paths(
    repository_root: Path, module: str
) -> tuple[str, ...]:
    if module != PACKAGE_NAME and not module.startswith(f"{PACKAGE_NAME}."):
        return ()
    parts = module.split(".")
    base = repository_root.joinpath(*parts)
    module_file = base.with_suffix(".py")
    package_init = base / "__init__.py"
    paths: set[str] = set()
    root_init = repository_root / PACKAGE_NAME / "__init__.py"
    if root_init.is_file():
        paths.add(root_init.relative_to(repository_root).as_posix())
    if module_file.is_file():
        paths.add(module_file.relative_to(repository_root).as_posix())
    elif package_init.is_file():
        paths.add(package_init.relative_to(repository_root).as_posix())
    else:
        raise RuntimeError(f"local import cannot be resolved: {module}")
    for index in range(1, len(parts)):
        parent_init = repository_root.joinpath(*parts[:index]) / "__init__.py"
        if parent_init.is_file():
            paths.add(parent_init.relative_to(repository_root).as_posix())
    return tuple(sorted(paths))


def _local_import_modules(relative: str, source: str) -> tuple[str, ...]:
    tree = ast.parse(source, filename=relative)
    module_name = relative.removesuffix(".py").replace("/", ".")
    if module_name.endswith(".__init__"):
        package_parts = module_name.removesuffix(".__init__").split(".")
    else:
        package_parts = module_name.split(".")[:-1]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == PACKAGE_NAME or alias.name.startswith(
                    f"{PACKAGE_NAME}."
                ):
                    imported.add(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            ascend = node.level - 1
            if ascend > len(package_parts):
                raise RuntimeError(
                    f"relative import escapes package in {relative}: "
                    f"level={node.level}"
                )
            base_parts = package_parts[: len(package_parts) - ascend]
            if node.module:
                imported.add(
                    ".".join([*base_parts, *node.module.split(".")])
                )
            else:
                for alias in node.names:
                    imported.add(".".join([*base_parts, alias.name]))
        elif node.module == PACKAGE_NAME or str(node.module or "").startswith(
            f"{PACKAGE_NAME}."
        ):
            imported.add(str(node.module))
    return tuple(sorted(imported))


def discover_source_files(repository_root: Path) -> tuple[str, ...]:
    repository_root = repository_root.resolve()
    discovered: set[str] = {f"{PACKAGE_NAME}/__init__.py", *SOURCE_ROOTS}
    pending = list(sorted(discovered))
    parsed: set[str] = set()
    while pending:
        relative = pending.pop(0)
        if relative in parsed:
            continue
        source_path = repository_root / relative
        if not source_path.is_file():
            raise RuntimeError(f"candidate source file missing: {relative}")
        parsed.add(relative)
        source = source_path.read_text(encoding="utf-8")
        for module in _local_import_modules(relative, source):
            for imported_path in _module_source_paths(
                repository_root, module
            ):
                if imported_path not in discovered:
                    discovered.add(imported_path)
                    pending.append(imported_path)
        pending.sort()
    return tuple(sorted(discovered))


def verify_manifest(payload: Mapping[str, Any]) -> bool:
    stable = dict(payload)
    observed = str(stable.pop("stable_payload_sha256", ""))
    return observed == sha256_bytes(canonical_json(stable).encode("utf-8"))


def _verify_record(payload: Mapping[str, Any]) -> None:
    stable = dict(payload)
    observed = str(stable.pop("record_stable_payload_sha256", ""))
    expected = sha256_bytes(canonical_json(stable).encode("utf-8"))
    if observed != expected or observed != V6_DEVELOPMENT_RECORD_STABLE_SHA256:
        raise RuntimeError("v6 development record stable replay failed")
    if payload.get("status") != (
        "POST_OUTCOME_DEVELOPMENT_AGGREGATE_GATES_PASS_STABILITY_FAIL"
    ):
        raise RuntimeError("unexpected v6 development status")
    if payload.get("lab_stable_payload_sha256") != V6_GATE_LAB_STABLE_SHA256:
        raise RuntimeError("v6 gate-lab stable payload changed")
    exact = payload.get("exact_results", {}).get("all", {})
    expected_counts = {
        "selected": 1720,
        "baseline_eligible": 680,
        "baseline_false": 91,
        "accepted": 472,
        "accepted_false": 0,
        "counterfactual_false": 0,
    }
    for field, value in expected_counts.items():
        if int(exact.get(field, -1)) != value:
            raise RuntimeError(f"v6 development metric changed: {field}")
    if float(exact.get("coverage_lower", 0.0)) <= 0.25:
        raise RuntimeError("v6 development coverage gate did not pass")
    if float(exact.get("reduction_lower", 0.0)) <= 10.0:
        raise RuntimeError("v6 development 10x gate did not pass")
    decision = payload.get("decision", {})
    if decision.get("aggregate_development_10x_gate_pass") is not True:
        raise RuntimeError("v6 aggregate development gate did not pass")
    if decision.get("leave_one_shard_out_stability_pass") is not False:
        raise RuntimeError("v6 stability status changed")
    if decision.get("external_certificate_claimed") is not False:
        raise RuntimeError("v6 development improperly claims external evidence")
    if decision.get("candidate_ready_to_freeze") is not False:
        raise RuntimeError("v6 record improperly self-authorizes freezing")
    policy = payload.get("policy", {})
    if policy.get("thresholds_selected_after_wildreceipt_outcomes") is not True:
        raise RuntimeError("v6 threshold provenance was not disclosed")
    if policy.get("uses_truth_at_inference") is not False:
        raise RuntimeError("v6 policy claims truth at inference")
    if policy.get("uses_annotation_geometry_at_inference") is not False:
        raise RuntimeError("v6 policy claims annotation geometry at inference")


def external_protocol() -> dict[str, Any]:
    return {
        "protocol_id": "coru-receipt-v6-schema-first-numeric-v1",
        "dataset": CORU_DATASET_ID,
        "component": "Receipt",
        "revision": CORU_REVISION,
        "schema_files": {
            "labels": {
                "path": "Receipt/labels.txt",
                "sha256": EXPECTED_LABELS_SHA256,
                "size_bytes": EXPECTED_LABELS_BYTES,
            },
            "test_json": {
                "path": "Receipt/test.json",
                "sha256": EXPECTED_TEST_JSON_SHA256,
                "size_bytes": EXPECTED_TEST_JSON_BYTES,
            },
        },
        "test_archive": {
            "path": "Receipt/test.zip",
            "sha256": EXPECTED_TEST_ARCHIVE_SHA256,
            "size_bytes": EXPECTED_TEST_ARCHIVE_BYTES,
            "download_only_after_schema_and_power_gate": True,
        },
        "schema_adapter": {
            "schema": ADAPTER_SCHEMA,
            "accepted_format": "COCO images/annotations/categories",
            "requires_explicit_transcription_field": True,
            "category_name_is_not_ocr_truth": True,
            "unknown_or_ambiguous_schema": "terminal_no_ocr",
            "one_numeric_risk_unit_per_image": True,
            "selection_completed_before_ocr": True,
        },
        "risk_unit": (
            "one SHA-256-selected explicit 4-12 digit transcription per "
            "physical receipt image"
        ),
        "selection": {
            "uses_ocr": False,
            "uses_candidate_output": False,
            "normalization": (
                "ASCII digits after separator and currency removal; standalone "
                "years, repeated-digit junk, letters, and non-ASCII digits excluded"
            ),
            "deduplicate_after_archive_opening": "decoded image SHA-256",
        },
        "baseline": {
            "engine": "Tesseract 5.3.4",
            "language": "eng",
            "oem": 1,
            "psm": 3,
            "input": "complete original receipt image",
            "annotation_geometry_used_only_for_scoring": True,
        },
        "detector": {
            "configuration": dict(SELECTED_CONFIGURATION),
            "input": "complete original receipt image",
        },
        "selective_policy": {
            "name": GATE_POLICY.name,
            "base_union": (
                "detector==forest with no equal-length conflict OR "
                "forest==gray==autocontrast"
            ),
            "branch_1": (
                "detector==gray==autocontrast and detector confidence>91.0"
            ),
            "branch_1_threshold": (
                DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN
            ),
            "branch_2": (
                "detector==forest==gray and detector confidence>=93.0"
            ),
            "branch_2_threshold": (
                DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST
            ),
            "conflicting_outputs": "abstain",
            "thresholds_selected_on_opened_wildreceipt": True,
            "frozen_before_coru_schema_opening": True,
            "truth_available_at_inference": False,
            "annotation_geometry_available_at_inference": False,
        },
        "digit_forest": {
            "candidate_id": "digit-forest-v3",
            "threshold": 0.25,
            "tree_count": 500,
        },
        "counterfactual": {
            "equal_length_single_digit_mutation": True,
            "gate": "final accepted output must not equal mutation",
            "generated_before_candidate_inference": True,
        },
        "exact_gates": {
            "family_alpha": 0.05,
            "alpha_per_leg_bonferroni": 0.0125,
            "target_error_reduction": 10.0,
            "minimum_selected": 3000,
            "minimum_accepted": 900,
            "minimum_coverage_lower": 0.25,
            "counterfactual_maximum_upper": 0.01,
            "baseline_errors_must_be_positive": True,
            "candidate_upper_must_not_exceed_baseline_lower_divided_by_10": True,
        },
        "power_gate": {
            "wildreceipt_development_acceptance_rate": 472 / 1720,
            "expected_test_receipts_from_preexisting_protocol": 3700,
            "projected_accepts_if_rate_holds": 3700 * 472 / 1720,
            "archive_download_requires_selected_at_least": 3000,
            "archive_download_requires_projected_accepts_at_least": 900,
            "planning_only_not_evidence": True,
        },
        "runtime": {
            "source_closure_algorithm": SOURCE_CLOSURE_ALGORITHM,
            "neutral_workdir_import_required": True,
            "deterministic_threads": 1,
            "image_archive_partitions_if_gate_passes": 12,
        },
        "claim_limits": {
            "schema_census_is_not_external_validation": True,
            "external_certificate_claimed": False,
            "honduras_production_readiness_claimed": False,
            "production_change_automatic": False,
        },
    }


def _copy_sources(
    repository_root: Path, output_dir: Path
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    source_files = discover_source_files(repository_root)
    records: list[dict[str, Any]] = []
    source_root = output_dir / "source"
    for relative in source_files:
        source = repository_root / relative
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
    return records, source_files


def build_candidate(
    *,
    repository_root: Path,
    model_root: Path,
    development_record_path: Path,
    source_seal_path: Path,
    source_commit: str,
    output_dir: Path,
) -> dict[str, Any]:
    source_commit = _full_hex(source_commit, 40)
    if not source_commit:
        raise RuntimeError("candidate source commit is not a full SHA")
    development = json.loads(
        development_record_path.read_text(encoding="utf-8")
    )
    _verify_record(development)
    source_seal = json.loads(source_seal_path.read_text(encoding="utf-8"))
    if not verify_coru_source_seal(source_seal):
        raise RuntimeError("CORU source seal stable replay failed")
    if source_seal.get("stable_payload_sha256") != CORU_SOURCE_SEAL_STABLE_SHA256:
        raise RuntimeError("CORU source seal changed")
    if source_seal.get("resolved_revision") != CORU_REVISION:
        raise RuntimeError("CORU source revision changed")
    for field in (
        "archives_downloaded",
        "annotation_bytes_read",
        "labels_read",
        "dataset_rows_read",
        "images_opened",
    ):
        if int(source_seal.get(field, -1)) != 0:
            raise RuntimeError(f"CORU source was opened before v6 freeze: {field}")
    if source_seal.get("ocr_executed") is not False:
        raise RuntimeError("CORU OCR ran before v6 freeze")
    if source_seal.get("outcomes_opened") is not False:
        raise RuntimeError("CORU outcomes opened before v6 freeze")

    model_candidate, model = load_frozen_candidate(model_root)
    if model_candidate.get("candidate_id") != "digit-forest-v3":
        raise RuntimeError("unexpected frozen digit model")
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
            raise RuntimeError(f"digit model artifact missing: {name}")
        shutil.copyfile(source, model_dir / name)

    source_records, source_files = _copy_sources(
        repository_root, output_dir
    )
    requirements_path = output_dir / "requirements.lock"
    requirements_path.write_text(
        "\n".join(REQUIREMENTS) + "\n", encoding="utf-8"
    )
    seal_copy = output_dir / "coru_receipt_source_seal_v1.json"
    seal_copy.write_text(
        json.dumps(source_seal, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    development_copy = output_dir / "wildreceipt_v6_development_record.json"
    development_copy.write_text(
        json.dumps(development, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    protocol = external_protocol()
    source_file_set_sha256 = sha256_bytes(
        canonical_json(list(source_files)).encode("utf-8")
    )
    manifest: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "status": "FROZEN_BEFORE_CORU_RECEIPT_SCHEMA_OR_IMAGE_OPENING",
        "source_commit": source_commit,
        "source_files": source_records,
        "runtime": {
            "requirements": list(REQUIREMENTS),
            "requirements_file": requirements_path.name,
            "requirements_sha256": sha256_file(requirements_path),
            "source_closure_algorithm": SOURCE_CLOSURE_ALGORITHM,
            "source_file_count": len(source_files),
            "source_file_set_sha256": source_file_set_sha256,
            "deterministic_threads": 1,
        },
        "detector": {
            "configuration": dict(SELECTED_CONFIGURATION),
        },
        "selective_policy": {
            "name": GATE_POLICY.name,
            "threshold_1": DETECTOR_GUARD_CONFIDENCE_STRICTLY_GREATER_THAN,
            "threshold_2": DETECTOR_FOREST_GRAY_CONFIDENCE_AT_LEAST,
            "development_artifact_id": V6_GATE_LAB_ARTIFACT_ID,
            "development_artifact_zip_sha256": V6_GATE_LAB_ARTIFACT_ZIP_SHA256,
            "development_lab_stable_payload_sha256": V6_GATE_LAB_STABLE_SHA256,
            "development_record_file": development_copy.name,
            "development_record_file_sha256": sha256_file(development_copy),
            "development_record_stable_payload_sha256": (
                V6_DEVELOPMENT_RECORD_STABLE_SHA256
            ),
            "thresholds_selected_after_wildreceipt_outcomes": True,
            "frozen_before_coru_schema_opening": True,
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
            "source_seal_file": seal_copy.name,
            "source_seal_file_sha256": sha256_file(seal_copy),
            "source_seal_stable_payload_sha256": source_seal[
                "stable_payload_sha256"
            ],
            "schema_or_outcomes_opened_before_freeze": False,
        },
        "external_protocol": protocol,
        "development_evidence": {
            "wildreceipt_selected": 1720,
            "wildreceipt_accepted": 472,
            "wildreceipt_accepted_false": 0,
            "wildreceipt_counterfactual_false": 0,
            "wildreceipt_coverage_lower": development["exact_results"][
                "all"
            ]["coverage_lower"],
            "wildreceipt_reduction_lower": development["exact_results"][
                "all"
            ]["reduction_lower"],
            "leave_one_shard_out_stability_pass": False,
            "post_outcome_internal_only": True,
        },
        "decision": {
            "candidate_frozen_before_coru_schema_opening": True,
            "ready_for_coru_schema_and_power_census": True,
            "ready_to_open_coru_test_archive": False,
            "archive_open_requires_frozen_census_pass": True,
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
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
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
        raise RuntimeError("CORU v6 candidate stable replay failed")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--development-record", required=True, type=Path)
    parser.add_argument("--source-seal", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = build_candidate(
        repository_root=args.repository_root,
        model_root=args.model_root,
        development_record_path=args.development_record,
        source_seal_path=args.source_seal,
        source_commit=args.source_commit,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
