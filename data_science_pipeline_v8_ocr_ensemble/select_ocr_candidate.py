from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any, Mapping, Sequence

getcontext().prec = 40

CANDIDATE_NAMES = (
    "auto_300_psm3",
    "balanced_200_psm6",
    "sparse_300_psm11",
)
TITLE_TOKENS = ("CONCEPTOS", "BASICOS", "PACC")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_single(root: Path, name: str) -> Path:
    matches = sorted(path for path in root.rglob(name) if path.is_file())
    if len(matches) != 1:
        raise RuntimeError(f"expected one {name} below {root}, got {len(matches)}")
    return matches[0]


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", unaccented.upper()).strip()


def bounded_word_term(word_count: int) -> Decimal:
    if word_count < 0:
        raise ValueError("word_count must be non-negative")
    return Decimal(word_count) / Decimal(word_count + 1)


def score_candidate(mean_confidence: float, native_token_recall: float, word_count: int) -> Decimal:
    return (
        Decimal(str(mean_confidence))
        + Decimal(20) * Decimal(str(native_token_recall))
        + bounded_word_term(word_count)
    )


def choose_candidate(summaries: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    eligible = [summary for summary in summaries if bool(summary["eligible"])]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda summary: (-Decimal(str(summary["score"])), str(summary["candidate_name"])),
    )[0]


def archive_summary(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in {"external-receipt.json", "external-receipt.sha256"}:
            continue
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    payload = canonical_bytes(rows)
    return {
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "members": rows,
    }


def inspect_candidate(name: str, root: Path, source_host: str) -> dict[str, Any]:
    if name not in CANDIDATE_NAMES:
        raise ValueError(f"unexpected candidate: {name}")
    manifest_path = find_single(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = next((item for item in manifest.get("stage_records", []) if item.get("stage") == "extract"), None)
    if record is None:
        raise RuntimeError(f"{name}: extract record missing")
    document_path = find_single(root, "document.manifest.json")
    document = json.loads(document_path.read_text(encoding="utf-8"))
    text_files = sorted(
        path for path in root.rglob("page_*.txt")
        if path.is_file() and not path.name.endswith(".native.txt")
    )
    if len(text_files) != 3:
        raise RuntimeError(f"{name}: expected three OCR text files, got {len(text_files)}")
    texts = [path.read_text(encoding="utf-8", errors="replace") for path in text_files]
    normalized = normalize_text("\n".join(texts))
    token_set = set(normalized.split())
    title_hits = sorted(token for token in TITLE_TOKENS if token in token_set)
    metrics = record.get("metrics", {})
    mean_confidence = float(metrics.get("mean_confidence", -1.0))
    native_token_recall = float(metrics.get("native_token_recall", -1.0))
    word_count = sum(int(page.get("word_count", 0)) for page in document.get("pages", []))
    quarantined = [item for item in manifest.get("artifacts", []) if item.get("state") == "quarantined"]
    empty_pages = sum(1 for text in texts if not text.strip())
    checks = {
        "trusted_source_host": source_host == "oncae.gob.hn",
        "pages_three": int(metrics.get("pages_rasterized", -1)) == 3 and int(metrics.get("pages_ocr", -1)) == 3,
        "document_pages_three": int(document.get("processed_pages", -1)) == 3 and len(document.get("pages", [])) == 3,
        "confidence_gate": mean_confidence >= 55.0,
        "recall_gate": native_token_recall >= 0.50,
        "pacc_token": "PACC" in token_set,
        "title_group_quorum": len(title_hits) >= 2,
        "year_2023": "2023" in token_set,
        "empty_pages_zero": empty_pages == 0,
        "quarantine_zero": not quarantined,
        "cost_zero": float(record.get("cost_usd", metrics.get("cost_usd", -1.0))) == 0.0,
        "word_count_positive": word_count > 0,
    }
    score = score_candidate(mean_confidence, native_token_recall, word_count)
    return {
        "schema": "data-science-pipeline/ocr-candidate-summary/1",
        "candidate_name": name,
        "eligible": all(checks.values()),
        "score": format(score, ".18f"),
        "score_components": {
            "mean_confidence": mean_confidence,
            "native_token_recall": native_token_recall,
            "native_token_recall_weighted": float(Decimal(20) * Decimal(str(native_token_recall))),
            "word_count": word_count,
            "bounded_word_count": format(bounded_word_term(word_count), ".18f"),
        },
        "checks": checks,
        "identity_hits": {"title_group": title_hits, "year": ["2023"] if "2023" in token_set else []},
        "source_pdf_sha256": document["source_sha256"],
        "document_manifest_sha256": sha256_file(document_path),
        "extraction_manifest_sha256": sha256_file(manifest_path),
        "archive": archive_summary(root),
    }


def select(candidates_root: Path, output_dir: Path, source_host: str) -> dict[str, Any]:
    summaries = [inspect_candidate(name, candidates_root / name, source_host) for name in CANDIDATE_NAMES]
    selected = choose_candidate(summaries)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_payload = canonical_bytes(summaries)
    (output_dir / "candidate-summaries.json").write_bytes(summary_payload)
    (output_dir / "candidate-summaries.sha256").write_text(
        f"{hashlib.sha256(summary_payload).hexdigest()}  candidate-summaries.json\n",
        encoding="utf-8",
    )
    selection = {
        "schema": "data-science-pipeline/ocr-ensemble-selection/1",
        "verdict": "PASS" if selected is not None else "FAIL_NO_ELIGIBLE_CANDIDATE",
        "score_formula": "mean_confidence + 20*native_token_recall + word_count/(1+word_count)",
        "selected_candidate": None if selected is None else selected["candidate_name"],
        "selected_score": None if selected is None else selected["score"],
        "eligible_candidates": [summary["candidate_name"] for summary in summaries if summary["eligible"]],
        "candidate_summary_sha256": hashlib.sha256(summary_payload).hexdigest(),
        "post_result_retuning_permitted": False,
        "external_cost_usd": 0.0,
    }
    selection_payload = canonical_bytes(selection)
    (output_dir / "selection.json").write_bytes(selection_payload)
    (output_dir / "selection.sha256").write_text(
        f"{hashlib.sha256(selection_payload).hexdigest()}  selection.json\n",
        encoding="utf-8",
    )
    if selected is None:
        return selection
    selected_root = candidates_root / str(selected["candidate_name"])
    receipt = {
        "schema": "data-science-pipeline/selected-ocr-extraction-receipt/1",
        "verdict": "PASS",
        "selected_candidate": selected["candidate_name"],
        "selected_score": selected["score"],
        "checks": selected["checks"],
        "identity_hits": selected["identity_hits"],
        "metrics": selected["score_components"],
        "source_pdf_sha256": selected["source_pdf_sha256"],
        "candidate_summary_sha256": hashlib.sha256(summary_payload).hexdigest(),
        "candidate_archive_manifest_sha256": selected["archive"]["manifest_sha256"],
        "post_result_retuning_permitted": False,
        "external_cost_usd": 0.0,
    }
    receipt_payload = canonical_bytes(receipt)
    (selected_root / "external-receipt.json").write_bytes(receipt_payload)
    (selected_root / "external-receipt.sha256").write_text(
        f"{hashlib.sha256(receipt_payload).hexdigest()}  external-receipt.json\n",
        encoding="utf-8",
    )
    return selection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-host", required=True)
    args = parser.parse_args()
    result = select(args.candidates_root, args.output, args.source_host)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if result["verdict"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
