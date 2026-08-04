"""PDF acquisition, trusted native-box extraction, rendering and crop OCR."""
from __future__ import annotations

import html
import math
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageOps
import pytesseract

from .core import MAX_FILE_BYTES, MAX_PAGES_PER_DOCUMENT, RENDER_DPI, sha256_file


def run(argv: Sequence[str], *, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(list(argv), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n"
            f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
        )
    return result


def download_pdf(url: str, destination: Path) -> dict[str, Any]:
    """Stream one public PDF with a strict byte and time ceiling."""
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OCR-Real-Risk-Holdout/1.0", "Accept": "application/pdf"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response, destination.open("wb") as handle:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_FILE_BYTES:
                return {"status": "SKIPPED_TOO_LARGE", "seconds": time.perf_counter()-started,
                        "declared_bytes": int(declared)}
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ValueError("download exceeded byte ceiling")
                handle.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        destination.unlink(missing_ok=True)
        return {"status": "DOWNLOAD_FAILED", "seconds": time.perf_counter()-started,
                "error": f"{type(exc).__name__}: {exc}"}
    elapsed = time.perf_counter() - started
    size = destination.stat().st_size
    with destination.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        destination.unlink(missing_ok=True)
        return {"status": "NOT_PDF", "seconds": elapsed, "bytes": size}
    return {"status": "ACQUIRED", "seconds": elapsed, "bytes": size,
            "sha256": sha256_file(destination)}


def pdf_page_count(pdf_path: Path) -> int:
    result = run(["pdfinfo", str(pdf_path)], timeout=30)
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError("pdfinfo did not report page count")


def selected_pages(page_count: int) -> tuple[int, ...]:
    if page_count <= 1 or MAX_PAGES_PER_DOCUMENT <= 1: return (1,)
    return (1, page_count)


def extract_word_boxes(pdf_path: Path, page_number: int, work_dir: Path) -> tuple[float, float, list[dict[str, Any]]]:
    output = work_dir / f"page-{page_number:04d}-bbox.html"
    run(["pdftotext", "-f", str(page_number), "-l", str(page_number),
         "-bbox", "-enc", "UTF-8", str(pdf_path), str(output)], timeout=45)
    root = ET.parse(output).getroot()
    page = next((x for x in root.iter() if x.tag.rsplit("}", 1)[-1] == "page"), None)
    if page is None: raise RuntimeError("bbox output has no page")
    width, height = float(page.attrib["width"]), float(page.attrib["height"])
    words: list[dict[str, Any]] = []
    for node in page.iter():
        if node.tag.rsplit("}", 1)[-1] != "word": continue
        try:
            box = [float(node.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax")]
        except (KeyError, ValueError):
            continue
        words.append({"text": html.unescape("".join(node.itertext())).strip(), "bbox_pt": box})
    return width, height, words


def page_has_full_image(pdf_path: Path, page_number: int,
                        page_width_pt: float, page_height_pt: float) -> tuple[bool, float]:
    result = run(["pdfimages", "-f", str(page_number), "-l", str(page_number),
                  "-list", str(pdf_path)], timeout=30, check=False)
    max_coverage = 0.0
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 14 or not fields[0].isdigit() or not fields[1].isdigit(): continue
        try:
            width_px, height_px = float(fields[3]), float(fields[4])
            x_ppi, y_ppi = float(fields[12]), float(fields[13])
        except (ValueError, IndexError):
            continue
        if x_ppi <= 0 or y_ppi <= 0: continue
        physical_w, physical_h = width_px / x_ppi * 72.0, height_px / y_ppi * 72.0
        coverage = min(1.0, physical_w * physical_h / max(1.0, page_width_pt * page_height_pt))
        max_coverage = max(max_coverage, coverage)
    return max_coverage >= 0.75, max_coverage


def render_page(pdf_path: Path, page_number: int, work_dir: Path) -> Path:
    stem = work_dir / f"page-{page_number:04d}"
    run(["pdftoppm", "-f", str(page_number), "-l", str(page_number),
         "-singlefile", "-r", str(RENDER_DPI), "-png", str(pdf_path), str(stem)], timeout=90)
    path = stem.with_suffix(".png")
    if not path.exists(): raise RuntimeError("pdftoppm did not create PNG")
    return path


def crop_box(bbox_pt: Sequence[float], page_size_pt: tuple[float, float],
             image_size_px: tuple[int, int]) -> tuple[int, int, int, int]:
    page_w, page_h = page_size_pt
    image_w, image_h = image_size_px
    x0, y0, x1, y1 = bbox_pt
    sx, sy = image_w / page_w, image_h / page_h
    left, top, right, bottom = x0*sx, y0*sy, x1*sx, y1*sy
    height, width = max(1.0, bottom-top), max(1.0, right-left)
    pad_x, pad_y = max(3.0, width*0.12), max(3.0, height*0.28)
    return (max(0, math.floor(left-pad_x)), max(0, math.floor(top-pad_y)),
            min(image_w, math.ceil(right+pad_x)), min(image_h, math.ceil(bottom+pad_y)))


def crop_is_usable(crop: Image.Image) -> bool:
    if crop.width < 12 or crop.height < 10: return False
    extrema = ImageOps.grayscale(crop).getextrema()
    return bool(extrema and extrema[1] - extrema[0] >= 35)


def tesseract_claim(crop: Image.Image) -> tuple[str, float]:
    started = time.perf_counter()
    raw = pytesseract.image_to_string(
        crop, lang="eng",
        config="--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789 -c classify_bln_numeric_mode=1",
    )
    return "".join(x for x in raw if x.isdigit()), (time.perf_counter()-started)*1000.0
