"""Run the sealed, zero-cost geometry-only reading-order benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any, Mapping

from .core import (
    ANNOTATION_FILE,
    CANDIDATES,
    DATASET_ID,
    EXPECTED_ANNOTATION_SHA256,
    PINNED_REVISION,
    SCHEMA,
    SPLIT_RULE,
    canonical_json,
    decision_from_metrics,
    evaluate_candidate,
    grouped_summary,
    page_from_raw,
    selection_key,
    sha256_bytes,
    solver_receipt,
    split_name,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_annotation(annotation: Path | None) -> Path:
    if annotation is not None:
        path = annotation
    else:
        from huggingface_hub import hf_hub_download

        path = Path(
            hf_hub_download(
                DATASET_ID,
                ANNOTATION_FILE,
                repo_type="dataset",
                revision=PINNED_REVISION,
            )
        )
    digest = sha256_file(path)
    if digest != EXPECTED_ANNOTATION_SHA256:
        raise RuntimeError(f"annotation hash mismatch: {digest}")
    return path


def build_report(annotation_path: Path) -> dict[str, Any]:
    raw = json.loads(annotation_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("annotation root must be a list")
    pages = [page for item in raw if (page := page_from_raw(item)) is not None]
    development = [page for page in pages if split_name(page.page_id) == "development"]
    holdout = [page for page in pages if split_name(page.page_id) == "holdout"]
    if len(development) < 500 or len(holdout) < 100:
        raise RuntimeError("sealed split is unexpectedly small")

    development_summaries: dict[str, Any] = {}
    holdout_summaries: dict[str, Any] = {}
    holdout_rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    runtimes: dict[str, Any] = {}
    candidate_by_name = {candidate.name: candidate for candidate in CANDIDATES}
    for candidate in CANDIDATES:
        dev_summary, _dev_rows, dev_seconds = evaluate_candidate(candidate, development)
        hold_summary, hold_rows, hold_seconds = evaluate_candidate(candidate, holdout)
        development_summaries[candidate.name] = dev_summary
        holdout_summaries[candidate.name] = hold_summary
        holdout_rows_by_candidate[candidate.name] = hold_rows
        runtimes[candidate.name] = {
            "development_seconds": dev_seconds,
            "holdout_seconds": hold_seconds,
            "microseconds_per_page": (dev_seconds + hold_seconds) * 1_000_000 / max(len(pages), 1),
        }

    selected_name = min(
        development_summaries,
        key=lambda name: selection_key(candidate_by_name[name], development_summaries[name]),
    )
    selected_holdout = holdout_summaries[selected_name]
    baseline_holdout = holdout_summaries["yx_baseline"]
    selected_rows = holdout_rows_by_candidate[selected_name]
    by_layout = grouped_summary(selected_rows, "layout")
    by_domain = grouped_summary(selected_rows, "domain")
    decision = decision_from_metrics(selected_holdout, baseline_holdout, by_layout)

    stable_payload: dict[str, Any] = {
        "schema": SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": PINNED_REVISION,
            "annotation_file": ANNOTATION_FILE,
            "annotation_sha256": EXPECTED_ANNOTATION_SHA256,
        },
        "split": {
            "rule": SPLIT_RULE,
            "eligible_pages": len(pages),
            "development_pages": len(development),
            "holdout_pages": len(holdout),
            "development_ids_sha256": sha256_bytes(canonical_json(sorted(page.page_id for page in development)).encode("utf-8")),
            "holdout_ids_sha256": sha256_bytes(canonical_json(sorted(page.page_id for page in holdout)).encode("utf-8")),
        },
        "solver": solver_receipt(),
        "candidates": [
            {"name": candidate.name, "complexity_rank": candidate.complexity_rank}
            for candidate in CANDIDATES
        ],
        "selection": {
            "selected_candidate": selected_name,
            "criterion": "development lexicographic: read-order edit, pairwise accuracy, exact-page rate, complexity",
            "holdout_not_used_for_selection": True,
        },
        "development": development_summaries,
        "holdout": holdout_summaries,
        "selected_holdout_by_layout": by_layout,
        "selected_holdout_by_domain": by_domain,
        "decision": decision,
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "paid_api_used": False,
            "gpu_used": False,
            "image_pixels_used": False,
            "ocr_model_used": False,
            "logic_power_in_runtime": False,
        },
    }
    stable_sha = sha256_bytes(canonical_json(stable_payload).encode("utf-8"))
    return {
        **stable_payload,
        "stable_payload_sha256": stable_sha,
        "runtime": runtimes,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }


def write_report(report: Mapping[str, Any], output_dir: Path) -> Path:
    reports = output_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "reading_order.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (reports / "reading_order.sha256").write_text(
        f"{sha256_file(path)}  reading_order.json\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_reading_order_real_v1/run"))
    args = parser.parse_args()
    annotation_path = resolve_annotation(args.annotation)
    report = build_report(annotation_path)
    path = write_report(report, args.output_dir)
    selected = report["selection"]["selected_candidate"]
    print(
        json.dumps(
            {
                "report": str(path),
                "selected_candidate": selected,
                "holdout": report["holdout"][selected],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
