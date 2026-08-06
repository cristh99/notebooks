"""Deterministic LSVT source binding for the frozen numeric-consensus v7 policy.

The prior COCO-Text v7 candidate is the byte-frozen behavioral authority. This
builder changes only source binding, license constraints, and source-adapter
files; policy, model, thresholds, quality gates, and speed gates are unchanged.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_bytes, sha256_file
from .lsvt_source_seal_v7 import verify as verify_source_seal

CANDIDATE_ID = "numeric-consensus-v7-lsvt"
PRIOR_CANDIDATE_ID = "numeric-consensus-v7-cocotext"
PRIOR_CANDIDATE_STABLE = "33d14875f0d2f9681ced662e452a5f28943ecb65e30a9242663d6a472034da9d"
PRIOR_ARTIFACT_ID = 8974218596
PRIOR_ARTIFACT_ZIP_SHA256 = "7a0671b214d02276ae0e14689915fbd2800dddf95847317b7fb1745e9e6b3361"
POLICY_SOURCE_SHA256 = "5b37aa3ac9f349e708624e815dab97e2ab1eaaac4a905499de15aa3513862b2d"
LSVT_PATH = "data/LSVT-00000-of-00001.parquet"
LSVT_SIZE = 8_979_134_697
LSVT_SHA256 = "44d4e6822060bbd3c11b933675d91ac7da4e944645bee7a080529f0232823c8b"
OVERLAYS = (
    "ocr_real_risk_v1/lsvt_source_seal_v7.py",
    "ocr_real_risk_v1/lsvt_adapter_v7.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v7_lsvt.py",
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
    for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
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


def build(
    *,
    repository_root: Path,
    prior_candidate_root: Path,
    source_seal_path: Path,
    source_commit: str,
    output_dir: Path,
) -> dict[str, Any]:
    if len(source_commit) != 40:
        raise RuntimeError("full source commit required")
    verify_hashes(prior_candidate_root)
    prior = json.loads(
        (prior_candidate_root / "frozen_candidate.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        not verify_stable(prior)
        or prior.get("candidate_id") != PRIOR_CANDIDATE_ID
        or prior.get("stable_payload_sha256") != PRIOR_CANDIDATE_STABLE
    ):
        raise RuntimeError("prior v7 candidate binding mismatch")
    prior_policy = prior_candidate_root / (
        "source/ocr_real_risk_v1/numeric_consensus_policy_v7.py"
    )
    current_policy = repository_root / (
        "ocr_real_risk_v1/numeric_consensus_policy_v7.py"
    )
    if (
        sha256_file(prior_policy) != POLICY_SOURCE_SHA256
        or sha256_file(current_policy) != POLICY_SOURCE_SHA256
    ):
        raise RuntimeError("v7 policy changed after COCO-Text terminal gate")

    seal = json.loads(source_seal_path.read_text(encoding="utf-8"))
    if not verify_source_seal(seal):
        raise RuntimeError("LSVT source seal stable replay failed")
    source = seal["source_object"]
    if (
        seal.get("outcomes_opened") is not False
        or source.get("path") != LSVT_PATH
        or source.get("size_bytes") != LSVT_SIZE
        or source.get("sha256") != LSVT_SHA256
    ):
        raise RuntimeError("LSVT source identity mismatch")

    shutil.rmtree(output_dir, ignore_errors=True)
    shutil.copytree(prior_candidate_root, output_dir)
    (output_dir / "cocotext_source_seal_v7.json").unlink(missing_ok=True)
    shutil.copy2(source_seal_path, output_dir / "lsvt_source_seal_v7.json")
    for relative in OVERLAYS:
        source_file = repository_root / relative
        target = output_dir / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target)

    manifest = stable(
        {
            "schema": "ocr-numeric-consensus-v7-lsvt-candidate/1",
            "candidate_id": CANDIDATE_ID,
            "status": "FROZEN_BEFORE_LSVT_FOOTER_ROWS_OR_IMAGES",
            "source_commit": source_commit,
            "policy": prior["policy"],
            "digit_model": prior["digit_model"],
            "development_stable_payload_sha256": prior[
                "development_stable_payload_sha256"
            ],
            "prior_candidate_binding": {
                "candidate_id": PRIOR_CANDIDATE_ID,
                "stable_payload_sha256": PRIOR_CANDIDATE_STABLE,
                "artifact_id": PRIOR_ARTIFACT_ID,
                "artifact_zip_sha256": PRIOR_ARTIFACT_ZIP_SHA256,
                "policy_source_sha256": POLICY_SOURCE_SHA256,
                "behavioral_changes": [],
                "source_binding_only": True,
            },
            "source_binding": {
                "dataset_id": seal["dataset_id"],
                "component": seal["component"],
                "resolved_revision": seal["resolved_revision"],
                "source_object": source,
                "source_seal_stable_payload_sha256": seal[
                    "stable_payload_sha256"
                ],
                "upstream_license": "CC-BY-NC-ND-3.0",
                "commercial_use_forbidden": True,
                "source_images_must_not_be_redistributed": True,
            },
            "full_download_gate": prior["full_download_gate"],
            "quality_gate": prior["quality_gate"],
            "speed_gate": prior["speed_gate"],
            "constraints": {
                **prior["constraints"],
                "commercial_use": False,
                "source_images_redistributed": False,
            },
        }
    )
    (output_dir / "frozen_candidate.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_hashes(output_dir)
    verify(output_dir)
    return manifest


def verify(root: Path) -> dict[str, Any]:
    verify_hashes(root)
    manifest = json.loads(
        (root / "frozen_candidate.json").read_text(encoding="utf-8")
    )
    if (
        not verify_stable(manifest)
        or manifest.get("candidate_id") != CANDIDATE_ID
        or manifest.get("status")
        != "FROZEN_BEFORE_LSVT_FOOTER_ROWS_OR_IMAGES"
    ):
        raise RuntimeError("LSVT v7 candidate verification failed")
    if manifest["prior_candidate_binding"]["behavioral_changes"]:
        raise RuntimeError("LSVT binding contains behavioral changes")
    policy = manifest["policy"]
    if (
        policy["annotation_text_length_used_at_inference"]
        or not policy["forest_threshold_is_effective"]
        or policy["forest_minimum_mean_probability"] != 0.25
    ):
        raise RuntimeError("v7 policy invariants changed")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--repository-root", type=Path, required=True)
    build_parser.add_argument("--prior-candidate-root", type=Path, required=True)
    build_parser.add_argument("--source-seal", type=Path, required=True)
    build_parser.add_argument("--source-commit", required=True)
    build_parser.add_argument("--output-dir", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    result = (
        build(
            repository_root=args.repository_root,
            prior_candidate_root=args.prior_candidate_root,
            source_seal_path=args.source_seal,
            source_commit=args.source_commit,
            output_dir=args.output_dir,
        )
        if args.command == "build"
        else verify(args.bundle)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
