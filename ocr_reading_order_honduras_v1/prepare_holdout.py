"""Acquire and prepare the frozen Honduran reading-order holdout.

This stage does not score the frozen XY-cut kernel. It downloads the exact
predeclared public PDFs, renders page 1, runs Tesseract once, groups its words
into block-level units, and emits numbered overlays plus a blank annotation
template. Ground-truth order is added only after these immutable observations
have been archived.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont
import pytesseract

from ocr_reading_order_real_v1.core import Block, CANDIDATES, canonical_json, sha256_bytes

SCHEMA = "ocr-reading-order-honduras-v1/preparation/1"
MIN_REQUIRED_DOCUMENTS = 8
MAX_PDF_BYTES = 25 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    value = re.sub(r"[\t\r\f\v]+", " ", str(text or ""))
    return re.sub(r" +", " ", value).strip()


def _union(boxes: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    values = list(boxes)
    return (
        min(box[0] for box in values),
        min(box[1] for box in values),
        max(box[2] for box in values),
        max(box[3] for box in values),
    )


def group_tesseract_blocks(data: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Group word-level Tesseract output into stable block-level units."""
    groups: dict[int, list[int]] = defaultdict(list)
    for index, raw_text in enumerate(data.get("text", [])):
        text = normalize_text(str(raw_text))
        if not text:
            continue
        try:
            block_num = int(data["block_num"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if block_num <= 0 or width <= 0 or height <= 0:
            continue
        groups[block_num].append(index)

    blocks: list[dict[str, Any]] = []
    for stable_index, block_num in enumerate(sorted(groups)):
        indices = groups[block_num]
        boxes = [
            (
                float(data["left"][index]),
                float(data["top"][index]),
                float(data["left"][index]) + float(data["width"][index]),
                float(data["top"][index]) + float(data["height"][index]),
            )
            for index in indices
        ]
        words = [normalize_text(str(data["text"][index])) for index in indices]
        confidences: list[float] = []
        for index in indices:
            try:
                confidence = float(data["conf"][index])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if confidence >= 0:
                confidences.append(confidence / 100.0)
        text = " ".join(word for word in words if word)
        if len(text) < 2:
            continue
        blocks.append(
            {
                "block_id": f"B{stable_index:03d}",
                "tesseract_block_num": block_num,
                "text": text,
                "bbox": list(_union(boxes)),
                "confidence": sum(confidences) / max(len(confidences), 1),
                "word_count": len(words),
            }
        )
    return blocks


def ordered_ids(
    blocks: Sequence[Mapping[str, Any]],
    page_width: float,
    page_height: float,
    candidate_name: str,
) -> list[str]:
    candidate = next(item for item in CANDIDATES if item.name == candidate_name)
    geometry = [
        Block(
            str(item["block_id"]),
            0,
            "tesseract_block",
            tuple(float(value) for value in item["bbox"]),
        )
        for item in blocks
    ]
    return [item.block_id for item in candidate.orderer(geometry, page_width, page_height)]


def _run(command: Sequence[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def download_pdf(url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = destination.with_suffix(".headers.txt")
    started = time.perf_counter()
    try:
        result = _run(
            [
                "curl",
                "-L",
                "--fail",
                "--retry",
                "2",
                "--retry-all-errors",
                "--connect-timeout",
                "20",
                "--max-time",
                "180",
                "--max-filesize",
                str(MAX_PDF_BYTES),
                "-D",
                str(headers),
                "-o",
                str(destination),
                url,
            ],
            timeout=210,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "DOWNLOAD_FAILED",
            "seconds": time.perf_counter() - started,
            "error": str(exc),
        }
    if not destination.exists() or destination.stat().st_size < 100:
        return {"status": "EMPTY_DOWNLOAD", "seconds": time.perf_counter() - started}
    prefix = destination.read_bytes()[:5]
    if prefix != b"%PDF-":
        return {
            "status": "NOT_PDF",
            "seconds": time.perf_counter() - started,
            "bytes": destination.stat().st_size,
            "prefix_hex": prefix.hex(),
        }
    return {
        "status": "ACQUIRED",
        "seconds": time.perf_counter() - started,
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "curl_stdout": result.stdout[-500:],
        "headers_sha256": sha256_file(headers) if headers.exists() else None,
    }


def render_first_page(pdf_path: Path, output_prefix: Path) -> Path:
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-singlefile",
            "-r",
            "150",
            "-png",
            str(pdf_path),
            str(output_prefix),
        ],
        timeout=180,
    )
    path = output_prefix.with_suffix(".png")
    if not path.exists():
        raise RuntimeError("pdftoppm did not create a first-page PNG")
    return path


def run_tesseract_blocks(image_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    image = Image.open(image_path).convert("RGB")
    started = time.perf_counter()
    language = "spa+eng"
    try:
        data = pytesseract.image_to_data(
            image,
            lang=language,
            config="--oem 1 --psm 3",
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractError:
        language = "eng"
        data = pytesseract.image_to_data(
            image,
            lang=language,
            config="--oem 1 --psm 3",
            output_type=pytesseract.Output.DICT,
        )
    blocks = group_tesseract_blocks(data)
    return blocks, {
        "seconds": time.perf_counter() - started,
        "language": language,
        "page_width": image.width,
        "page_height": image.height,
        "image_sha256": sha256_file(image_path),
        "image_bytes": image_path.stat().st_size,
    }


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, *, fill: str = "black") -> None:
    draw.text(xy, value, font=ImageFont.load_default(), fill=fill)


def create_overlay(
    image_path: Path,
    blocks: Sequence[Mapping[str, Any]],
    baseline_order: Sequence[str],
    geometry_order: Sequence[str],
    destination: Path,
) -> None:
    page = Image.open(image_path).convert("RGB")
    panel_width = 720
    canvas = Image.new("RGB", (page.width + panel_width, max(page.height, 900)), "white")
    canvas.paste(page, (0, 0))
    draw = ImageDraw.Draw(canvas)
    palette = ["red", "blue", "green", "purple", "orange", "brown", "magenta", "cyan"]
    for index, item in enumerate(blocks):
        left, top, right, bottom = [int(round(value)) for value in item["bbox"]]
        color = palette[index % len(palette)]
        draw.rectangle((left, top, right, bottom), outline=color, width=4)
        label = str(item["block_id"])
        label_box = (left, max(0, top - 17), left + 42, top)
        draw.rectangle(label_box, fill="white", outline=color, width=2)
        _text(draw, (left + 2, max(0, top - 15)), label, fill=color)

    x = page.width + 15
    _text(draw, (x, 10), "HONDURAS READING-ORDER HOLDOUT")
    _text(draw, (x, 30), f"Blocks: {len(blocks)}")
    _text(draw, (x, 52), "Baseline y/x:")
    baseline_lines = [", ".join(baseline_order[i : i + 10]) for i in range(0, len(baseline_order), 10)]
    y = 70
    for line in baseline_lines:
        _text(draw, (x, y), line)
        y += 16
    y += 6
    _text(draw, (x, y), "Frozen XY-cut:")
    y += 18
    geometry_lines = [", ".join(geometry_order[i : i + 10]) for i in range(0, len(geometry_order), 10)]
    for line in geometry_lines:
        _text(draw, (x, y), line)
        y += 16
    y += 10
    _text(draw, (x, y), "Block text snippets:")
    y += 18
    for item in blocks:
        snippet = normalize_text(str(item["text"]))[:85]
        _text(draw, (x, y), f"{item['block_id']}: {snippet}")
        y += 16
        if y > canvas.height - 20:
            break
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, optimize=True)


def create_contact_sheet(overlays: Sequence[Path], destination: Path) -> None:
    thumbs: list[tuple[str, Image.Image]] = []
    for path in overlays:
        image = Image.open(path).convert("RGB")
        image.thumbnail((900, 700))
        thumbs.append((path.stem, image.copy()))
    columns = 2
    cell_width, cell_height = 930, 750
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, max(1, rows) * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(thumbs):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        _text(draw, (x + 10, y + 5), name)
        sheet.paste(image, (x + 10, y + 25))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, optimize=True)


def prepare(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    observations: list[dict[str, Any]] = []
    overlays: list[Path] = []
    for item in manifest["documents"]:
        document_id = str(item["id"])
        pdf_path = output_dir / "pdf" / f"{document_id}.pdf"
        acquisition = download_pdf(str(item["url"]), pdf_path)
        observation: dict[str, Any] = {
            "document": item,
            "acquisition": acquisition,
            "status": acquisition["status"],
        }
        if acquisition["status"] != "ACQUIRED":
            observations.append(observation)
            continue
        try:
            page_path = render_first_page(pdf_path, output_dir / "pages" / document_id)
            blocks, ocr = run_tesseract_blocks(page_path)
            observation["page"] = ocr
            observation["blocks"] = blocks
            observation["page_png"] = str(page_path.relative_to(output_dir))
            if len(blocks) < 2:
                observation["status"] = "UNSCORABLE_FEWER_THAN_TWO_BLOCKS"
                observations.append(observation)
                continue
            baseline = ordered_ids(blocks, ocr["page_width"], ocr["page_height"], "yx_baseline")
            geometry = ordered_ids(blocks, ocr["page_width"], ocr["page_height"], "xycut_loose")
            observation["baseline_order"] = baseline
            observation["geometry_order"] = geometry
            observation["status"] = "PREPARED"
            overlay_path = output_dir / "overlays" / f"{document_id}.png"
            create_overlay(page_path, blocks, baseline, geometry, overlay_path)
            observation["overlay_png"] = str(overlay_path.relative_to(output_dir))
            observation["overlay_sha256"] = sha256_file(overlay_path)
            overlays.append(overlay_path)
        except Exception as exc:  # preserve every disposition; do not silently drop documents
            observation["status"] = "PREPARATION_FAILED"
            observation["error"] = f"{type(exc).__name__}: {exc}"
        observations.append(observation)

    prepared = [item for item in observations if item["status"] == "PREPARED"]
    if overlays:
        create_contact_sheet(overlays, output_dir / "overlays" / "CONTACT_SHEET.png")
    template = {
        "schema": "ocr-reading-order-honduras-v1/annotations/1",
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "instructions": "For every PREPARED page, provide each block_id exactly once in human reading order; do not change blocks, images, algorithms, or page identities.",
        "annotations": [
            {
                "document_id": item["document"]["id"],
                "source_pdf_sha256": item["acquisition"]["sha256"],
                "page_png_sha256": item["page"]["image_sha256"],
                "overlay_sha256": item["overlay_sha256"],
                "available_block_ids": [block["block_id"] for block in item["blocks"]],
                "correct_order": [],
                "annotation_status": "PENDING",
            }
            for item in prepared
        ],
    }
    stable_payload = {
        "schema": SCHEMA,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "documents_declared": len(manifest["documents"]),
        "documents_prepared": len(prepared),
        "observations": observations,
        "constraints": manifest["constraints"],
    }
    stable_sha = sha256_bytes(canonical_json(stable_payload).encode("utf-8"))
    report = {**stable_payload, "stable_payload_sha256": stable_sha}
    reports = output_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "preparation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (reports / "annotation_template.json").write_text(json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (reports / "preparation.sha256").write_text(
        f"{sha256_file(reports / 'preparation.json')}  preparation.json\n",
        encoding="utf-8",
    )
    if len(prepared) < MIN_REQUIRED_DOCUMENTS:
        raise RuntimeError(f"only {len(prepared)} documents prepared; need at least {MIN_REQUIRED_DOCUMENTS}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("ocr_reading_order_honduras_v1/manifest.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_reading_order_honduras_v1/run"))
    args = parser.parse_args()
    report = prepare(args.manifest, args.output_dir)
    print(
        json.dumps(
            {
                "documents_declared": report["documents_declared"],
                "documents_prepared": report["documents_prepared"],
                "statuses": {
                    item["document"]["id"]: item["status"]
                    for item in report["observations"]
                },
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
