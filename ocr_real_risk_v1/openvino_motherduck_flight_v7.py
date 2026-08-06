"""Portable one-shot MotherDuck executor for the frozen OpenVINO v7 gate.

This file is infrastructure only. It downloads the exact scientific modules
from one frozen Git commit, verifies their Git-blob and SHA-256 identities,
materializes an isolated package, executes the metadata-only gate once, and
prints compact cryptographic receipts. It never selects image bytes, runs OCR,
uses candidate inference, writes MotherDuck data, or authorizes a later gate.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

FROZEN_SOURCE_COMMIT = "fa20f6d210fa8be7272178b1f152e38b2d583637"
REPOSITORY = "cristh99/notebooks"
RAW_BASE = (
    f"https://raw.githubusercontent.com/{REPOSITORY}/"
    f"{FROZEN_SOURCE_COMMIT}/ocr_real_risk_v1"
)
SOURCE_FILES: dict[str, dict[str, object]] = {
    "core.py": {
        "git_blob_sha1": "c7cfe8320c7864cc7c63389cad8e832a1b9fc5d7",
        "sha256": "23593784005eccf9136077d29c29f5f934b7650ab60924a83a2458db932718d0",
        "bytes": 11262,
    },
    "textocr_adapter_v6.py": {
        "git_blob_sha1": "c55e4724dd1b9af3a02128424d63107f2504e4ea",
        "sha256": "dc17474c2bdcfb56fd1435b5f90182cd38bdae69328af4de00ed0e5c612b2033",
        "bytes": 17570,
    },
    "openvino_source_seal_v7.py": {
        "git_blob_sha1": "79be5dae1e67b9469ea1200d91e8dc46628c42e7",
        "sha256": "681d61c799c5bc8cbd643ba30113f9576f4040658af00357d9d9f9a4f42287b0",
        "bytes": 6221,
    },
    "openvino_adapter_v7.py": {
        "git_blob_sha1": "a4f790a9e2825be24f552f6223d3027bd15f461e",
        "sha256": "744102028990c94363c9b4138bb805a8f9d8bf2000e476a8283e6443869cb903",
        "bytes": 14945,
    },
    "openvino_terminal_v7.py": {
        "git_blob_sha1": "438fa95eed8511c19ca2b92d487734b56bea8616",
        "sha256": "42cddd66aa9d3f52b6deac28b6298c00da179612e5b8a93a4e4f6d6e76d3573f",
        "bytes": 11173,
    },
}
SOURCE_SEAL_STABLE_SHA256 = (
    "3c1192c6a0dc420c4b9de66e4c5f0a2a916339286aa6f28b2e39ba28531ee089"
)
CANDIDATE_STABLE_SHA256 = (
    "160a3e79c6075a6741a1a6365b0c833115bfc6e156176cb4cb5744b1189119cd"
)
EXPECTED_SOURCE_ROWS = 207_790
REQUIRED_SELECTED = 16_997

CANDIDATE_JSON = r'''{
  "candidate_id": "numeric-consensus-v7-openvino",
  "constraints": {
    "external_spend_usd": 0,
    "gcloud_used": false,
    "gpu_used": false,
    "paid_api_used": false,
    "production_modified": false
  },
  "development_stable_payload_sha256": "2e1ac87773d387c27c0d8a8649eb03f39739b8275f3b34a71654a0c81f67cb79",
  "digit_model": {
    "artifact_id": 8917522937,
    "artifact_zip_sha256": "080b0efd4b91a180a1a5c6acd767d72e0a8f286718e64eb90d8ec9d370d2dc17",
    "candidate_id": "digit-forest-v3",
    "candidate_stable_payload_sha256": "0f88d94af81e0f7921e654e452059d2075b07ee35bcffd83dd8b02ebdd9e93a1",
    "model_file": "model/digit_forest.joblib",
    "model_sha256": "53229915331c2bbea2454f9e7cb5768a26e9edb30de750747f4397f1ff4cf92c",
    "reused_without_retraining": true,
    "threshold": 0.25,
    "tree_count": 500
  },
  "independence": {
    "digit_model_training_corpus": "jsdnrs/ICDAR2019-SROIE",
    "openvino_component_previously_opened": false,
    "pixel_overlap_unchecked_until_images_are_authorized": true,
    "retired_or_opened_corpora": [
      "SROIE",
      "CORD",
      "WildReceipt",
      "TextOCR",
      "COCO-Text"
    ]
  },
  "license_gate": {
    "full_image_download_requires_review": true,
    "mirror_declared": "apache-2.0",
    "upstream_terms_independently_resolved": false
  },
  "metadata_power_gate": {
    "development_acceptance_rate": 0.0235344458707745,
    "expected_source_rows": 207790,
    "full_image_download_authorized_in_this_gate": false,
    "image_column_forbidden": true,
    "license_review_required_before_separate_full_gate": true,
    "minimum_projected_verified": 400,
    "minimum_selected": 5000,
    "stage_a": "texts-only upper bound",
    "stage_b": "exact geometry census only when stage A can pass"
  },
  "policy": {
    "alternate_output_correction": false,
    "annotation_text_length_used_at_inference": false,
    "equal_length_detector_conflicts": "abstain",
    "forest_minimum_mean_probability": 0.25,
    "forest_threshold_is_effective": true,
    "ground_truth_available_at_inference": false,
    "minimum_independent_crop_guards": 1,
    "policy_id": "v7-claim-verifier-prob25-guard1-no-conflict",
    "schema": "ocr-numeric-consensus-policy/7",
    "semantics": "verify_observed_claim_or_abstain",
    "terminal_outputs": [
      "verified_claim",
      "abstain"
    ]
  },
  "predecessor_v7": {
    "candidate_id": "numeric-consensus-v7-cocotext",
    "policy_reused_without_change": true,
    "policy_source_sha256": "5b37aa3ac9f349e708624e815dab97e2ab1eaaac4a905499de15aa3513862b2d",
    "policy_test_sha256": "826a841298ef0e0a6c252982009f0f446ba354f8901da7dc7e3dda8c136bf2c0",
    "source_commit": "74bb1fffb71fb4da78995b1417235cf04db34639",
    "stable_payload_sha256": "33d14875f0d2f9681ced662e452a5f28943ecb65e30a9242663d6a472034da9d",
    "terminal_scientific_verdict": "UNKNOWN_NO_IMAGE_OUTCOMES_OPENED"
  },
  "quality_gate": {
    "counterfactual_maximum_upper": 0.01,
    "macrofolds": 4,
    "minimum_coverage_lower": 0.25,
    "minimum_macrofold_pass_fraction": 0.75,
    "target_error_reduction": 10.0
  },
  "schema": "ocr-numeric-consensus-v7-openvino-candidate/1",
  "source_commit": "fa20f6d210fa8be7272178b1f152e38b2d583637",
  "source_seal_stable_payload_sha256": "3c1192c6a0dc420c4b9de66e4c5f0a2a916339286aa6f28b2e39ba28531ee089",
  "speed_gate": {
    "claim_authorized": false,
    "measure_candidate_and_baseline_wall_seconds": true,
    "tenfold_claim_requires_ratio_at_most": 0.1
  },
  "stable_payload_sha256": "160a3e79c6075a6741a1a6365b0c833115bfc6e156176cb4cb5744b1189119cd",
  "status": "FROZEN_BEFORE_OPENVINO_FOOTER_ROWS_OR_IMAGES"
}'''

STABLE_PAYLOAD_STUB = '''from __future__ import annotations\n\nfrom typing import Any, Mapping\n\nfrom .core import canonical_json, sha256_bytes\n\n\ndef stable_payload(value: Mapping[str, Any], hash_field: str) -> dict[str, Any]:\n    result = dict(value)\n    result.pop(hash_field, None)\n    result[hash_field] = sha256_bytes(canonical_json(result).encode("utf-8"))\n    return result\n'''


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_blob_sha1(value: bytes) -> str:
    prefix = f"blob {len(value)}\0".encode("ascii")
    return hashlib.sha1(prefix + value).hexdigest()  # nosec B324: Git identity


def verify_stable(payload: Mapping[str, Any]) -> bool:
    value = dict(payload)
    observed = str(value.pop("stable_payload_sha256", ""))
    return observed == sha256_bytes(canonical_json(value).encode("utf-8"))


def frozen_candidate() -> dict[str, Any]:
    candidate = json.loads(CANDIDATE_JSON)
    if not verify_stable(candidate):
        raise RuntimeError("portable candidate stable replay failed")
    if candidate["stable_payload_sha256"] != CANDIDATE_STABLE_SHA256:
        raise RuntimeError("portable candidate stable binding changed")
    if candidate["source_commit"] != FROZEN_SOURCE_COMMIT:
        raise RuntimeError("portable candidate source commit changed")
    if candidate["metadata_power_gate"]["expected_source_rows"] != (
        EXPECTED_SOURCE_ROWS
    ):
        raise RuntimeError("portable candidate source row count changed")
    if candidate["policy"]["annotation_text_length_used_at_inference"]:
        raise RuntimeError("truth-length oracle survived")
    if not candidate["policy"]["forest_threshold_is_effective"]:
        raise RuntimeError("forest threshold became ineffective")
    return candidate


def _fetch(url: str, *, timeout: float = 120.0) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "OCR-OpenVINO-V7-MotherDuck-Flight/1",
        },
    )
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == 5:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"download failed: {url}") from last_error


def materialize_frozen_package(root: Path) -> dict[str, Any]:
    package = root / "ocr_real_risk_v1"
    shutil.rmtree(root, ignore_errors=True)
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    observed: dict[str, Any] = {}
    for name, expected in SOURCE_FILES.items():
        raw = _fetch(f"{RAW_BASE}/{name}")
        digest = sha256_bytes(raw)
        blob = git_blob_sha1(raw)
        if len(raw) != expected["bytes"]:
            raise RuntimeError(f"frozen source byte count mismatch: {name}")
        if digest != expected["sha256"]:
            raise RuntimeError(f"frozen source SHA-256 mismatch: {name}")
        if blob != expected["git_blob_sha1"]:
            raise RuntimeError(f"frozen source Git blob mismatch: {name}")
        (package / name).write_bytes(raw)
        observed[name] = {
            "bytes": len(raw),
            "sha256": digest,
            "git_blob_sha1": blob,
        }
    stub = STABLE_PAYLOAD_STUB.encode("utf-8")
    (package / "sroie_natural_holdout.py").write_bytes(stub)
    observed["sroie_natural_holdout.py"] = {
        "role": "inert import stub exposing only exact stable_payload",
        "bytes": len(stub),
        "sha256": sha256_bytes(stub),
        "git_blob_sha1": git_blob_sha1(stub),
    }
    return observed


def load_frozen_modules(root: Path) -> tuple[Any, Any, Any, Any]:
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    textocr = importlib.import_module("ocr_real_risk_v1.textocr_adapter_v6")
    source_seal = importlib.import_module(
        "ocr_real_risk_v1.openvino_source_seal_v7"
    )
    adapter = importlib.import_module("ocr_real_risk_v1.openvino_adapter_v7")
    terminal = importlib.import_module("ocr_real_risk_v1.openvino_terminal_v7")
    for function_name in (
        "canonical_numeric_text",
        "resolve_bbox",
        "selection_rank",
        "select_numeric_annotation",
        "census_rows",
    ):
        function = getattr(textocr, function_name)
        if "stable_payload" in function.__code__.co_names:
            raise RuntimeError(
                f"inert stable_payload stub reached scientific path: {function_name}"
            )
    if adapter.EXPECTED_ROW_COUNT != EXPECTED_SOURCE_ROWS:
        raise RuntimeError("frozen adapter row count changed")
    if adapter.REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS != REQUIRED_SELECTED:
        raise RuntimeError("frozen adapter power boundary changed")
    return textocr, source_seal, adapter, terminal


def compact_census(report: Mapping[str, Any]) -> dict[str, Any]:
    compact = dict(report)
    exact = compact.get("exact_census")
    if isinstance(exact, Mapping):
        exact_compact = dict(exact)
        exact_compact.pop("records", None)
        compact["exact_census"] = exact_compact
    return compact


def emit_json_artifact(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    encoded = base64.b64encode(compressed).decode("ascii")
    print(f"BEGIN_{name}_GZIP_BASE64")
    print(encoded)
    print(f"END_{name}_GZIP_BASE64")
    return {
        "name": name,
        "raw_bytes": len(raw),
        "raw_sha256": sha256_bytes(raw),
        "gzip_bytes": len(compressed),
        "gzip_sha256": sha256_bytes(compressed),
        "base64_chars": len(encoded),
    }


def main() -> None:
    started = time.time()
    if os.environ.get("MOTHERDUCK_FLIGHTS_RUN") is None:
        print("warning: MOTHERDUCK_FLIGHTS_RUN is absent", flush=True)
    candidate = frozen_candidate()
    work = Path(tempfile.mkdtemp(prefix="openvino-v7-frozen-"))
    source_receipt = materialize_frozen_package(work)
    _textocr, source_seal_module, adapter, terminal_module = (
        load_frozen_modules(work)
    )

    source_seal = source_seal_module.seal(source_seal_module.fetch_metadata())
    if not source_seal_module.verify(source_seal):
        raise RuntimeError("live source seal replay failed")
    if source_seal["stable_payload_sha256"] != SOURCE_SEAL_STABLE_SHA256:
        raise RuntimeError("live source seal does not match frozen candidate")
    if source_seal["source_object"]["declared_rows"] != EXPECTED_SOURCE_ROWS:
        raise RuntimeError("live source declared row count changed")

    preflight = {
        "schema": "ocr-openvino-v7-motherduck-preflight/1",
        "frozen_source_commit": FROZEN_SOURCE_COMMIT,
        "candidate_stable_payload_sha256": CANDIDATE_STABLE_SHA256,
        "source_seal_stable_payload_sha256": SOURCE_SEAL_STABLE_SHA256,
        "expected_source_rows": EXPECTED_SOURCE_ROWS,
        "required_selected_for_projected_verified": REQUIRED_SELECTED,
        "scientific_modules": source_receipt,
        "image_column_authorized": False,
        "ocr_authorized": False,
        "candidate_inference_authorized": False,
        "external_spend_usd": 0,
        "gcloud_used": False,
        "gpu_used": False,
        "paid_api_used": False,
        "production_modified": False,
    }
    preflight["stable_payload_sha256"] = sha256_bytes(
        canonical_json(preflight).encode("utf-8")
    )
    print(
        "OPENVINO_V7_PREFLIGHT="
        + json.dumps(preflight, ensure_ascii=False, sort_keys=True),
        flush=True,
    )

    census_started = time.time()
    census = adapter.remote_census(
        source_url=adapter.SOURCE_URL,
        candidate_stable_payload_sha256=CANDIDATE_STABLE_SHA256,
        candidate_source_commit=FROZEN_SOURCE_COMMIT,
    )
    census_seconds = time.time() - census_started
    census_raw = (
        json.dumps(census, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    terminal = terminal_module.adjudicate(
        census,
        candidate,
        source_seal,
        source_commit=FROZEN_SOURCE_COMMIT,
        census_file_sha256=sha256_bytes(census_raw),
    )

    artifacts = [
        emit_json_artifact("OPENVINO_V7_SOURCE_SEAL", source_seal),
        emit_json_artifact("OPENVINO_V7_CANDIDATE", candidate),
        emit_json_artifact("OPENVINO_V7_COMPACT_CENSUS", compact_census(census)),
        emit_json_artifact("OPENVINO_V7_TERMINAL", terminal),
    ]
    summary = {
        "schema": "ocr-openvino-v7-motherduck-run/1",
        "status": terminal["status"],
        "scientific_verdict": terminal["scientific_verdict"],
        "metadata_power_pass": terminal["metadata_power_pass"],
        "separate_full_gate_eligible_after_license_review": terminal[
            "separate_full_gate_eligible_after_license_review"
        ],
        "full_image_download_authorized": terminal[
            "full_image_download_authorized"
        ],
        "ocr_authorized": terminal["ocr_authorized"],
        "rows_scanned": terminal["rows_scanned"],
        "selected_or_upper_bound": terminal["selected_or_upper_bound"],
        "projected_verified_claims": terminal[
            "projected_verified_claims"
        ],
        "candidate_stable_payload_sha256": CANDIDATE_STABLE_SHA256,
        "source_seal_stable_payload_sha256": SOURCE_SEAL_STABLE_SHA256,
        "census_stable_payload_sha256": census[
            "stable_payload_sha256"
        ],
        "census_file_sha256": terminal["census_file_sha256"],
        "terminal_stable_payload_sha256": terminal[
            "stable_payload_sha256"
        ],
        "selected_record_set_sha256": (
            census["exact_census"]["selected_record_set_sha256"]
            if isinstance(census.get("exact_census"), Mapping)
            else None
        ),
        "census_wall_seconds": census_seconds,
        "total_wall_seconds": time.time() - started,
        "artifacts": artifacts,
        "external_spend_usd": 0,
        "gcloud_used": False,
        "gpu_used": False,
        "paid_api_used": False,
        "production_modified": False,
    }
    summary["stable_payload_sha256"] = sha256_bytes(
        canonical_json(summary).encode("utf-8")
    )
    print(
        "OPENVINO_V7_TERMINAL_SUMMARY="
        + json.dumps(summary, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
