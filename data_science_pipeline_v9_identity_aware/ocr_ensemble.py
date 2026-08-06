from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence

from facts_contract import canonical_json_bytes, sha256_file

CANDIDATES = (
    {"name": "auto_300_psm3", "dpi": 300, "psm": 3},
    {"name": "balanced_200_psm6", "dpi": 200, "psm": 6},
    {"name": "sparse_300_psm11", "dpi": 300, "psm": 11},
)


def _run(arguments: Sequence[str], *, stdout_text: bool = True) -> str | bytes:
    environment = dict(os.environ)
    environment.update({"LC_ALL": "C", "LANG": "C", "OMP_THREAD_LIMIT": "1"})
    completed = subprocess.run(
        list(arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=stdout_text,
        env=environment,
    )
    return completed.stdout


def _page_count(pdf_path: Path) -> int:
    output = str(_run(["pdfinfo", str(pdf_path)]))
    match = re.search(r"^Pages:\s+(\d+)\s*$", output, re.MULTILINE)
    if match is None:
        raise RuntimeError("pdfinfo did not expose a page count")
    return int(match.group(1))


def _numeric_page_key(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    if match is None:
        raise RuntimeError(f"unexpected raster filename: {path.name}")
    return int(match.group(1))


def _render(pdf_path: Path, render_root: Path, dpi: int, pages: int) -> list[Path]:
    render_root.mkdir(parents=True, exist_ok=True)
    prefix = render_root / "page"
    _run([
        "pdftoppm",
        "-f",
        "1",
        "-l",
        str(pages),
        "-r",
        str(dpi),
        "-png",
        str(pdf_path),
        str(prefix),
    ])
    images = sorted(render_root.glob("page-*.png"), key=_numeric_page_key)
    if len(images) != pages:
        raise RuntimeError(f"expected {pages} rasters at {dpi} DPI, got {len(images)}")
    return images


def _ocr(image: Path, psm: int) -> str:
    return str(
        _run(
            [
                "tesseract",
                str(image),
                "stdout",
                "-l",
                "spa+eng",
                "--oem",
                "1",
                "--psm",
                str(psm),
            ]
        )
    )


def run_ensemble(pdf_path: Path, output: Path, minimum_pages: int = 1, maximum_pages: int = 20) -> dict[str, Any]:
    if pdf_path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError("input is not a PDF by magic")
    pages = _page_count(pdf_path)
    if pages < minimum_pages or pages > maximum_pages:
        raise RuntimeError(f"page count outside frozen bounds: {pages}")
    output.mkdir(parents=True, exist_ok=True)
    render_cache: dict[int, list[Path]] = {}
    candidates: list[dict[str, Any]] = []
    for config in CANDIDATES:
        dpi = int(config["dpi"])
        psm = int(config["psm"])
        name = str(config["name"])
        if dpi not in render_cache:
            render_cache[dpi] = _render(pdf_path, output / "renders" / str(dpi), dpi, pages)
        candidate_root = output / name
        candidate_root.mkdir(parents=True, exist_ok=True)
        page_rows = []
        for index, image in enumerate(render_cache[dpi], start=1):
            text = _ocr(image, psm)
            text_path = candidate_root / f"page_{index:04d}.txt"
            text_path.write_text(text, encoding="utf-8", newline="\n")
            page_rows.append(
                {
                    "page": index,
                    "text_path": text_path.relative_to(output).as_posix(),
                    "text_bytes": text_path.stat().st_size,
                    "text_sha256": sha256_file(text_path),
                    "raster_path": image.relative_to(output).as_posix(),
                    "raster_bytes": image.stat().st_size,
                    "raster_sha256": sha256_file(image),
                }
            )
        candidates.append({**config, "pages": page_rows})
    manifest = {
        "schema": "data-science-pipeline/frozen-ocr-ensemble/1",
        "verdict": "OCR_SEALED",
        "source_pdf_name": pdf_path.name,
        "source_pdf_bytes": pdf_path.stat().st_size,
        "source_pdf_sha256": sha256_file(pdf_path),
        "page_count": pages,
        "minimum_pages": minimum_pages,
        "maximum_pages": maximum_pages,
        "native_text_used": False,
        "candidate_selection": "two-of-three fact consensus; no score and no native-text feedback",
        "candidates": candidates,
        "tools": {
            "pdfinfo": str(_run(["pdfinfo", "-v"])).splitlines()[:1],
            "pdftoppm": str(_run(["pdftoppm", "-v"])).splitlines()[:1],
            "tesseract": str(_run(["tesseract", "--version"])).splitlines()[:1],
        },
    }
    payload = canonical_json_bytes(manifest)
    manifest_path = output / "ocr-manifest.json"
    manifest_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (output / "ocr-manifest.sha256").write_text(f"{digest}  ocr-manifest.json\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_ensemble(args.pdf, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
