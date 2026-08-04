"""Replay a retained OCR canary with contamination-resistant word crops."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image

from .isolated_crop import recrop_from_artifact
from .pixel_digit_alignment import PixelDigitAligner


def _status(decision: Any) -> str:
    status = getattr(decision, "status", "")
    return str(getattr(status, "value", status))


def _prediction(decision: Any) -> str:
    return str(getattr(decision, "predicted", ""))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tesseract_claim(image: Image.Image) -> tuple[str, float]:
    started = time.perf_counter()
    raw = pytesseract.image_to_string(
        image,
        lang="eng",
        config=(
            "--oem 1 --psm 7 "
            "-c tessedit_char_whitelist=0123456789 "
            "-c classify_bln_numeric_mode=1"
        ),
    )
    claim = "".join(character for character in raw if character.isdigit())
    return claim, (time.perf_counter() - started) * 1000.0


def replay(artifact_root: Path, output_dir: Path) -> dict[str, Any]:
    report_path = artifact_root / "reports/real_numeric_risk_holdout.json"
    source = json.loads(report_path.read_text(encoding="utf-8"))
    documents = {row["document_id"]: row for row in source["documents"]}
    output_crops = output_dir / "crops"
    output_crops.mkdir(parents=True, exist_ok=True)

    aligner = PixelDigitAligner()
    _ = aligner._bank  # type: ignore[attr-defined]
    rows: list[dict[str, Any]] = []
    for original in source["observations"]:
        document = documents[original["document_id"]]
        selected = document["native_index"]["selected"]
        page_reports = document.get("pages") or []
        if len(page_reports) != 1:
            raise RuntimeError("replay requires exactly one retained page report")
        image_size = tuple(int(value) for value in page_reports[0]["image_size"])
        crop_path = artifact_root / original["crop_path"]
        with Image.open(crop_path) as opened:
            padded = opened.convert("RGB")
            isolated, global_box, relative_box = recrop_from_artifact(
                padded,
                original["bbox_px"],
                selected["bbox_pt"],
                (
                    float(selected["page_width_pt"]),
                    float(selected["page_height_pt"]),
                ),
                image_size,
            )
        retained = output_crops / f"{original['crop_id']}.png"
        isolated.save(retained, optimize=False)
        claim, tesseract_ms = _tesseract_claim(isolated)
        if claim:
            started = time.perf_counter()
            decision = aligner.align(isolated, claim)
            verifier_ms = (time.perf_counter() - started) * 1000.0
            verifier_status = _status(decision)
            verifier_prediction = _prediction(decision)
        else:
            verifier_ms = 0.0
            verifier_status = "NO_CLAIM"
            verifier_prediction = ""
        accepted = verifier_status == "ALIGNED"

        counterfactual_claim = str(original["counterfactual_claim"])
        started = time.perf_counter()
        counterfactual = aligner.align(isolated, counterfactual_claim)
        counterfactual_ms = (time.perf_counter() - started) * 1000.0
        counterfactual_status = _status(counterfactual)
        rows.append(
            {
                "crop_id": original["crop_id"],
                "document_id": original["document_id"],
                "truth": original["truth"],
                "old_claim": original["tesseract_claim"],
                "old_claim_correct": original["claim_correct"],
                "old_verifier_status": original["verifier_status"],
                "old_false_accepted": original["false_accepted"],
                "isolated_claim": claim,
                "isolated_claim_correct": claim == original["truth"],
                "isolated_verifier_status": verifier_status,
                "isolated_verifier_prediction": verifier_prediction,
                "isolated_accepted": accepted,
                "isolated_false_accepted": accepted and claim != original["truth"],
                "counterfactual_claim": counterfactual_claim,
                "counterfactual_status": counterfactual_status,
                "counterfactual_false_accept": counterfactual_status == "ALIGNED",
                "tesseract_runtime_ms": tesseract_ms,
                "verifier_runtime_ms": verifier_ms,
                "counterfactual_runtime_ms": counterfactual_ms,
                "old_padded_box_px": original["bbox_px"],
                "isolated_box_px": list(global_box),
                "isolated_relative_box_px": list(relative_box),
                "isolated_crop_sha256": _sha256(retained),
            }
        )

    summary = {
        "schema": "ocr-real-risk-isolated-crop-replay/1",
        "source": {
            "artifact_root": str(artifact_root),
            "report_sha256": _sha256(report_path),
            "observations_replayed": len(rows),
            "selection_changed": False,
            "truth_changed": False,
            "only_crop_geometry_changed": True,
        },
        "old": {
            "baseline_predictions": sum(bool(row["old_claim"]) for row in rows),
            "baseline_errors": sum(not row["old_claim_correct"] for row in rows),
            "verifier_false_accepts": sum(row["old_false_accepted"] for row in rows),
        },
        "isolated": {
            "baseline_predictions": sum(bool(row["isolated_claim"]) for row in rows),
            "baseline_errors": sum(
                not row["isolated_claim_correct"] for row in rows
            ),
            "verifier_accepted": sum(row["isolated_accepted"] for row in rows),
            "verifier_false_accepts": sum(
                row["isolated_false_accepted"] for row in rows
            ),
            "counterfactual_false_accepts": sum(
                row["counterfactual_false_accept"] for row in rows
            ),
        },
        "environment": {
            "tesseract": subprocess.run(
                ["tesseract", "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()[0],
            "verifier_configuration": aligner.configuration(),
        },
        "rows": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "isolated_crop_replay.json"
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hashes = [
        f"{_sha256(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = replay(args.artifact_root, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
