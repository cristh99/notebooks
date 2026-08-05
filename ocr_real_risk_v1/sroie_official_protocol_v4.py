"""Outcome-blind SROIE geometry protocol for OCR development canaries."""
from __future__ import annotations

import csv
import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image

ASCII_DIGITS = frozenset("0123456789")
ALLOWED_NON_DIGIT = frozenset(" \t\r\n.,:+-/$€£¥₹₡₦₱()[]{}'")
CURRENCY_CODE = re.compile(r"(?i)\b(?:HNL|LPS?|L|USD|US|EUR|GBP|JPY|CNY|RMB|MYR|RM)\b")


class Scope(str, Enum):
    SAME_LENGTH_SUBSTITUTION = "SAME_LENGTH_SUBSTITUTION"
    OUT_OF_SCOPE_LENGTH_OR_PARTIAL_MATCH = "OUT_OF_SCOPE_LENGTH_OR_PARTIAL_MATCH"


@dataclass(frozen=True, slots=True)
class BoxToken:
    page_id: str
    source_id: str
    text: str
    digits: str
    bbox: tuple[float, float, float, float]
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class Match:
    candidate: BoxToken
    truth: BoxToken
    geometry_score: float
    iou: float
    smaller_coverage: float
    vertical_overlap: float


def canonical_numeric(value: str, *, min_digits: int = 4, max_digits: int = 12) -> str | None:
    text = CURRENCY_CODE.sub("", unicodedata.normalize("NFKC", str(value or "")).strip()).strip()
    if any(ch not in ASCII_DIGITS and ch not in ALLOWED_NON_DIGIT for ch in text):
        return None
    digits = "".join(ch for ch in text if ch in ASCII_DIGITS)
    return digits if min_digits <= len(digits) <= max_digits else None


def parse_truth(path: Path, page_id: str) -> list[BoxToken]:
    output: list[BoxToken] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for index, row in enumerate(csv.reader(handle), start=1):
            if len(row) < 9:
                continue
            try:
                coordinates = [float(value) for value in row[:8]]
            except ValueError:
                continue
            text = ",".join(row[8:]).strip()
            digits = canonical_numeric(text)
            if digits is None:
                continue
            xs, ys = coordinates[0::2], coordinates[1::2]
            output.append(BoxToken(page_id, f"truth:{page_id}:{index}", text, digits, (min(xs), min(ys), max(xs), max(ys))))
    return output


def parse_tesseract_tsv(tsv: str, page_id: str) -> list[BoxToken]:
    output: list[BoxToken] = []
    for index, row in enumerate(csv.DictReader(tsv.splitlines(), delimiter="\t"), start=1):
        text = str(row.get("text") or "").strip()
        digits = canonical_numeric(text)
        if digits is None:
            continue
        try:
            left, top = float(row["left"]), float(row["top"])
            width, height, confidence = float(row["width"]), float(row["height"]), float(row["conf"])
        except (KeyError, TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            output.append(BoxToken(page_id, f"tesseract:{page_id}:{index}", text, digits, (left, top, left + width, top + height), confidence))
    return output


def geometry(first: Sequence[float], second: Sequence[float]) -> tuple[float, float, float]:
    ax0, ay0, ax1, ay1 = map(float, first)
    bx0, by0, bx1, by1 = map(float, second)
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    width, height = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    intersection = width * height
    area_a, area_b = max(1e-12, (ax1 - ax0) * (ay1 - ay0)), max(1e-12, (bx1 - bx0) * (by1 - by0))
    return (
        intersection / max(1e-12, area_a + area_b - intersection),
        intersection / max(1e-12, min(area_a, area_b)),
        height / max(1e-12, min(ay1 - ay0, by1 - by0)),
    )


def match_geometry_only(
    candidates: Iterable[BoxToken],
    truth: Iterable[BoxToken],
    *,
    min_iou: float = 0.20,
    min_smaller_coverage: float = 0.55,
    min_vertical_overlap: float = 0.55,
) -> list[Match]:
    candidate_rows, truth_rows = list(candidates), list(truth)
    edges: list[tuple[float, int, int, float, float, float]] = []
    for ci, candidate in enumerate(candidate_rows):
        for ti, expected in enumerate(truth_rows):
            iou, smaller, vertical = geometry(candidate.bbox, expected.bbox)
            if vertical >= min_vertical_overlap and (iou >= min_iou or smaller >= min_smaller_coverage):
                edges.append((max(iou, smaller) + 0.05 * vertical, ci, ti, iou, smaller, vertical))
    edges.sort(key=lambda row: (row[0], row[3], row[4], row[5]), reverse=True)
    used_candidates: set[int] = set()
    used_truth: set[int] = set()
    output: list[Match] = []
    for score, ci, ti, iou, smaller, vertical in edges:
        if ci in used_candidates or ti in used_truth:
            continue
        used_candidates.add(ci)
        used_truth.add(ti)
        output.append(Match(candidate_rows[ci], truth_rows[ti], score, iou, smaller, vertical))
    return sorted(output, key=lambda row: (row.candidate.page_id, row.candidate.bbox))


def classify_scope(match: Match) -> Scope:
    return Scope.SAME_LENGTH_SUBSTITUTION if len(match.candidate.digits) == len(match.truth.digits) else Scope.OUT_OF_SCOPE_LENGTH_OR_PARTIAL_MATCH


def padded_crop(image: Image.Image, bbox: Sequence[float], pad: int = 2) -> Image.Image:
    x0, y0, x1, y1 = bbox
    return image.crop((max(0, math.floor(x0) - pad), max(0, math.floor(y0) - pad), min(image.width, math.ceil(x1) + pad), min(image.height, math.ceil(y1) + pad)))


def sha256_image(image: Image.Image) -> str:
    converted = image.convert("L")
    digest = hashlib.sha256(str(converted.size).encode("ascii") + converted.tobytes())
    return digest.hexdigest()


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)
