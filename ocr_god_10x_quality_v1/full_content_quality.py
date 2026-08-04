"""Repair OCR quality measurement by evaluating complete visible content.

The earlier development benchmark compared OCR output only with paragraph-like
annotations. OmniDocBench also labels table HTML and formula LaTeX. Correctly
recognized cell text was therefore counted as false-positive OCR. This module
rebuilds page references from all visible semantic content and preserves the
old text-only metrics for comparison.

No OCR is executed here. The exact frozen Stage 1 observations are replayed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import platform
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ocr_reading_order_real_v1.core import (
    ANNOTATION_FILE,
    DATASET_ID,
    EXPECTED_ANNOTATION_SHA256,
    PINNED_REVISION,
)

SCHEMA = "ocr-god-10x/full-content-quality/1"
WORD_RE = re.compile(
    r"\d+(?:[.,:/-]\d+)*|[^\W\d_]+(?:['’\-][^\W\d_]+)*",
    re.UNICODE,
)
NUMBER_RE = re.compile(r"(?<!\w)[+-]?(?:\d[\d\s.,:/\-]*\d|\d)(?!\w)")
TAG_RE = re.compile(r"<[^>]+>")
LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+\*?")
SPACE_RE = re.compile(r"\s+")

TABLE_CATEGORIES = frozenset({"table"})
FORMULA_CATEGORIES = frozenset({"equation_isolated", "equation_semantic"})
NON_SEMANTIC_CATEGORIES = frozenset(
    {
        "figure",
        "chart_mask",
        "table_mask",
        "text_mask",
        "organic_chemical_formula_mask",
        "algorithm_mask",
        "unknown_mask",
        "need_mask",
        "abandon",
    }
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = (
        text.replace("\u00ad", "")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )
    return SPACE_RE.sub(" ", text).strip()


def html_to_plain(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(
        r"(?i)</?(?:td|th|tr|p|div|br|li|table|thead|tbody|tfoot)[^>]*>",
        " ",
        text,
    )
    text = TAG_RE.sub(" ", text)
    return normalize_text(text)


def latex_to_plain(value: str) -> str:
    text = html.unescape(value or "")
    # Preserve arguments while removing command names and presentation syntax.
    text = re.sub(
        r"\\(?:text|textrm|textbf|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}",
        r" \1 ",
        text,
    )
    text = LATEX_COMMAND_RE.sub(" ", text)
    text = re.sub(r"[{}\[\]$^_&\\|]", " ", text)
    text = re.sub(r"[=+*/<>≈≠≤≥×÷±→←↔]", " ", text)
    return normalize_text(text)


def canonical_text(value: str) -> str:
    return normalize_text(value).casefold()


def word_tokens(value: str) -> list[str]:
    return WORD_RE.findall(canonical_text(value))


def canonical_number(token: str) -> str:
    value = canonical_text(token).replace(" ", "").strip(".,;:")
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
        value = value.replace(",", "")
    return value


def number_tokens(value: str) -> list[str]:
    return [canonical_number(match.group(0)) for match in NUMBER_RE.finditer(value)]


def counter_metrics(
    reference: Sequence[str],
    prediction: Sequence[str],
) -> dict[str, float | int]:
    ref = Counter(reference)
    pred = Counter(prediction)
    true_positive = sum((ref & pred).values())
    reference_count = sum(ref.values())
    prediction_count = sum(pred.values())
    precision = (
        true_positive / prediction_count
        if prediction_count
        else float(reference_count == 0)
    )
    recall = (
        true_positive / reference_count
        if reference_count
        else float(prediction_count == 0)
    )
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "true_positive": true_positive,
        "reference_count": reference_count,
        "prediction_count": prediction_count,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "error": 1.0 - f1,
    }


def union_groups(relations: Sequence[Mapping[str, Any]]) -> list[set[str]]:
    groups: list[set[str]] = []
    for relation in relations:
        if relation.get("relation_type") != "truncated":
            continue
        source = str(relation.get("source_anno_id"))
        target = str(relation.get("target_anno_id"))
        merged = {source, target}
        remaining: list[set[str]] = []
        for group in groups:
            if group & merged:
                merged |= group
            else:
                remaining.append(group)
        remaining.append(merged)
        groups = remaining
    return groups


def item_payload(item: Mapping[str, Any]) -> dict[str, str]:
    category = str(item.get("category_type") or "")
    if category in NON_SEMANTIC_CATEGORIES:
        return {"text": "", "table": "", "formula": ""}

    raw_text = normalize_text(str(item.get("text") or ""))
    raw_html = html_to_plain(str(item.get("html") or ""))
    raw_latex = latex_to_plain(str(item.get("latex") or ""))

    if category in TABLE_CATEGORIES:
        table = raw_html or raw_latex or raw_text
        return {"text": "", "table": table, "formula": ""}
    if category in FORMULA_CATEGORIES:
        formula = raw_latex or raw_text
        return {"text": "", "table": "", "formula": formula}
    if raw_text:
        return {"text": raw_text, "table": "", "formula": ""}

    span_text: list[str] = []
    span_formula: list[str] = []
    for span in item.get("line_with_spans") or []:
        if span.get("ignore", False):
            continue
        span_category = str(span.get("category_type") or "")
        if span_category == "equation_ignore":
            continue
        if span_category == "equation_inline":
            plain = latex_to_plain(str(span.get("latex") or span.get("text") or ""))
            if plain:
                span_formula.append(plain)
        else:
            plain = normalize_text(str(span.get("text") or ""))
            if plain:
                span_text.append(plain)
    return {
        "text": normalize_text(" ".join(span_text)),
        "table": "",
        "formula": normalize_text(" ".join(span_formula)),
    }


def page_reference(raw_page: Mapping[str, Any]) -> dict[str, Any]:
    items = [
        item
        for item in raw_page.get("layout_dets") or []
        if not item.get("ignore", False)
    ]
    item_by_id = {
        str(item.get("anno_id")): item
        for item in items
        if item.get("anno_id") is not None
    }
    truncated_groups = union_groups(
        (raw_page.get("extra") or {}).get("relation") or []
    )
    group_by_id: dict[str, set[str]] = {}
    for group in truncated_groups:
        for anno_id in group:
            group_by_id[anno_id] = group

    processed_groups: set[tuple[str, ...]] = set()
    records: list[tuple[int, str, dict[str, str]]] = []
    for index, item in enumerate(items):
        anno_id = str(item.get("anno_id"))
        group = group_by_id.get(anno_id)
        if group:
            key = tuple(sorted(group))
            if key in processed_groups:
                continue
            processed_groups.add(key)
            members = [
                item_by_id[value]
                for value in group
                if value in item_by_id
            ]
            members.sort(
                key=lambda member: (
                    int(member.get("order") or 0),
                    str(member.get("anno_id")),
                )
            )
            payloads = [item_payload(member) for member in members]
            payload = {
                kind: normalize_text(
                    " ".join(value[kind] for value in payloads if value[kind])
                )
                for kind in ("text", "table", "formula")
            }
            order = min(
                (int(member.get("order") or 0) for member in members),
                default=index,
            )
            records.append((order, key[0], payload))
        else:
            records.append(
                (
                    int(item.get("order") or 0),
                    anno_id,
                    item_payload(item),
                )
            )

    records.sort(key=lambda row: (row[0], row[1]))
    text_parts = [row[2]["text"] for row in records if row[2]["text"]]
    table_parts = [row[2]["table"] for row in records if row[2]["table"]]
    formula_parts = [
        row[2]["formula"] for row in records if row[2]["formula"]
    ]
    text = normalize_text("\n".join(text_parts))
    table = normalize_text("\n".join(table_parts))
    formula = normalize_text("\n".join(formula_parts))
    full = normalize_text("\n".join(value for value in (text, table, formula) if value))
    return {
        "text": text,
        "table": table,
        "formula": formula,
        "full": full,
        "blocks": {
            "text": len(text_parts),
            "table": len(table_parts),
            "formula": len(formula_parts),
        },
        "sha256": {
            "text": sha256_bytes(text.encode("utf-8")),
            "table": sha256_bytes(table.encode("utf-8")),
            "formula": sha256_bytes(formula.encode("utf-8")),
            "full": sha256_bytes(full.encode("utf-8")),
        },
    }


def annotation_map(raw_pages: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    mapping: dict[str, Mapping[str, Any]] = {}
    basename_counts: Counter[str] = Counter()
    for page in raw_pages:
        page_id = str((page.get("page_info") or {}).get("image_path") or "")
        if not page_id:
            continue
        mapping[page_id] = page
        basename_counts[Path(page_id).name] += 1
    for page in raw_pages:
        page_id = str((page.get("page_info") or {}).get("image_path") or "")
        if page_id and basename_counts[Path(page_id).name] == 1:
            mapping.setdefault(Path(page_id).name, page)
    return mapping


def newly_valid_count(
    old_reference: Sequence[str],
    full_reference: Sequence[str],
    prediction: Sequence[str],
) -> int:
    old_ref = Counter(old_reference)
    full_ref = Counter(full_reference)
    pred = Counter(prediction)
    old_false_positive = pred - old_ref
    added_reference = full_ref - old_ref
    return sum((old_false_positive & added_reference).values())


def micro_metric(
    observations: Sequence[Mapping[str, Any]],
    engine: str,
    reference_key: str,
    token_fn: Any,
) -> dict[str, float | int]:
    reference: list[str] = []
    prediction: list[str] = []
    for row in observations:
        reference.extend(token_fn(str(row["reference"][reference_key])))
        prediction.extend(token_fn(str(row["engines"][engine])))
    return counter_metrics(reference, prediction)


def quality_gate(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_word_error = float(baseline["full_word"]["error"])
    baseline_numeric_error = float(baseline["full_numeric"]["error"])
    candidate_word_error = float(candidate["full_word"]["error"])
    candidate_numeric_error = float(candidate["full_numeric"]["error"])
    word_10x = candidate_word_error <= baseline_word_error / 10.0 + 1e-15
    numeric_10x = (
        candidate_numeric_error
        <= baseline_numeric_error / 10.0 + 1e-15
    )
    return {
        "word_error_reduction_factor": (
            baseline_word_error / candidate_word_error
            if candidate_word_error > 1e-15
            else None
        ),
        "numeric_error_reduction_factor": (
            baseline_numeric_error / candidate_numeric_error
            if candidate_numeric_error > 1e-15
            else None
        ),
        "word_quality_10x": word_10x,
        "numeric_quality_10x": numeric_10x,
        "both_quality_10x": word_10x and numeric_10x,
    }


def resolve_annotation(annotation_path: Path | None) -> Path:
    if annotation_path is not None:
        path = annotation_path
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


def build_report(
    stage1_report_path: Path,
    annotation_path: Path | None = None,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    annotation = resolve_annotation(annotation_path)
    raw_pages = json.loads(annotation.read_text(encoding="utf-8"))
    raw_by_id = annotation_map(raw_pages)
    stage1 = json.loads(stage1_report_path.read_text(encoding="utf-8"))
    stage1_rows = stage1.get("observations") or []
    if len(stage1_rows) != 20:
        raise RuntimeError(f"expected 20 Stage 1 pages, found {len(stage1_rows)}")

    engine_names = sorted((stage1_rows[0].get("engines") or {}).keys())
    observations: list[dict[str, Any]] = []
    for row in stage1_rows:
        page_id = str(row.get("page_id") or "")
        raw_page = raw_by_id.get(page_id) or raw_by_id.get(Path(page_id).name)
        if raw_page is None:
            raise KeyError(f"annotation page not found: {page_id}")
        reference = page_reference(raw_page)
        prior_reference = normalize_text(str(row.get("reference_text") or ""))
        engines: dict[str, str] = {}
        metrics: dict[str, Any] = {}
        for engine in engine_names:
            prediction = normalize_text(
                str((row.get("engines") or {})[engine].get("text") or "")
            )
            engines[engine] = prediction
            old_words = word_tokens(prior_reference)
            full_words = word_tokens(reference["full"])
            pred_words = word_tokens(prediction)
            old_numbers = number_tokens(prior_reference)
            full_numbers = number_tokens(reference["full"])
            pred_numbers = number_tokens(prediction)
            metrics[engine] = {
                "text_only_word": counter_metrics(old_words, pred_words),
                "full_word": counter_metrics(full_words, pred_words),
                "text_only_numeric": counter_metrics(
                    old_numbers,
                    pred_numbers,
                ),
                "full_numeric": counter_metrics(
                    full_numbers,
                    pred_numbers,
                ),
                "table_word_recall": counter_metrics(
                    word_tokens(reference["table"]),
                    pred_words,
                )["recall"],
                "formula_word_recall": counter_metrics(
                    word_tokens(reference["formula"]),
                    pred_words,
                )["recall"],
                "newly_valid_words": newly_valid_count(
                    old_words,
                    full_words,
                    pred_words,
                ),
                "newly_valid_numbers": newly_valid_count(
                    old_numbers,
                    full_numbers,
                    pred_numbers,
                ),
            }
        observations.append(
            {
                "page_id": page_id,
                "layout": row.get("layout"),
                "domain": row.get("domain"),
                "reference": {
                    **reference,
                    "prior_text_only": prior_reference,
                    "prior_text_only_sha256": sha256_bytes(
                        prior_reference.encode("utf-8")
                    ),
                },
                "engines": engines,
                "metrics": metrics,
            }
        )

    aggregate: dict[str, Any] = {}
    for engine in engine_names:
        aggregate[engine] = {
            "text_only_word": micro_metric(
                observations,
                engine,
                "prior_text_only",
                word_tokens,
            ),
            "full_word": micro_metric(
                observations,
                engine,
                "full",
                word_tokens,
            ),
            "text_only_numeric": micro_metric(
                observations,
                engine,
                "prior_text_only",
                number_tokens,
            ),
            "full_numeric": micro_metric(
                observations,
                engine,
                "full",
                number_tokens,
            ),
            "table_word_recall": micro_metric(
                observations,
                engine,
                "table",
                word_tokens,
            )["recall"],
            "formula_word_recall": micro_metric(
                observations,
                engine,
                "formula",
                word_tokens,
            )["recall"],
            "newly_valid_words": sum(
                int(row["metrics"][engine]["newly_valid_words"])
                for row in observations
            ),
            "newly_valid_numbers": sum(
                int(row["metrics"][engine]["newly_valid_numbers"])
                for row in observations
            ),
        }

    baseline_name = "tesseract"
    baseline = aggregate[baseline_name]
    gates = {
        engine: quality_gate(baseline, metrics)
        for engine, metrics in aggregate.items()
        if engine != baseline_name
    }
    passing = sorted(
        engine
        for engine, gate in gates.items()
        if gate["both_quality_10x"]
    )
    best_word = max(
        engine_names,
        key=lambda engine: (
            float(aggregate[engine]["full_word"]["f1"]),
            float(aggregate[engine]["full_numeric"]["f1"]),
            engine,
        ),
    )
    best_numeric = max(
        engine_names,
        key=lambda engine: (
            float(aggregate[engine]["full_numeric"]["f1"]),
            float(aggregate[engine]["full_word"]["f1"]),
            engine,
        ),
    )
    reclassified_words = sum(
        int(aggregate[engine]["newly_valid_words"])
        for engine in engine_names
    )
    if passing:
        verdict = "FULL_CONTENT_QUALITY_10X_OBSERVED"
        next_experiment = (
            "bind the passing quality route to a same-runner speed gate on "
            "a new untouched holdout"
        )
    else:
        verdict = "METRIC_REPAIRED_QUALITY_10X_NOT_REACHED"
        next_experiment = (
            "evaluate a Latin-specialized recognizer and structured table "
            "reconstruction under the repaired metric"
        )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "stage1_report_sha256": sha256_file(stage1_report_path),
            "stage1_stable_payload_sha256": stage1.get(
                "stable_payload_sha256"
            ),
            "stage1_artifact_sha256": artifact_sha256,
            "dataset_id": DATASET_ID,
            "dataset_revision": PINNED_REVISION,
            "annotation_file": ANNOTATION_FILE,
            "annotation_sha256": EXPECTED_ANNOTATION_SHA256,
        },
        "measurement_repair": {
            "old_reference": "paragraph-like text categories only",
            "new_reference": (
                "all visible semantic text plus table HTML and formula LaTeX "
                "converted to plain comparable tokens"
            ),
            "order_independent": True,
            "ocr_rerun": False,
            "pages": len(observations),
            "engines": engine_names,
            "total_reclassified_words_across_engines": reclassified_words,
        },
        "observations": observations,
        "aggregate": aggregate,
        "decision": {
            "verdict": verdict,
            "baseline": baseline_name,
            "best_full_word_engine": best_word,
            "best_full_numeric_engine": best_numeric,
            "passing_quality_10x_candidates": passing,
            "gates": gates,
            "next_experiment": next_experiment,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "logic_power_in_runtime": False,
        },
    }
    stable = canonical_json(payload).encode("utf-8")
    payload["stable_payload_sha256"] = sha256_bytes(stable)
    payload["environment"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1-report", type=Path, required=True)
    parser.add_argument("--annotation", type=Path)
    parser.add_argument("--artifact-sha256")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_god_10x_quality_v1/run"),
    )
    args = parser.parse_args()
    report = build_report(
        args.stage1_report,
        args.annotation,
        args.artifact_sha256,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "full_content_quality.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "full_content_quality.sha256").write_text(
        f"{sha256_file(path)}  full_content_quality.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "aggregate": report["aggregate"],
                "decision": report["decision"],
                "measurement_repair": report["measurement_repair"],
                "stable_payload_sha256": report[
                    "stable_payload_sha256"
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
