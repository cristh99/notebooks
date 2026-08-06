from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_science_pipeline_v4_normalize"))
import normalize_ocr as base  # noqa: E402


def find_single(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {name}, got {len(matches)}")
    return matches[0]


def verify(path: Path, expected: str, label: str) -> None:
    actual = base.sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} hash mismatch: {actual} != {expected}")


def normalize_extraction(extraction_root: Path, output_dir: Path) -> dict[str, Any]:
    receipt_path = find_single(extraction_root, "external-receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("verdict") != "PASS":
        raise RuntimeError("upstream extraction is not PASS")
    doc_manifest_path = find_single(extraction_root, "document.manifest.json")
    doc = json.loads(doc_manifest_path.read_text(encoding="utf-8"))
    if int(doc.get("processed_pages", 0)) != 3 or len(doc.get("pages", [])) != 3:
        raise RuntimeError("expected exactly three processed pages")
    document_id = f"sha256:{doc['source_sha256']}"
    documents = [{
        "schema": "canonical-document/1",
        "document_id": document_id,
        "source_sha256": doc["source_sha256"],
        "source_bytes": doc["source_bytes"],
        "source_artifact_id": doc["source_artifact_id"],
        "total_pages": doc["total_pdf_pages"],
        "processed_pages": doc["processed_pages"],
        "partial_document": doc["partial_document"],
        "renderer": doc["renderer"],
        "ocr_engine": doc["ocr_engine"],
        "languages": doc["languages"],
        "dpi": doc["dpi"],
        "psm": doc["psm"],
        "mean_confidence": doc["mean_confidence"],
        "native_token_recall": doc["native_token_recall"],
        "lineage_parent_sha256": doc["source_sha256"],
    }]
    pages: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    seen_word_ids: set[str] = set()
    extract_dir = doc_manifest_path.parent
    for expected_page in sorted(doc["pages"], key=lambda row: int(row["page_number"])):
        page = int(expected_page["page_number"])
        prefix = extract_dir / f"page_{page:04d}"
        paths = {
            "image": prefix.with_suffix(".png"),
            "text": prefix.with_suffix(".txt"),
            "tsv": prefix.with_suffix(".tsv"),
            "layout": prefix.with_suffix(".layout.json"),
            "native": prefix.with_suffix(".native.txt"),
        }
        for path in paths.values():
            if not path.is_file():
                raise RuntimeError(f"missing evidence: {path.name}")
        verify(paths["image"], expected_page["image_sha256"], f"page {page} image")
        verify(paths["text"], expected_page["ocr_text_sha256"], f"page {page} OCR")
        verify(paths["tsv"], expected_page["tsv_sha256"], f"page {page} TSV")
        verify(paths["layout"], expected_page["layout_sha256"], f"page {page} layout")
        verify(paths["native"], expected_page["native_text_sha256"], f"page {page} native")
        layout = json.loads(paths["layout"].read_text(encoding="utf-8"))
        if layout.get("page_number") != page or layout.get("word_count") != expected_page["word_count"]:
            raise RuntimeError(f"page {page} cardinality mismatch")
        width, height = int(layout["width"]), int(layout["height"])
        page_id = f"{document_id}:page:{page:04d}"
        pages.append({
            "schema": "canonical-page/1",
            "document_id": document_id,
            "page_id": page_id,
            "page_number": page,
            "width_px": width,
            "height_px": height,
            "dpi": layout["dpi"],
            "word_count": layout["word_count"],
            "mean_confidence": layout["mean_confidence"],
            "native_token_recall": layout["native_token_recall"],
            "image_sha256": expected_page["image_sha256"],
            "ocr_text_sha256": expected_page["ocr_text_sha256"],
            "tsv_sha256": expected_page["tsv_sha256"],
            "layout_sha256": expected_page["layout_sha256"],
            "native_text_sha256": expected_page["native_text_sha256"],
            "lineage_parent_sha256": expected_page["layout_sha256"],
        })
        by_line: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
        for item in layout["words"]:
            left, top = int(item["left"]), int(item["top"])
            word_width, word_height = int(item["width"]), int(item["height"])
            confidence = float(item["confidence"])
            if left < 0 or top < 0 or word_width <= 0 or word_height <= 0:
                raise RuntimeError(f"page {page} invalid word box")
            if left + word_width > width or top + word_height > height:
                raise RuntimeError(f"page {page} word box outside raster")
            if not 0 <= confidence <= 100:
                raise RuntimeError(f"page {page} invalid confidence")
            block = int(item["block_num"])
            paragraph = int(item["par_num"])
            line = int(item["line_num"])
            word_num = int(item["word_num"])
            word_id = f"{page_id}:b{block}:p{paragraph}:l{line}:w{word_num}"
            if word_id in seen_word_ids:
                raise RuntimeError(f"duplicate word ID: {word_id}")
            seen_word_ids.add(word_id)
            raw = str(item["text"])
            normalized = base.normalized_token(raw)
            row = {
                "schema": "canonical-word/1",
                "document_id": document_id,
                "page_id": page_id,
                "word_id": word_id,
                "page_number": page,
                "block_num": block,
                "paragraph_num": paragraph,
                "line_num": line,
                "word_num": word_num,
                "text_raw": raw,
                "token_normalized": normalized,
                "token_kind": base.token_kind(raw, normalized),
                "confidence": confidence,
                "left_px": left,
                "top_px": top,
                "width_px": word_width,
                "height_px": word_height,
                "lineage_parent_sha256": expected_page["layout_sha256"],
            }
            words.append(row)
            by_line[(block, paragraph, line)].append(row)
        for (block, paragraph, line), line_words in sorted(by_line.items()):
            line_words.sort(key=lambda row: (row["word_num"], row["left_px"]))
            left = min(row["left_px"] for row in line_words)
            top = min(row["top_px"] for row in line_words)
            right = max(row["left_px"] + row["width_px"] for row in line_words)
            bottom = max(row["top_px"] + row["height_px"] for row in line_words)
            lines.append({
                "schema": "canonical-line/1",
                "document_id": document_id,
                "page_id": page_id,
                "line_id": f"{page_id}:b{block}:p{paragraph}:l{line}",
                "page_number": page,
                "block_num": block,
                "paragraph_num": paragraph,
                "line_num": line,
                "text": " ".join(row["text_raw"] for row in line_words),
                "word_count": len(line_words),
                "mean_confidence": sum(row["confidence"] for row in line_words) / len(line_words),
                "left_px": left,
                "top_px": top,
                "width_px": right - left,
                "height_px": bottom - top,
                "lineage_parent_sha256": expected_page["layout_sha256"],
            })
    pages.sort(key=lambda row: row["page_number"])
    words.sort(key=lambda row: (row["page_number"], row["block_num"], row["paragraph_num"], row["line_num"], row["word_num"], row["left_px"]))
    lines.sort(key=lambda row: (row["page_number"], row["block_num"], row["paragraph_num"], row["line_num"]))
    if len(words) != sum(int(page["word_count"]) for page in doc["pages"]):
        raise RuntimeError("word cardinality mismatch")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "documents.jsonl": base.write_jsonl(output_dir / "documents.jsonl", documents),
        "pages.jsonl": base.write_jsonl(output_dir / "pages.jsonl", pages),
        "lines.jsonl": base.write_jsonl(output_dir / "lines.jsonl", lines),
        "words.jsonl": base.write_jsonl(output_dir / "words.jsonl", words),
    }
    manifest = {
        "schema": "data-science-pipeline/fresh-normalized-ocr-bundle/1",
        "upstream": {
            "external_receipt_sha256": base.sha256_file(receipt_path),
            "document_manifest_sha256": base.sha256_file(doc_manifest_path),
            "source_sha256": doc["source_sha256"],
        },
        "row_counts": {"documents": len(documents), "pages": len(pages), "lines": len(lines), "words": len(words)},
        "checks": {
            "page_hashes_verified": True,
            "cardinality_reconciled": True,
            "word_keys_unique": len(seen_word_ids) == len(words),
            "coordinates_within_raster": True,
            "confidence_ranges_valid": True,
            "deterministic_sorting": True,
            "external_cost_usd": 0.0,
        },
        "outputs": outputs,
    }
    payload = base.canonical_bytes(manifest)
    (output_dir / "normalize-manifest.json").write_bytes(payload)
    (output_dir / "normalize-manifest.sha256").write_text(f"{base.sha256_bytes(payload)}  normalize-manifest.json\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(normalize_extraction(args.extraction, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
