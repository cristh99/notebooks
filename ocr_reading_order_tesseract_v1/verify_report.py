"""Recompute all metrics and decisions from frozen Tesseract observations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .run_canary import (
    GTPage,
    OCRLine,
    aggregate,
    canonical_json,
    evaluate_page,
    page_from_raw,
    resolve_annotation,
    sha256_bytes,
)


def stable_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key not in {"stable_payload_sha256", "runtime", "environment"}}


def verify(report_path: Path, annotation_path: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = stable_payload(report)
    observed_sha = sha256_bytes(canonical_json(payload).encode("utf-8"))
    if report.get("stable_payload_sha256") != observed_sha:
        errors.append("stable payload hash mismatch")

    annotation = resolve_annotation(annotation_path)
    raw = json.loads(annotation.read_text(encoding="utf-8"))
    pages = {page.page_id: page for item in raw if (page := page_from_raw(item)) is not None}
    observations = {item["page_id"]: item for item in payload["observations"]}
    rebuilt_rows: list[dict[str, Any]] = []
    for expected_row in payload["rows"]:
        page_id = expected_row["page_id"]
        page: GTPage = pages[page_id]
        observation = observations[page_id]
        lines = [
            OCRLine(
                item["line_id"],
                item["text"],
                tuple(float(value) for value in item["bbox"]),
                float(item["confidence"]),
            )
            for item in observation["lines"]
        ]
        matches = observation["matches"]
        baseline, _ = evaluate_page(page, lines, "yx_baseline", matches)
        geometry, _ = evaluate_page(page, lines, "xycut_loose", matches)
        rebuilt_rows.append({
            "page_id": page.page_id,
            "layout": page.layout,
            "domain": page.domain,
            "baseline": baseline,
            "geometry": geometry,
        })
    if canonical_json(rebuilt_rows) != canonical_json(payload["rows"]):
        errors.append("row semantic replay mismatch")
    rebuilt_aggregate = {"baseline": aggregate(rebuilt_rows, "baseline"), "geometry": aggregate(rebuilt_rows, "geometry")}
    if canonical_json(rebuilt_aggregate) != canonical_json(payload["aggregate"]):
        errors.append("aggregate semantic replay mismatch")

    baseline = rebuilt_aggregate["baseline"]
    geometry = rebuilt_aggregate["geometry"]
    baseline_edit = float(baseline["mean_conditional_read_order_edit"])
    geometry_edit = float(geometry["mean_conditional_read_order_edit"])
    improvement = (baseline_edit - geometry_edit) / baseline_edit if baseline_edit > 0 else 0.0
    harmful = sum(
        float(row["geometry"]["order"]["conditional_read_order_edit"])
        > float(row["baseline"]["order"]["conditional_read_order_edit"]) + 1e-12
        for row in rebuilt_rows
    )
    pass_gate = (
        improvement >= 0.20
        and geometry["mean_character_accuracy"] >= baseline["mean_character_accuracy"] - 1e-12
        and geometry["mean_word_accuracy"] >= baseline["mean_word_accuracy"] - 1e-12
        and harmful / len(rebuilt_rows) <= 0.10
        and geometry["mean_match_coverage"] >= 0.70
    )
    expected_decision = {
        "verdict": "PROMOTE_TO_HONDURAN_HOLDOUT" if pass_gate else "DO_NOT_PROMOTE",
        "relative_conditional_edit_improvement": improvement,
        "harmful_pages": harmful,
        "harmful_page_rate": harmful / len(rebuilt_rows),
        "next_experiment": (
            "sealed Honduran public-document holdout with frozen Tesseract plus XY-cut"
            if pass_gate
            else "geometry plus block semantics on the same frozen pages"
        ),
        "quality_gate_pass": pass_gate,
        "automatic_production_change": False,
    }
    if canonical_json(expected_decision) != canonical_json(payload["decision"]):
        errors.append("decision semantic replay mismatch")
    return {"valid": not errors, "errors": errors, "stable_payload_sha256": observed_sha}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--annotation", type=Path)
    args = parser.parse_args()
    result = verify(args.report, args.annotation)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
