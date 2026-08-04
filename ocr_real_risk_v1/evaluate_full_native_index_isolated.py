"""All-page native-index evaluation with contamination-resistant crops."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from . import evaluate as base
from .core import Candidate, canonical_json, sha256_bytes
from .evaluate_full_native_index import execute_full_native_index
from .isolated_crop import (
    HORIZONTAL_PAD_PX,
    VERTICAL_PAD_PX,
    isolated_native_word_box,
)


def _isolated_crop_box(
    bbox_pt: Sequence[float],
    page_size_pt: tuple[float, float],
    image_size_px: tuple[int, int],
) -> tuple[int, int, int, int]:
    return isolated_native_word_box(
        bbox_pt,
        page_size_pt,
        image_size_px,
    )


def execute_full_native_index_isolated(
    candidates: Sequence[Candidate],
    output_dir: Path,
    max_documents: int,
    target_tokens: int,
    stage: str,
    source_paths: Sequence[Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the existing full index while replacing only crop geometry."""
    original_crop_box = base.crop_box
    base.crop_box = _isolated_crop_box
    try:
        report, anchor_census = execute_full_native_index(
            candidates,
            output_dir,
            max_documents,
            target_tokens,
            stage,
            source_paths,
        )
    finally:
        base.crop_box = original_crop_box

    documents = {row["document_id"]: row for row in report["documents"]}
    for observation in report["observations"]:
        document = documents[observation["document_id"]]
        selected = document["native_index"]["selected"]
        pages = document.get("pages") or []
        if len(pages) != 1 or "image_size" not in pages[0]:
            raise RuntimeError("isolated observation lacks one rendered page")
        expected = isolated_native_word_box(
            selected["bbox_pt"],
            (
                float(selected["page_width_pt"]),
                float(selected["page_height_pt"]),
            ),
            tuple(int(value) for value in pages[0]["image_size"]),
        )
        if tuple(int(value) for value in observation["bbox_px"]) != expected:
            raise RuntimeError("recorded crop geometry differs from isolated protocol")

    report["protocol"]["crop_geometry"] = {
        "schema": "ocr-real-risk-isolated-native-word-crop/1",
        "source_geometry": "native PDF word bbox selected before OCR",
        "horizontal_padding_px": HORIZONTAL_PAD_PX,
        "vertical_padding_px": VERTICAL_PAD_PX,
        "proportional_padding": False,
        "selection_or_truth_changed": False,
        "development_origin": (
            "fixed after an exact replay showed all three apparent baseline "
            "errors in the prior 16-case canary were neighboring-glyph contamination"
        ),
    }
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )
    return report, anchor_census
