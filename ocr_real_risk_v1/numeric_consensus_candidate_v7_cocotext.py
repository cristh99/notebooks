"""Deterministic builder for the preregistered COCO-Text v7 bundle."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .cocotext_source_seal_v7 import verify as verify_source_seal
from .core import canonical_json, sha256_bytes, sha256_file
from .numeric_consensus_policy_v7 import policy_manifest

CANDIDATE_ID = "numeric-consensus-v7-cocotext"
V6_STABLE = "96b35ec606a174e25c49089e099c917e88425385c46ba557dd594de506f349ca"
DEVELOPMENT_STABLE = "2e1ac87773d387c27c0d8a8649eb03f39739b8275f3b34a71654a0c81f67cb79"
OVERLAYS = (
    "ocr_real_risk_v1/numeric_consensus_policy_v7.py",
    "ocr_real_risk_v1/test_numeric_consensus_policy_v7.py",
    "ocr_real_risk_v1/textocr_v7_development_replay.py",
    "ocr_real_risk_v1/cocotext_source_seal_v7.py",
    "ocr_real_risk_v1/ocrdata_adapter_v7.py",
    "ocr_real_risk_v1/numeric_consensus_candidate_v7_cocotext.py",
)


def stable(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("stable_payload_sha256", None)
    result["stable_payload_sha256"] = sha256_bytes(
        canonical_json(result).encode()
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
        path for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (root / "SHA256SUMS.txt").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n"
            for path in files
        )
    )


def build(
    repo: Path,
    v6: Path,
    source_seal_path: Path,
    development_path: Path,
    source_commit: str,
    output: Path,
) -> dict[str, Any]:
    if len(source_commit) != 40:
        raise RuntimeError("full source commit required")
    verify_hashes(v6)
    v6_manifest = json.loads((v6 / "frozen_candidate.json").read_text())
    if v6_manifest.get("stable_payload_sha256") != V6_STABLE:
        raise RuntimeError("v6 candidate binding mismatch")

    source_seal = json.loads(source_seal_path.read_text())
    if not verify_source_seal(source_seal):
        raise RuntimeError("source seal replay failed")
    source = source_seal["source_object"]
    if (
        source_seal.get("outcomes_opened") is not False
        or source.get("path") != "data/cocotext-00000-of-00001.parquet"
        or source.get("size_bytes") != 2_223_323_062
        or source.get("sha256")
        != "562176cbb803bb7aa140a4537701ef53ebb86e396c8927f9b160227ac49efd48"
    ):
        raise RuntimeError("COCO-Text source binding mismatch")

    development = json.loads(development_path.read_text())
    if (
        not verify_stable(development)
        or development.get("stable_payload_sha256") != DEVELOPMENT_STABLE
        or development["limitations"]["scientific_credit"] is not False
    ):
        raise RuntimeError("development evidence binding mismatch")

    shutil.rmtree(output, ignore_errors=True)
    shutil.copytree(v6 / "source", output / "source")
    shutil.copytree(v6 / "model", output / "model")
    for relative in OVERLAYS:
        src = repo / relative
        dst = output / "source" / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(source_seal_path, output / "cocotext_source_seal_v7.json")
    shutil.copy2(development_path, output / "textocr_v7_development_diagnostic.json")

    manifest = stable(
        {
            "schema": "ocr-numeric-consensus-v7-cocotext-candidate/1",
            "candidate_id": CANDIDATE_ID,
            "status": "FROZEN_BEFORE_COCOTEXT_FOOTER_ROWS_OR_IMAGES",
            "source_commit": source_commit,
            "policy": policy_manifest(),
            "digit_model": {
                **v6_manifest["digit_model"],
                "reused_without_retraining": True,
            },
            "source_seal_stable_payload_sha256": source_seal[
                "stable_payload_sha256"
            ],
            "development_stable_payload_sha256": DEVELOPMENT_STABLE,
            "full_download_gate": {
                "minimum_selected": 5000,
                "minimum_projected_verified": 400,
                "development_acceptance_rate": 110 / 4674,
            },
            "quality_gate": {
                "target_error_reduction": 10.0,
                "minimum_coverage_lower": 0.25,
                "counterfactual_maximum_upper": 0.01,
                "macrofolds": 4,
                "minimum_macrofold_pass_fraction": 0.75,
            },
            "speed_gate": {
                "measure_candidate_and_baseline_wall_seconds": True,
                "tenfold_claim_requires_ratio_at_most": 0.1,
                "claim_authorized": False,
            },
            "constraints": {
                "external_spend_usd": 0,
                "gcloud_used": False,
                "gpu_used": False,
                "paid_api_used": False,
                "production_modified": False,
            },
        }
    )
    (output / "frozen_candidate.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    write_hashes(output)
    verify(output)
    return manifest


def verify(root: Path) -> dict[str, Any]:
    verify_hashes(root)
    manifest = json.loads((root / "frozen_candidate.json").read_text())
    if not verify_stable(manifest) or manifest.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("v7 bundle verification failed")
    policy = manifest["policy"]
    if policy["annotation_text_length_used_at_inference"]:
        raise RuntimeError("truth-length oracle survived")
    if not policy["forest_threshold_is_effective"]:
        raise RuntimeError("probability threshold is ineffective")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--repository-root", type=Path, required=True)
    b.add_argument("--v6-candidate-root", type=Path, required=True)
    b.add_argument("--source-seal", type=Path, required=True)
    b.add_argument("--development-diagnostic", type=Path, required=True)
    b.add_argument("--source-commit", required=True)
    b.add_argument("--output-dir", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("bundle", type=Path)
    args = parser.parse_args()
    result = (
        build(
            args.repository_root,
            args.v6_candidate_root,
            args.source_seal,
            args.development_diagnostic,
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
