"""Acquire the independent Honduran holdout and freeze router observations."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ocr_reading_order_honduras_v1.prepare_holdout import (
    MAX_PDF_BYTES,
    create_contact_sheet,
    create_overlay,
    download_pdf,
    run_tesseract_blocks,
    sha256_file,
)
from ocr_reading_order_real_v1.core import canonical_json, sha256_bytes
from .router import route

SCHEMA = "ocr-reading-order-honduras-router-v1/preparation/1"
MIN_REQUIRED_DOCUMENTS = 8


def _run(command: Sequence[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def pdf_page_count(pdf_path: Path) -> int:
    output = _run(["pdfinfo", str(pdf_path)], timeout=60).stdout
    match = re.search(r"^Pages:\s+(\d+)\s*$", output, re.MULTILINE)
    if match is None:
        raise RuntimeError("pdfinfo did not report page count")
    count = int(match.group(1))
    if count <= 0:
        raise RuntimeError("PDF has no pages")
    return count


def render_selected_page(pdf_path: Path, output_prefix: Path, page_rule: str) -> tuple[Path, int, int]:
    pages = pdf_page_count(pdf_path)
    if page_rule == "FIRST":
        page_number = 1
    elif page_rule == "LAST":
        page_number = pages
    else:
        raise ValueError(f"unknown page rule: {page_rule}")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
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
        raise RuntimeError("pdftoppm did not create the selected page")
    return path, page_number, pages


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
            page_path, page_number, page_count = render_selected_page(
                pdf_path,
                output_dir / "pages" / document_id,
                str(item["page_rule"]),
            )
            blocks, ocr = run_tesseract_blocks(page_path)
            observation["page"] = {
                **ocr,
                "page_number": page_number,
                "pdf_page_count": page_count,
                "page_rule": item["page_rule"],
            }
            observation["blocks"] = blocks
            observation["page_png"] = str(page_path.relative_to(output_dir))
            if len(blocks) < 2:
                observation["status"] = "UNSCORABLE_FEWER_THAN_TWO_BLOCKS"
                observations.append(observation)
                continue
            decision = route(blocks, ocr["page_width"], ocr["page_height"])
            observation["baseline_order"] = list(decision.baseline_order)
            observation["geometry_order"] = list(decision.geometry_order)
            observation["router_order"] = list(decision.selected_order)
            observation["router_selected"] = decision.selected
            observation["router_reason"] = decision.reason
            observation["router_disagreement_blocks"] = list(decision.disagreement_blocks)
            observation["router_features"] = decision.features
            observation["status"] = "PREPARED"
            overlay_path = output_dir / "overlays" / f"{document_id}.png"
            create_overlay(
                page_path,
                blocks,
                decision.baseline_order,
                decision.geometry_order,
                overlay_path,
            )
            observation["overlay_png"] = str(overlay_path.relative_to(output_dir))
            observation["overlay_sha256"] = sha256_file(overlay_path)
            overlays.append(overlay_path)
        except Exception as exc:
            observation["status"] = "PREPARATION_FAILED"
            observation["error"] = f"{type(exc).__name__}: {exc}"
        observations.append(observation)

    prepared = [item for item in observations if item["status"] == "PREPARED"]
    if overlays:
        create_contact_sheet(overlays, output_dir / "overlays" / "CONTACT_SHEET.png")
    template = {
        "schema": "ocr-reading-order-honduras-router-v1/annotations/1",
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "instructions": (
            "For each PREPARED page, partition every block into semantic or ignored, "
            "then provide a partial-order DAG over semantic blocks. Do not add, remove, "
            "split, merge or rename blocks."
        ),
        "annotations": [
            {
                "document_id": item["document"]["id"],
                "source_pdf_sha256": item["acquisition"]["sha256"],
                "page_png_sha256": item["page"]["image_sha256"],
                "overlay_sha256": item["overlay_sha256"],
                "available_block_ids": [block["block_id"] for block in item["blocks"]],
                "semantic_block_ids": [],
                "ignored_block_ids": [],
                "correct_order": [],
                "must_precede": [],
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
        "router_spec": {
            "header_max_center_y": 0.35,
            "footer_min_center_y": 0.55,
            "body_min_column_gap": 0.08,
            "body_min_vertical_overlap": 0.20,
            "wide_spanning_ratio": 0.70,
            "frozen_before_acquisition": True,
        },
    }
    stable_sha = sha256_bytes(canonical_json(stable_payload).encode("utf-8"))
    report = {**stable_payload, "stable_payload_sha256": stable_sha}
    reports = output_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "preparation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (reports / "annotation_template.json").write_text(
        json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (reports / "preparation.sha256").write_text(
        f"{sha256_file(reports / 'preparation.json')}  preparation.json\n",
        encoding="utf-8",
    )
    if len(prepared) < MIN_REQUIRED_DOCUMENTS:
        raise RuntimeError(
            f"only {len(prepared)} documents prepared; need at least {MIN_REQUIRED_DOCUMENTS}"
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("ocr_reading_order_honduras_router_v1/manifest.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_reading_order_honduras_router_v1/run"),
    )
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
                "router_choices": {
                    item["document"]["id"]: {
                        "selected": item.get("router_selected"),
                        "reason": item.get("router_reason"),
                    }
                    for item in report["observations"]
                    if item["status"] == "PREPARED"
                },
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
