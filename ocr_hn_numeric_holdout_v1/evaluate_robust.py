"""Fail-closed wrapper for real-document OCR evaluation.

Tesseract occasionally emits numeric tokens with zero-area or fully out-of-page
bounding boxes. Those boxes cannot support a production pixel decision. This
wrapper filters or clips them before spatial matching, so the evaluator records
an abstention instead of aborting or falling back to truth geometry for a
primary decision.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from PIL import Image

from . import evaluate as base

_ORIGINAL_TESSERACT_TOKENS = base.tesseract_tokens


def sanitize_numeric_tokens(
    tokens: Sequence[Mapping[str, Any]], image: Image.Image
) -> tuple[list[dict[str, Any]], int]:
    """Return finite, positive-area token boxes clipped to the page image."""
    valid: list[dict[str, Any]] = []
    rejected = 0
    for token in tokens:
        bbox = token.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            rejected += 1
            continue
        try:
            x0, y0, x1, y1 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            rejected += 1
            continue
        if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            rejected += 1
            continue
        clipped = [
            max(0.0, x0),
            max(0.0, y0),
            min(float(image.width), x1),
            min(float(image.height), y1),
        ]
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            rejected += 1
            continue
        normalized = dict(token)
        normalized["bbox"] = [
            int(math.floor(clipped[0])),
            int(math.floor(clipped[1])),
            int(math.ceil(clipped[2])),
            int(math.ceil(clipped[3])),
        ]
        if (
            normalized["bbox"][2] <= normalized["bbox"][0]
            or normalized["bbox"][3] <= normalized["bbox"][1]
        ):
            rejected += 1
            continue
        valid.append(normalized)
    return valid, rejected


def robust_tesseract_tokens(image: Image.Image, language: str, psm: int):
    tokens, runtime = _ORIGINAL_TESSERACT_TOKENS(image, language, psm)
    valid, rejected = sanitize_numeric_tokens(tokens, image)
    enriched = dict(runtime)
    enriched["invalid_numeric_bboxes_filtered"] = rejected
    enriched["tokens_after_bbox_filter"] = len(valid)
    return valid, enriched


def main() -> int:
    base.tesseract_tokens = robust_tesseract_tokens
    return int(base.main())


if __name__ == "__main__":
    raise SystemExit(main())
