"""Fail-closed wrapper for real-document OCR evaluation.

Two real-document edge cases are handled before evidence scoring:

* Tesseract may emit zero-area, non-finite, or out-of-page numeric boxes;
* PyMuPDF text coordinates are unrotated while page rendering applies the page
  rotation, so a raw PDF bbox can otherwise map outside the rendered image.

Invalid OCR boxes are removed and therefore become abstentions. PDF truth boxes
are transformed by the current page's rotation matrix before they are used for
spatial matching or diagnostic-only crops. Neither repair creates a primary
claim or uses ground truth to override Tesseract.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import fitz
from PIL import Image

from . import evaluate as base

_ORIGINAL_TESSERACT_TOKENS = base.tesseract_tokens
_ORIGINAL_PIL_PAGE = base.pil_page
_CURRENT_PAGE: fitz.Page | None = None


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


def robust_pil_page(page: fitz.Page, dpi: int) -> Image.Image:
    """Record the exact page whose rotation is applied during rendering."""
    global _CURRENT_PAGE
    _CURRENT_PAGE = page
    return _ORIGINAL_PIL_PAGE(page, dpi)


def rotation_aware_pdf_bbox_to_pixels(
    bbox_pdf: Sequence[float], dpi: int
) -> list[float]:
    """Map unrotated PDF text coordinates into the rendered page image."""
    rect = fitz.Rect(*(float(value) for value in bbox_pdf))
    if rect.is_empty or rect.is_infinite:
        raise ValueError("invalid PDF truth bbox")
    page = _CURRENT_PAGE
    if page is not None:
        rect = rect * page.rotation_matrix
    scale = dpi / 72.0
    return [
        float(rect.x0) * scale,
        float(rect.y0) * scale,
        float(rect.x1) * scale,
        float(rect.y1) * scale,
    ]


def main() -> int:
    base.tesseract_tokens = robust_tesseract_tokens
    base.pil_page = robust_pil_page
    base.pdf_bbox_to_pixels = rotation_aware_pdf_bbox_to_pixels
    return int(base.main())


if __name__ == "__main__":
    raise SystemExit(main())
