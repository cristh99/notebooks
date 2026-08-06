"""Deterministic builder for the preregistered OpenVINO v7 bundle."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_bytes, sha256_file
from .numeric_consensus_policy_v7 import policy_manifest
from .openvino_source_seal_v7 import (
    SOURCE_PATH,
    SOURCE_SHA256,
    SOURCE_SIZE_BYTES,
    verify as verify_source_seal,
)

CANDIDATE_ID = "numeric-consensus-v7-openvino"
PREDECESSOR_V7_ID = "numeric-consensus-v7-cocotext"
PREDECESSOR_V7_STABLE = (
    "33d14875f0d2f9681ced662e452a5f28943ecb65e30a9242663d6a472034da9d"
)
PREDECESSOR_V7_SOURCE_COMMIT = "74bb1fffb71fb4da78995b1417235cf04db34639"
DEVELOPMENT_STABLE = (
    "2e1ac87773d387c27c0d8a8649eb03f39739b8275f3b34a71654a0c81f67cb79"
)
POLICY_SOURCE_SHA256 = (
    "5b37aa3ac9f349e708624e815dab97e2ab1eaaac4a905499de15aa3513862b2d"
)
POLICY_TEST_SHA256 = (
    "826a841298ef0e0a6c252982009f0f446ba354f8901da7dc7e3dda8c136bf2c0"
)
OVERLAYS = (
    "ocr_real_risk_v1/numeric_consensus_policy_v7.py",
    "ocr_real_risk_v1/test_numeric_consensus_policy_v7.py",
    "ocr_real_risk_v1/textocr_v7_development_replay.py",
    "ocr_real_risk_v1/openvino_source_seal_v7.py",
    "ocr_real_risk_v1/openvino_adapter_v7.py",
    "ocr_real_risk_v1/test_openvino_metadata_gate_v7.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v7_openvino.py",
)


def stable(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("stable_payload_sha256", None)
    result["stable_payload_sha256"] = sha256_bytes(
        canonical_json(result).encode("utf-8")
    )
    return result


def verify_stable(payload: Mapping[str, Any]) -> bool:
    return stable(payload)["stable_payload_sha256"] == payload.get(
        "stable_payload_sha256"
    )


def verify_hashes(root: Path) -> None:
    for line in (root / "SHA256SUMS.txt").read_text().splitlines():
        if not line:
            continue
        digest, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"SHA-256 mismatch: {relative}")


def write_hashes(root: Path) -> None:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (root / "SHA256SUMS.txt").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )


def _verify_frozen_policy(repo: Path) -> None:
    policy_source = repo / "ocr_real_risk_v1/numeric_consensus_policy_v7.py"
    policy_test = repo / "ocr_real_risk_v1/test_numeric_consensus_policy_v7.py"
    if sha256_file(policy_source) != POLICY_SOURCE_SHA256:
        raise RuntimeError("frozen v7 policy source changed")
    if sha256_file(policy_test) != POLICY_TEST_SHA256:
        raise RuntimeError("frozen v7 policy tests changed")


def _verify_predecessor(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    verify_hashes(root)
    manifest = json.loads((root / "frozen_candidate.json").read_text())
    if (
        not verify_stable(manifest)
        or manifest.get("candidate_id") != PREDECESSOR_V7_ID
        or manifest.get("stable_payload_sha256") != PREDECESSOR_V7_STABLE
        or manifest.get("source_commit") != PREDECESSOR_V7_SOURCE_COMMIT
        or manifest.get("policy") != policy_manifest()
        or manifest.get("development_stable_payload_sha256")
        != DEVELOPMENT_STABLE
    ):
        raise RuntimeError("COCO-Text v7 predecessor binding mismatch")
    source_root = root / "source"
    if (
        sha256_file(
            source_root / "ocr_real_risk_v1/numeric_consensus_policy_v7.py"
        )
        != POLICY_SOURCE_SHA256
        or sha256_file(
            source_root / "ocr_real_risk_v1/test_numeric_consensus_policy_v7.py"
        )
        != POLICY_TEST_SHA256
    ):
        raise RuntimeError("predecessor policy source does not match freeze")
    development = json.loads(
        (root / "textocr_v7_development_diagnostic.json").read_text()
    )
    if (
        not verify_stable(development)
        or development.get("stable_payload_sha256") != DEVELOPMENT_STABLE
        or development["limitations"]["scientific_credit"] is not False
    ):
        raise RuntimeError("development evidence binding mismatch")
    return manifest, development


def build(
    repo: Path,
    predecessor_v7: Path,
    source_seal_path: Path,
    source_commit: str,
    output: Path,
) -> dict[str, Any]:
    if len(source_commit) != 40:
        raise RuntimeError("full source commit required")
    _verify_frozen_policy(repo)
    predecessor, _development = _verify_predecessor(predecessor_v7)

    source_seal = json.loads(source_seal_path.read_text())
    if not verify_source_seal(source_seal):
        raise RuntimeError("source seal replay failed")
    source = source_seal["source_object"]
    if (
        source_seal.get("outcomes_opened") is not False
        or source.get("path") != SOURCE_PATH
        or source.get("size_bytes") != SOURCE_SIZE_BYTES
        or source.get("sha256") != SOURCE_SHA256
    ):
        raise RuntimeError("OpenVINO source binding mismatch")

    shutil.rmtree(output, ignore_errors=True)
    shutil.copytree(predecessor_v7 / "source", output / "source")
    shutil.copytree(predecessor_v7 / "model", output / "model")
    for relative in OVERLAYS:
        src = repo / relative
        dst = output / "source" / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(source_seal_path, output / "openvino_source_seal_v7.json")
    shutil.copy2(
        predecessor_v7 / "textocr_v7_development_diagnostic.json",
        output / "textocr_v7_development_diagnostic.json",
    )
    shutil.copy2(
        predecessor_v7 / "frozen_candidate.json",
        output / "predecessor_cocotext_v7_candidate.json",
    )

    manifest = stable(
        {
            "schema": "ocr-numeric-consensus-v7-openvino-candidate/1",
            "candidate_id": CANDIDATE_ID,
            "status": "FROZEN_BEFORE_OPENVINO_FOOTER_ROWS_OR_IMAGES",
            "source_commit": source_commit,
            "policy": policy_manifest(),
            "digit_model": {
                **predecessor["digit_model"],
                "reused_without_retraining": True,
            },
            "source_seal_stable_payload_sha256": source_seal[
                "stable_payload_sha256"
            ],
            "development_stable_payload_sha256": DEVELOPMENT_STABLE,
            "predecessor_v7": {
                "candidate_id": PREDECESSOR_V7_ID,
                "stable_payload_sha256": PREDECESSOR_V7_STABLE,
                "source_commit": PREDECESSOR_V7_SOURCE_COMMIT,
                "terminal_scientific_verdict": (
                    "UNKNOWN_NO_IMAGE_OUTCOMES_OPENED"
                ),
                "policy_source_sha256": POLICY_SOURCE_SHA256,
                "policy_test_sha256": POLICY_TEST_SHA256,
                "policy_reused_without_change": True,
            },
            "metadata_power_gate": {
                "stage_a": "texts-only upper bound",
                "stage_b": "exact geometry census only when stage A can pass",
                "minimum_selected": 5000,
                "minimum_projected_verified": 400,
                "development_acceptance_rate": 110 / 4674,
                "image_column_forbidden": True,
                "full_image_download_authorized_in_this_gate": False,
                "license_review_required_before_separate_full_gate": True,
            },
            "quality_gate": predecessor["quality_gate"],
            "speed_gate": predecessor["speed_gate"],
            "independence": {
                "digit_model_training_corpus": "jsdnrs/ICDAR2019-SROIE",
                "retired_or_opened_corpora": [
                    "SROIE",
                    "CORD",
                    "WildReceipt",
                    "TextOCR",
                    "COCO-Text",
                ],
                "openvino_component_previously_opened": False,
                "pixel_overlap_unchecked_until_images_are_authorized": True,
            },
            "license_gate": {
                "mirror_declared": "apache-2.0",
                "upstream_terms_independently_resolved": False,
                "full_image_download_requires_review": True,
            },
            "constraints": predecessor["constraints"],
        }
    )
    (output / "frozen_candidate.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_hashes(output)
    verify(output)
    return manifest


def verify(root: Path) -> dict[str, Any]:
    verify_hashes(root)
    manifest = json.loads((root / "frozen_candidate.json").read_text())
    if not verify_stable(manifest) or manifest.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("OpenVINO v7 bundle verification failed")
    policy = manifest["policy"]
    if policy["annotation_text_length_used_at_inference"]:
        raise RuntimeError("truth-length oracle survived")
    if not policy["forest_threshold_is_effective"]:
        raise RuntimeError("probability threshold is ineffective")
    power_gate = manifest["metadata_power_gate"]
    if not power_gate["image_column_forbidden"]:
        raise RuntimeError("image bytes were not forbidden in power gate")
    if power_gate["full_image_download_authorized_in_this_gate"]:
        raise RuntimeError("metadata gate improperly authorizes image download")
    if manifest["predecessor_v7"]["stable_payload_sha256"] != (
        PREDECESSOR_V7_STABLE
    ):
        raise RuntimeError("predecessor v7 stable payload changed")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--repository-root", type=Path, required=True)
    build_parser.add_argument("--predecessor-v7-root", type=Path, required=True)
    build_parser.add_argument("--source-seal", type=Path, required=True)
    build_parser.add_argument("--source-commit", required=True)
    build_parser.add_argument("--output-dir", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    result = (
        build(
            args.repository_root,
            args.predecessor_v7_root,
            args.source_seal,
            args.source_commit,
            args.output_dir,
        )
        if args.command == "build"
        else verify(args.bundle)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
