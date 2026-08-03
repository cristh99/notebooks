"""Compatibility wrapper for OmniDocBench v1.6 page-attribute values."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import run_canary as core


def select_pages(raw_pages: Sequence[Mapping[str, Any]], count: int):
    pages = []
    for raw in raw_pages:
        try:
            page = core.ground_truth_from_page(raw)
        except (TypeError, ValueError):
            continue
        if page.language.casefold() not in {"en", "english"} or len(page.text) < 120 or not page.boxes:
            continue
        pages.append(page)
    if len(pages) < count:
        raise RuntimeError(f"only {len(pages)} eligible English pages; need {count}")
    pages.sort(key=lambda item: core.sha256_bytes(item.image_path.encode("utf-8")))
    selectors = [
        lambda page: page.has_table,
        lambda page: page.has_formula,
        lambda page: page.fuzzy_scan,
        lambda page: page.layout in {"double_column", "three_column", "1andmore_column"},
        lambda page: page.domain == "note",
        lambda page: not page.has_table and not page.has_formula and not page.fuzzy_scan,
    ]
    selected, used = [], set()
    for predicate in selectors:
        match = next((page for page in pages if page.page_id not in used and predicate(page)), None)
        if match is not None:
            selected.append(match)
            used.add(match.page_id)
        if len(selected) == count:
            return selected
    for page in pages:
        if page.page_id not in used:
            selected.append(page)
            used.add(page.page_id)
        if len(selected) == count:
            return selected
    raise AssertionError("selection denominator drift")


core.select_pages = select_pages

if __name__ == "__main__":
    core.main()
