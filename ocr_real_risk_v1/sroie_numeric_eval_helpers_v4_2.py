"""Small read-only helpers for SROIE numeric OCR development replays."""
from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ["OMP_THREAD_LIMIT"] = "1"

from PIL import Image
import pytesseract
from pytesseract import Output

from .semantic_rival_detector_v4_2 import SemanticOCRToken, canonical_ascii_digits

_PATTERNS = (
    re.compile(r"^[+-]?[0-9]+$"),
    re.compile(r"^[+-]?[0-9]+[.,][0-9]+$"),
    re.compile(r"^[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?$"),
    re.compile(r"^[+-]?[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?$"),
    re.compile(r"^[0-9]+(?:/[0-9]+)+$"),
    re.compile(r"^[0-9]+(?:-[0-9]+)+$"),
)
_YEAR = re.compile(r"^(?:19|20)[0-9]{2}$")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tesseract_version() -> str:
    run = subprocess.run(
        ["tesseract", "--version"], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    return run.stdout.splitlines()[0].strip() if run.stdout else "unknown"


def page_tokens(image: Image.Image) -> tuple[tuple[SemanticOCRToken, ...], float]:
    started = time.perf_counter()
    data = pytesseract.image_to_data(
        image, lang="eng", config="--oem 1 --psm 3",
        output_type=Output.DICT, timeout=60,
    )
    elapsed = time.perf_counter() - started
    tokens: list[SemanticOCRToken] = []
    for index, raw in enumerate(data.get("text") or []):
        text = str(raw).strip()
        if not text:
            continue
        try:
            left, top = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            confidence = float(data["conf"][index])
            block = int(data["block_num"][index])
            paragraph = int(data["par_num"][index])
            line = int(data["line_num"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0 or not math.isfinite(confidence):
            continue
        tokens.append(SemanticOCRToken(
            index=index, text=text, bbox=(left, top, left + width, top + height),
            confidence=confidence, block=block, paragraph=paragraph, line=line,
        ))
    return tuple(tokens), elapsed


def numeric_truth(text: str) -> str | None:
    value = str(text or "").strip().upper()
    value = re.sub(r"^(?:RM|MYR|USD|US\$|\$)\s*:?\s*", "", value)
    value = value.strip(" \t\r\n:;#()[]{}*")
    if not value or not any(pattern.fullmatch(value) for pattern in _PATTERNS):
        return None
    digits = canonical_ascii_digits(value)
    if not 4 <= len(digits) <= 12 or _YEAR.fullmatch(digits):
        return None
    if len(digits) >= 6 and len(set(digits)) == 1:
        return None
    return digits


def parse_annotations(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 9:
                continue
            try:
                coords = [float(value) for value in row[:8]]
            except ValueError:
                continue
            text = ",".join(row[8:]).strip()
            truth = numeric_truth(text)
            if truth is None:
                continue
            xs, ys = coords[0::2], coords[1::2]
            rows.append({"text": text, "truth": truth,
                         "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    return rows


def _overlap(first: Sequence[float], second: Sequence[float]) -> tuple[float, float, float, float]:
    ax0, ay0, ax1, ay1 = map(float, first)
    bx0, by0, bx1, by1 = map(float, second)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1e-9, (bx1 - bx0) * (by1 - by0))
    union = area_a + area_b - intersection
    ca, cb = ((ax0 + ax1) / 2, (ay0 + ay1) / 2), ((bx0 + bx1) / 2, (by0 + by1) / 2)
    return intersection / union, intersection / area_a, intersection / area_b, math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def match_annotation(
    annotation: Mapping[str, Any], tokens: Sequence[SemanticOCRToken]
) -> tuple[SemanticOCRToken, dict[str, float]] | None:
    truth_bbox = annotation["bbox"]
    tx0, ty0, tx1, ty1 = map(float, truth_bbox)
    center = ((tx0 + tx1) / 2, (ty0 + ty1) / 2)
    ranked: list[tuple[float, float, str, SemanticOCRToken, dict[str, float]]] = []
    for token in tokens:
        if not token.digits:
            continue
        iou, truth_cover, token_cover, distance = _overlap(truth_bbox, token.bbox)
        bx0, by0, bx1, by1 = token.bbox
        if truth_cover < 0.35 and not (bx0 <= center[0] <= bx1 and by0 <= center[1] <= by1):
            continue
        score = 3 * truth_cover + token_cover + 0.5 * iou - 0.001 * distance
        metrics = {"iou": iou, "truth_coverage": truth_cover,
                   "token_coverage": token_cover, "center_distance": distance,
                   "score": score}
        ranked.append((score, token.confidence, token.digits, token, metrics))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return ranked[0][3], ranked[0][4]
