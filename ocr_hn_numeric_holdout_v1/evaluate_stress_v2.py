"""Independent 2025 development evaluation of a frozen stronger scan tier.

The transform was selected from the completed 20-OCID 2026 smoke solely as a
challenge generator. It is frozen before this 2025 sample and does not change
the pixel verifier or any acceptance threshold.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from . import evaluate as base
from .core import canonical_json, sha256_bytes

TIER = "scan_stress_v2_dev"
RECIPE = {
    "downsample_scale": 0.45,
    "gaussian_blur_radius": 0.9,
    "contrast": 0.8,
    "brightness": 0.98,
    "jpeg_quality": 30,
    "upscale": "bicubic_to_original_geometry",
}


def apply_stress_v2(image: Image.Image, tier: str) -> Image.Image:
    if tier != TIER:
        return base._ORIGINAL_APPLY_PAGE_TIER(image, tier)
    size = image.size
    degraded = ImageOps.grayscale(image).resize(
        (
            max(1, round(size[0] * RECIPE["downsample_scale"])),
            max(1, round(size[1] * RECIPE["downsample_scale"])),
        ),
        Image.Resampling.LANCZOS,
    )
    degraded = degraded.filter(
        ImageFilter.GaussianBlur(RECIPE["gaussian_blur_radius"])
    )
    degraded = ImageEnhance.Contrast(degraded).enhance(RECIPE["contrast"])
    degraded = ImageEnhance.Brightness(degraded).enhance(RECIPE["brightness"])
    buffer = io.BytesIO()
    degraded.save(
        buffer,
        format="JPEG",
        quality=RECIPE["jpeg_quality"],
        optimize=False,
        progressive=False,
    )
    buffer.seek(0)
    with Image.open(buffer) as opened:
        decoded = opened.convert("L")
    return decoded.resize(size, Image.Resampling.BICUBIC).convert("RGB")


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--pdf-cache", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_hn_numeric_holdout_v1/run/evaluation"),
    )
    parser.add_argument("--minimum-accepted", type=int, default=5)
    parser.add_argument("--minimum-coverage", type=float, default=0.20)
    parser.add_argument("--counterfactual-minimum-total", type=int, default=10)
    parser.add_argument("--counterfactual-maximum-risk", type=float, default=0.30)
    return parser


def main() -> int:
    args = parser().parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not hasattr(base, "_ORIGINAL_APPLY_PAGE_TIER"):
        base._ORIGINAL_APPLY_PAGE_TIER = base.apply_page_tier
    base.SUPPORTED_TIERS = tuple(dict.fromkeys((*base.SUPPORTED_TIERS, TIER)))
    base.apply_page_tier = apply_stress_v2

    report = base.evaluate_manifest(
        manifest,
        dpi=300,
        language="spa",
        psm=3,
        tier=TIER,
        pdf_timeout=90,
        pdf_cache=args.pdf_cache,
        evidence_dir=args.output_dir / "crops",
        minimum_accepted=args.minimum_accepted,
        minimum_coverage=args.minimum_coverage,
        factor=10.0,
        alpha=0.05,
        minimum_institution_fold_pass_fraction=0.0,
        counterfactual_maximum_risk=args.counterfactual_maximum_risk,
        counterfactual_minimum_total=args.counterfactual_minimum_total,
    )
    report["runtime"]["image_tier"] = TIER
    report["runtime"]["image_tier_recipe"] = RECIPE
    report["research_design"]["development_split"] = {
        "source_year": 2025,
        "recipe_frozen_before_sample": True,
        "selection_basis": "2026 smoke development only",
        "thresholds_changed": False,
        "claim_scope": "development challenge calibration; not final external proof",
    }
    for observation in report["observations"]:
        observation["image_tier"] = TIER
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )

    path = args.output_dir / "evaluation.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "evaluation.sha256").write_text(
        f"{sha256_bytes(path.read_bytes())}  evaluation.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "tier": TIER,
                "recipe": RECIPE,
                "summary": report["summary"],
                "risk_gate": report["risk_gate"],
                "counterfactual_gate": report["counterfactual_gate"],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
