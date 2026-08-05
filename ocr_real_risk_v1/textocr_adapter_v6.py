"""Frozen TextOCR schema adapter and metadata-only numeric census.

The adapter is bundled before the TextOCR Parquet footer or rows are opened.
It expects one row per image with `texts`, `bboxes`, `polygons`, and
`num_text_regions`. Exactly one 4-12 digit ASCII transcription is selected per
row by a deterministic SHA-256 rank. Image bytes are intentionally excluded
from the census query and are never used for selection.
"""
from __future__ import annotations

import argparse
import json
import math
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import canonical_json, sha256_bytes
from .sroie_natural_holdout import stable_payload

DATASET_ID = "Yesianrohn/OCR-Data"
DATASET_REVISION = "2b1f8aab9fbba3b5be07e2cae9e3e9c43fe5487c"
COMPONENT = "TextOCR"
SOURCE_PATH = "data/TextOCR-00000-of-00001.parquet"
SOURCE_SHA256 = "f2d50b206923e4bdb70e9200e92b31bd8626acc37466bab8379fa48bb9c62823"
SOURCE_SIZE_BYTES = 6_196_529_116
SOURCE_URL = (
    "https://huggingface.co/datasets/Yesianrohn/OCR-Data/resolve/"
    f"{DATASET_REVISION}/{SOURCE_PATH}?download=true"
)
ADAPTER_SCHEMA = "ocr-textocr-numeric-adapter/6"
CENSUS_SCHEMA = "ocr-textocr-numeric-census/6"
EXPECTED_COLUMNS = ("image", "texts", "bboxes", "polygons", "num_text_regions")
CENSUS_COLUMNS = ("texts", "bboxes", "polygons", "num_text_regions")
MIN_DIGITS = 4
MAX_DIGITS = 12
YEAR_MIN = 1900
YEAR_MAX = 2099
MINIMUM_SELECTED = 3000
MINIMUM_ACCEPTED = 900
DEVELOPMENT_ACCEPTANCE_RATE = 472 / 1720


def canonical_numeric_text(value: object) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return None
    digits: list[str] = []
    for character in text:
        if "0" <= character <= "9":
            digits.append(character)
            continue
        category = unicodedata.category(character)
        if (
            character.isspace()
            or character in ",.:'’`/-_()[]{}+"
            or category in {"Sc", "Pd", "Po", "Ps", "Pe"}
        ):
            continue
        return None
    canonical = "".join(digits)
    if not MIN_DIGITS <= len(canonical) <= MAX_DIGITS:
        return None
    if len(set(canonical)) == 1:
        return None
    if len(canonical) == 4 and YEAR_MIN <= int(canonical) <= YEAR_MAX:
        return None
    return canonical


def _sequence(value: object, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        raise RuntimeError(f"TextOCR {field} must be a sequence")
    return list(value)


def _finite_numbers(value: object, field: str) -> list[float]:
    raw = _sequence(value, field)
    try:
        numbers = [float(item) for item in raw]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"TextOCR {field} contains a non-numeric value") from exc
    if not all(math.isfinite(item) for item in numbers):
        raise RuntimeError(f"TextOCR {field} contains a non-finite value")
    return numbers


def polygon_envelope(value: object) -> tuple[float, float, float, float]:
    raw = _sequence(value, "polygon")
    if not raw:
        raise RuntimeError("TextOCR polygon is empty")
    if all(
        isinstance(item, Sequence)
        and not isinstance(item, (str, bytes, bytearray, memoryview))
        for item in raw
    ):
        points: list[float] = []
        for point in raw:
            point_values = _finite_numbers(point, "polygon point")
            if len(point_values) != 2:
                raise RuntimeError("TextOCR polygon point must contain x and y")
            points.extend(point_values)
    else:
        points = _finite_numbers(raw, "polygon")
    if len(points) < 8 or len(points) % 2:
        raise RuntimeError(
            "TextOCR polygon must contain at least four x/y points"
        )
    xs = points[0::2]
    ys = points[1::2]
    envelope = (min(xs), min(ys), max(xs), max(ys))
    if envelope[2] <= envelope[0] or envelope[3] <= envelope[1]:
        raise RuntimeError("TextOCR polygon has non-positive extent")
    return envelope


def _bbox_iou(
    first: Sequence[float], second: Sequence[float]
) -> float:
    x0 = max(float(first[0]), float(second[0]))
    y0 = max(float(first[1]), float(second[1]))
    x1 = min(float(first[2]), float(second[2]))
    y1 = min(float(first[3]), float(second[3]))
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    first_area = max(
        1e-12,
        (float(first[2]) - float(first[0]))
        * (float(first[3]) - float(first[1])),
    )
    second_area = max(
        1e-12,
        (float(second[2]) - float(second[0]))
        * (float(second[3]) - float(second[1])),
    )
    return intersection / (first_area + second_area - intersection)


def resolve_bbox(
    bbox_value: object,
    polygon_value: object,
) -> tuple[tuple[float, float, float, float], str, float]:
    """Resolve ambiguous four-number boxes against the polygon envelope.

    Both common conventions are evaluated: `[x0,y0,x1,y1]` and
    `[x,y,width,height]`. The convention with strictly better polygon IoU wins.
    Ties between geometrically different candidates fail closed.
    """
    raw = _finite_numbers(bbox_value, "bbox")
    polygon = polygon_envelope(polygon_value)
    if len(raw) == 8:
        bbox = polygon_envelope(raw)
        return bbox, "polygon_8", _bbox_iou(bbox, polygon)
    if len(raw) != 4:
        raise RuntimeError("TextOCR bbox must contain four or eight numbers")
    x0, y0, third, fourth = raw
    candidates: list[tuple[str, tuple[float, float, float, float]]] = []
    xyxy = (x0, y0, third, fourth)
    if xyxy[2] > xyxy[0] and xyxy[3] > xyxy[1]:
        candidates.append(("xyxy", xyxy))
    xywh = (x0, y0, x0 + third, y0 + fourth)
    if third > 0 and fourth > 0:
        candidates.append(("xywh", xywh))
    if not candidates:
        raise RuntimeError("TextOCR bbox has no positive interpretation")
    scored = sorted(
        (
            _bbox_iou(candidate, polygon),
            name,
            candidate,
        )
        for name, candidate in candidates
    )
    best_score, best_name, best_bbox = scored[-1]
    if len(scored) > 1:
        second_score, _, second_bbox = scored[-2]
        if (
            abs(best_score - second_score) <= 1e-9
            and tuple(best_bbox) != tuple(second_bbox)
        ):
            raise RuntimeError("TextOCR bbox convention is ambiguous")
    if best_score < 0.50:
        raise RuntimeError(
            f"TextOCR bbox disagrees with polygon envelope: IoU={best_score}"
        )
    return tuple(best_bbox), best_name, best_score


def selection_rank(
    *,
    row_index: int,
    truth: str,
    bbox_xyxy: Sequence[float],
    annotation_text: str,
) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "dataset_revision": DATASET_REVISION,
                "row_index": int(row_index),
                "truth": truth,
                "bbox_xyxy": [float(value) for value in bbox_xyxy],
                "annotation_text_nfkc": unicodedata.normalize(
                    "NFKC", annotation_text
                ),
            }
        ).encode("utf-8")
    )


def select_numeric_annotation(
    *,
    row_index: int,
    texts: object,
    bboxes: object,
    polygons: object,
    num_text_regions: object,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    text_rows = _sequence(texts, "texts")
    bbox_rows = _sequence(bboxes, "bboxes")
    polygon_rows = _sequence(polygons, "polygons")
    if not (len(text_rows) == len(bbox_rows) == len(polygon_rows)):
        raise RuntimeError(
            "TextOCR texts, bboxes, and polygons are not one-to-one"
        )
    try:
        declared_regions = int(num_text_regions)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TextOCR num_text_regions is not an integer") from exc
    if declared_regions != len(text_rows):
        raise RuntimeError(
            "TextOCR num_text_regions does not match annotation arrays"
        )
    counts: Counter[str] = Counter()
    counts["annotations_total"] = len(text_rows)
    candidates: dict[
        tuple[str, tuple[float, float, float, float]], dict[str, Any]
    ] = {}
    for annotation_index, (raw_text, raw_bbox, raw_polygon) in enumerate(
        zip(text_rows, bbox_rows, polygon_rows, strict=True)
    ):
        text = unicodedata.normalize("NFKC", str(raw_text or "")).strip()
        truth = canonical_numeric_text(text)
        if truth is None:
            counts["annotations_outside_numeric_scope"] += 1
            continue
        bbox, convention, polygon_iou = resolve_bbox(raw_bbox, raw_polygon)
        rank = selection_rank(
            row_index=row_index,
            truth=truth,
            bbox_xyxy=bbox,
            annotation_text=text,
        )
        candidate = {
            "row_index": int(row_index),
            "annotation_index": annotation_index,
            "annotation_text": text,
            "truth": truth,
            "bbox_xyxy": list(bbox),
            "bbox_convention": convention,
            "bbox_polygon_iou": polygon_iou,
            "selection_rank_sha256": rank,
        }
        identity = (truth, bbox)
        previous = candidates.get(identity)
        if previous is None or (
            rank,
            annotation_index,
        ) < (
            str(previous["selection_rank_sha256"]),
            int(previous["annotation_index"]),
        ):
            candidates[identity] = candidate
        counts["numeric_annotations_in_scope"] += 1
    counts["unique_numeric_candidates"] = len(candidates)
    if not candidates:
        return None, dict(counts)
    selected = min(
        candidates.values(),
        key=lambda row: (
            str(row["selection_rank_sha256"]),
            str(row["truth"]),
            tuple(float(value) for value in row["bbox_xyxy"]),
        ),
    )
    return selected, dict(counts)


def census_rows(
    rows: Iterable[tuple[int, object, object, object, object]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    convention_counts: Counter[str] = Counter()
    truth_lengths: Counter[int] = Counter()
    seen_indices: set[int] = set()
    for row_index, texts, bboxes, polygons, num_regions in rows:
        if row_index in seen_indices:
            raise RuntimeError(f"duplicate TextOCR row index: {row_index}")
        seen_indices.add(row_index)
        counts["rows_total"] += 1
        selected, row_counts = select_numeric_annotation(
            row_index=row_index,
            texts=texts,
            bboxes=bboxes,
            polygons=polygons,
            num_text_regions=num_regions,
        )
        counts.update(row_counts)
        if selected is None:
            counts["rows_without_numeric_candidate"] += 1
            continue
        records.append(selected)
        counts["rows_with_selected_numeric_candidate"] += 1
        convention_counts[str(selected["bbox_convention"])] += 1
        truth_lengths[len(str(selected["truth"]))] += 1
    records.sort(key=lambda row: int(row["row_index"]))
    return {
        "row_count": counts["rows_total"],
        "selected_count": len(records),
        "counts": dict(sorted(counts.items())),
        "selected_bbox_conventions": dict(
            sorted(convention_counts.items())
        ),
        "selected_truth_length_distribution": {
            str(key): value for key, value in sorted(truth_lengths.items())
        },
        "selected_record_set_sha256": sha256_bytes(
            canonical_json(records).encode("utf-8")
        ),
        "records": records,
    }


def _quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def remote_census(
    *,
    source_url: str,
    candidate_stable_payload_sha256: str,
    candidate_source_commit: str,
) -> dict[str, Any]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("duckdb is required for TextOCR census") from exc
    if len(candidate_stable_payload_sha256) != 64:
        raise RuntimeError("candidate stable payload SHA-256 is invalid")
    if len(candidate_source_commit) != 40:
        raise RuntimeError("candidate source commit is invalid")
    connection = duckdb.connect(database=":memory:")
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=true")
    source = _quote_sql(source_url)
    description = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet({source})"
    ).fetchall()
    columns = [str(row[0]) for row in description]
    missing = [column for column in EXPECTED_COLUMNS if column not in columns]
    if missing:
        raise RuntimeError(
            f"TextOCR Parquet is missing frozen columns: {missing}"
        )
    query = (
        "SELECT file_row_number::BIGINT AS row_index, "
        "texts, bboxes, polygons, num_text_regions "
        f"FROM read_parquet({source}, file_row_number=true) "
        "ORDER BY file_row_number"
    )
    cursor = connection.execute(query)

    def rows() -> Iterable[tuple[int, object, object, object, object]]:
        while True:
            batch = cursor.fetchmany(128)
            if not batch:
                return
            for row in batch:
                yield int(row[0]), row[1], row[2], row[3], row[4]

    census = census_rows(rows())
    selected = int(census["selected_count"])
    projected_accepted = selected * DEVELOPMENT_ACCEPTANCE_RATE
    power_pass = bool(
        selected >= MINIMUM_SELECTED
        and projected_accepted >= MINIMUM_ACCEPTED
    )
    report: dict[str, Any] = {
        "schema": CENSUS_SCHEMA,
        "adapter_schema": ADAPTER_SCHEMA,
        "dataset": {
            "id": DATASET_ID,
            "revision": DATASET_REVISION,
            "component": COMPONENT,
            "source_path": SOURCE_PATH,
            "source_sha256": SOURCE_SHA256,
            "source_size_bytes": SOURCE_SIZE_BYTES,
            "source_url": source_url,
        },
        "candidate_binding": {
            "stable_payload_sha256": candidate_stable_payload_sha256,
            "source_commit": candidate_source_commit,
        },
        "schema_fingerprint": {
            "columns": columns,
            "expected_columns": list(EXPECTED_COLUMNS),
            "census_columns_only": list(CENSUS_COLUMNS),
            "image_column_read": False,
        },
        "selection": {
            "one_risk_unit_per_image_row": True,
            "uses_image_bytes": False,
            "uses_ocr": False,
            "uses_candidate_output": False,
            "bbox_convention_resolved_against_polygon": True,
        },
        "census": census,
        "power_gate": {
            "minimum_selected": MINIMUM_SELECTED,
            "minimum_accepted": MINIMUM_ACCEPTED,
            "development_acceptance_rate": DEVELOPMENT_ACCEPTANCE_RATE,
            "selected_available": selected,
            "selected_pass": selected >= MINIMUM_SELECTED,
            "projected_accepted": projected_accepted,
            "projected_accepted_pass": projected_accepted
            >= MINIMUM_ACCEPTED,
            "download_full_source_and_run_ocr": power_pass,
        },
        "decision": {
            "footer_and_metadata_columns_opened_after_candidate_freeze": True,
            "image_bytes_opened": False,
            "ocr_executed": False,
            "candidate_inference_executed": False,
            "external_certificate_claimed": False,
            "production_ready": False,
            "automatic_production_change": False,
            "verdict": (
                "TEXTOCR_SCHEMA_AND_POWER_GATE_PASS"
                if power_pass
                else "TEXTOCR_TERMINAL_NO_FULL_DOWNLOAD"
            ),
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    return stable_payload(report, "stable_payload_sha256")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--candidate-stable", required=True)
    parser.add_argument("--candidate-source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = remote_census(
        source_url=args.source_url,
        candidate_stable_payload_sha256=args.candidate_stable,
        candidate_source_commit=args.candidate_source_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema_fingerprint": report["schema_fingerprint"],
                "census": {
                    key: value
                    for key, value in report["census"].items()
                    if key != "records"
                },
                "power_gate": report["power_gate"],
                "decision": report["decision"],
                "stable_payload_sha256": report[
                    "stable_payload_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
