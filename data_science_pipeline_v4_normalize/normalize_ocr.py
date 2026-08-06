from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "data-science-pipeline/normalized-ocr-bundle/1"
EXPECTED_UPSTREAM_RUN = 31062120497
EXPECTED_UPSTREAM_ARTIFACT = 8952494053
EXPECTED_UPSTREAM_ARTIFACT_SHA256 = "e838bf457f1f83f9b547b52c4b6c3e9e28ff9357615a5ecfc2a09ccc3c27f692"
EXPECTED_SOURCE_SHA256 = "5f278ec51106212a95a6f8c135cdfb8376724daab1e49b9ca0d3879543d11e85"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def normalized_token(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", ascii_text.casefold())


def token_kind(raw: str, normalized: str) -> str:
    if not normalized:
        return "punctuation"
    if normalized.isdigit():
        return "number"
    if normalized.isalpha():
        return "word"
    return "alphanumeric"


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    payload = b"".join(canonical_bytes(dict(row)) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": path.name, "bytes": len(payload), "sha256": sha256_bytes(payload), "rows": payload.count(b"\n")}


def _single(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {name}, found {len(matches)}")
    return matches[0]


def _verify(path: Path, expected: str, label: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} hash mismatch: {actual} != {expected}")


def normalize_bundle(bundle_root: Path, output_dir: Path) -> dict[str, Any]:
    receipt_path = _single(bundle_root, "external-receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("verdict") != "PASS":
        raise RuntimeError("upstream extraction receipt is not PASS")
    if receipt.get("github_run_id") != EXPECTED_UPSTREAM_RUN:
        raise RuntimeError("unexpected upstream run")
    doc_manifest_path = _single(bundle_root, "document.manifest.json")
    _verify(doc_manifest_path, "d27d086166f1e3e9444d2e26429f2b7622bc868c0cf888ed24f43fd63a157569", "document manifest")
    doc = json.loads(doc_manifest_path.read_text(encoding="utf-8"))
    if doc.get("source_sha256") != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("unexpected source PDF")
    if doc.get("processed_pages") != 3 or len(doc.get("pages", [])) != 3:
        raise RuntimeError("expected exactly three extracted pages")

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

    for expected_page in sorted(doc["pages"], key=lambda x: x["page_number"]):
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
                raise RuntimeError(f"missing page evidence: {path.name}")
        _verify(paths["image"], expected_page["image_sha256"], f"page {page} image")
        _verify(paths["text"], expected_page["ocr_text_sha256"], f"page {page} OCR")
        _verify(paths["tsv"], expected_page["tsv_sha256"], f"page {page} TSV")
        _verify(paths["layout"], expected_page["layout_sha256"], f"page {page} layout")
        _verify(paths["native"], expected_page["native_text_sha256"], f"page {page} native")
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
                raise RuntimeError(f"page {page} confidence outside range")
            block = int(item["block_num"])
            paragraph = int(item["par_num"])
            line = int(item["line_num"])
            word_num = int(item["word_num"])
            word_id = f"{page_id}:b{block}:p{paragraph}:l{line}:w{word_num}"
            if word_id in seen_word_ids:
                raise RuntimeError(f"duplicate word key: {word_id}")
            seen_word_ids.add(word_id)
            raw = str(item["text"])
            norm = normalized_token(raw)
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
                "token_normalized": norm,
                "token_kind": token_kind(raw, norm),
                "confidence": confidence,
                "left_px": left,
                "top_px": top,
                "width_px": word_width,
                "height_px": word_height,
                "lineage_parent_sha256": expected_page["layout_sha256"],
            }
            words.append(row)
            by_line[(block, paragraph, line)].append(row)
        if not by_line:
            raise RuntimeError(f"page {page} has no lines")
        for (block, paragraph, line), line_words in sorted(by_line.items()):
            line_words.sort(key=lambda x: (x["word_num"], x["left_px"]))
            left = min(x["left_px"] for x in line_words)
            top = min(x["top_px"] for x in line_words)
            right = max(x["left_px"] + x["width_px"] for x in line_words)
            bottom = max(x["top_px"] + x["height_px"] for x in line_words)
            lines.append({
                "schema": "canonical-line/1",
                "document_id": document_id,
                "page_id": page_id,
                "line_id": f"{page_id}:b{block}:p{paragraph}:l{line}",
                "page_number": page,
                "block_num": block,
                "paragraph_num": paragraph,
                "line_num": line,
                "text": " ".join(x["text_raw"] for x in line_words),
                "word_count": len(line_words),
                "mean_confidence": sum(x["confidence"] for x in line_words) / len(line_words),
                "left_px": left,
                "top_px": top,
                "width_px": right - left,
                "height_px": bottom - top,
                "lineage_parent_sha256": expected_page["layout_sha256"],
            })

    pages.sort(key=lambda x: x["page_number"])
    words.sort(key=lambda x: (x["page_number"], x["block_num"], x["paragraph_num"], x["line_num"], x["word_num"], x["left_px"]))
    lines.sort(key=lambda x: (x["page_number"], x["block_num"], x["paragraph_num"], x["line_num"]))
    if len(words) != sum(int(x["word_count"]) for x in doc["pages"]):
        raise RuntimeError("word total does not match document manifest")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "documents.jsonl": write_jsonl(output_dir / "documents.jsonl", documents),
        "pages.jsonl": write_jsonl(output_dir / "pages.jsonl", pages),
        "lines.jsonl": write_jsonl(output_dir / "lines.jsonl", lines),
        "words.jsonl": write_jsonl(output_dir / "words.jsonl", words),
    }
    manifest = {
        "schema": SCHEMA,
        "upstream": {
            "run_id": EXPECTED_UPSTREAM_RUN,
            "artifact_id": EXPECTED_UPSTREAM_ARTIFACT,
            "artifact_zip_sha256": EXPECTED_UPSTREAM_ARTIFACT_SHA256,
            "external_receipt_sha256": sha256_file(receipt_path),
            "document_manifest_sha256": sha256_file(doc_manifest_path),
            "source_sha256": doc["source_sha256"],
        },
        "row_counts": {"documents": len(documents), "pages": len(pages), "lines": len(lines), "words": len(words)},
        "checks": {
            "source_hash_verified": True,
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
    manifest_payload = canonical_bytes(manifest)
    (output_dir / "normalize-manifest.json").write_bytes(manifest_payload)
    (output_dir / "normalize-manifest.sha256").write_text(f"{sha256_bytes(manifest_payload)}  normalize-manifest.json\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(normalize_bundle(args.bundle, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
