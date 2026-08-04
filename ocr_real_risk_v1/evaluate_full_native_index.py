"""Run the dual-source holdout after indexing every native PDF page.

The existing evaluator remains responsible for acquisition, image exclusion,
rasterization, crop quality, Tesseract, the frozen verifier, risk bounds and
artifacts. This wrapper changes only truth preparation: when ``pdf_page_count``
is called, it indexes the entire native text layer, seals one URL-anchored
location by SHA-256, and exposes only that page and location to the evaluator.
Documents without an anchored location never reach rasterization or OCR.
"""
from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from . import evaluate as base
from .core import Candidate, canonical_json, normalized_url, sha256_bytes
from .evaluate_dual_anchor import (
    canonical_dual_truth,
    prepare_process_disjoint_candidates,
)
from .full_native_index import (
    IndexedPage,
    isolate_selected_location,
    parse_bbox_document,
    select_dual_anchored_location,
)
from .pdf_pipeline import run
from .raw_truth_anchor import build_raw_url_anchor_map


def execute_full_native_index(
    candidates: Sequence[Candidate],
    output_dir: Path,
    max_documents: int,
    target_tokens: int,
    stage: str,
    source_paths: Sequence[Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared, document_scope = prepare_process_disjoint_candidates(candidates)
    anchor_map, anchor_census = build_raw_url_anchor_map(source_paths)
    anchor_payload = {
        url: sorted(values) for url, values in sorted(anchor_map.items())
    }
    anchor_map_sha256 = sha256_bytes(
        canonical_json(anchor_payload).encode("utf-8")
    )

    candidate_by_id = {candidate.key[:16]: candidate for candidate in prepared}
    if len(candidate_by_id) != len(prepared):
        raise RuntimeError("document-id collision in prepared candidate set")

    states: dict[str, dict[str, Any]] = {}
    totals: Counter[str] = Counter()
    current_document_id: list[str | None] = [None]
    original_page_count = base.pdf_page_count
    original_selected_pages = base.selected_pages
    original_extract_word_boxes = base.extract_word_boxes
    original_canonical_truth = base.canonical_truth

    def indexed_page_count(pdf_path: Path) -> int:
        page_count = original_page_count(pdf_path)
        document_id = pdf_path.parent.name
        current_document_id[0] = document_id
        candidate = candidate_by_id.get(document_id)
        if candidate is None:
            raise RuntimeError(f"unknown document id: {document_id}")
        output = pdf_path.parent / "native-all-pages.html"
        started = time.perf_counter()
        try:
            run(
                [
                    "pdftotext",
                    "-bbox-layout",
                    "-enc",
                    "UTF-8",
                    str(pdf_path),
                    str(output),
                ],
                timeout=180,
            )
            pages = parse_bbox_document(output)
            selected, metrics = select_dual_anchored_location(
                str(base.sha256_file(pdf_path)),
                pages,
                set(anchor_map.get(normalized_url(candidate.url), set())),
                canonical_dual_truth,
            )
            state = {
                "status": "SELECTED" if selected else "NO_DUAL_ANCHORED_LOCATION",
                "reported_page_count": page_count,
                "indexed_page_count": len(pages),
                "selected": selected,
                "metrics": metrics,
                "index_seconds": time.perf_counter() - started,
                "pages": {page.page_number: page for page in pages},
            }
            totals.update(metrics)
            totals["documents_indexed"] += 1
            if selected:
                totals["documents_with_index_candidate"] += 1
            else:
                totals["documents_without_index_candidate"] += 1
            if len(pages) != page_count:
                totals["page_count_mismatches"] += 1
        except Exception as exc:  # noqa: BLE001
            state = {
                "status": "NATIVE_INDEX_FAILED",
                "reported_page_count": page_count,
                "indexed_page_count": 0,
                "selected": None,
                "metrics": {},
                "index_seconds": time.perf_counter() - started,
                "error": f"{type(exc).__name__}: {exc}",
                "pages": {},
            }
            totals["native_index_failures"] += 1
        states[document_id] = state
        return page_count

    def indexed_selected_pages(_page_count: int) -> tuple[int, ...]:
        document_id = current_document_id[0]
        state = states.get(str(document_id), {})
        selected = state.get("selected")
        if not selected:
            return ()
        return (int(selected["page_number"]),)

    def indexed_extract_word_boxes(
        _pdf_path: Path,
        page_number: int,
        work_dir: Path,
    ) -> tuple[float, float, list[dict[str, object]]]:
        document_id = work_dir.name
        state = states.get(document_id)
        if state is None or not state.get("selected"):
            raise RuntimeError("native-index state has no selected location")
        page: IndexedPage | None = state["pages"].get(page_number)
        if page is None:
            raise RuntimeError("selected native-index page is unavailable")
        words = isolate_selected_location(
            page,
            state["selected"],
            canonical_dual_truth,
        )
        return page.width_pt, page.height_pt, words

    base.pdf_page_count = indexed_page_count
    base.selected_pages = indexed_selected_pages
    base.extract_word_boxes = indexed_extract_word_boxes
    base.canonical_truth = canonical_dual_truth
    try:
        report = base.execute(
            prepared,
            output_dir,
            max_documents,
            target_tokens,
            stage,
        )
    finally:
        base.pdf_page_count = original_page_count
        base.selected_pages = original_selected_pages
        base.extract_word_boxes = original_extract_word_boxes
        base.canonical_truth = original_canonical_truth

    for document in report["documents"]:
        state = states.get(str(document["document_id"]))
        if state is None:
            continue
        document["native_index"] = {
            key: value
            for key, value in state.items()
            if key != "pages"
        }
    for observation in report["observations"]:
        state = states.get(str(observation["document_id"]), {})
        selected = state.get("selected") or {}
        observation["native_index_selection_rank_sha256"] = selected.get(
            "selection_rank_sha256"
        )

    index_seconds = sum(
        float(state.get("index_seconds") or 0.0) for state in states.values()
    )
    report["protocol"]["ground_truth"] = (
        "one native PDF word location whose canonical digits also occur in "
        "frozen raw OCDS metadata bound to the same document URL"
    )
    report["protocol"]["dual_source_anchor"] = {
        "required": True,
        "anchor_schema": anchor_census["schema"],
        "anchor_map_sha256": anchor_map_sha256,
        "url_binding": "normalized public document URL",
        "selection_before_ocr": True,
    }
    report["protocol"]["native_text_index"] = {
        "schema": "ocr-real-risk-full-native-index/1",
        "scope": "all native-text pages, maximum 600",
        "selection": "minimum SHA-256 location rank across the full PDF",
        "pages_rendered_before_selection": 0,
        "pages_ocrd_before_selection": 0,
        "render_after_selection": "selected page only",
        "uses_ocr_for_selection": False,
    }
    report["protocol"]["document_scope"] = document_scope
    report["execution"]["full_native_index"] = {
        **dict(sorted(totals.items())),
        "index_seconds_total": index_seconds,
        "index_seconds_mean_per_indexed_document": (
            index_seconds / totals["documents_indexed"]
            if totals["documents_indexed"]
            else None
        ),
        "selected_pages_rendered": totals["documents_with_index_candidate"],
        "yield_per_attempted_document": (
            report["execution"]["documents_with_tokens"]
            / report["execution"]["documents_attempted"]
            if report["execution"]["documents_attempted"]
            else 0.0
        ),
    }
    report["anchor_census"] = anchor_census
    report.pop("stable_payload_sha256", None)
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )
    return report, anchor_census
