"""Outcome-blind adapter for WildReceipt external validation.

Exactly one eligible numeric word is selected per physical receipt by SHA-256
before OCR. WildReceipt stores LayoutLM-normalized ``xyxy`` geometry on a
0-1000 canvas; this module projects that geometry deterministically into the
original image's pixel space. Candidate construction later receives only the
complete original receipt image. Expert text and geometry are used solely to
preselect and score the risk unit; they are unavailable to detector, forest,
and crop guard.
"""
from __future__ import annotations

import math
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow.parquet as pq
from PIL import Image

from .core import canonical_json, sha256_bytes
from .sroie_natural_holdout import image_bytes_from_row

DATASET_ID = "kaydee/wildreceipt"
DATASET_REVISION = "cedafaf3c8b0246c9fad68af29324d655715ad12"
REQUIRED_COLUMNS = ("image", "id", "words", "bboxes")
MINIMUM_DIGITS = 4
MAXIMUM_DIGITS = 12
YEAR_MIN = 1900
YEAR_MAX = 2099
BBOX_COORDINATE_SPACE = "layoutlm_normalized_xyxy_0_1000"
BBOX_COORDINATE_MIN = 0.0
BBOX_COORDINATE_MAX = 1000.0


def canonical_ascii_numeric_word(value: object) -> str | None:
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
    if not MINIMUM_DIGITS <= len(canonical) <= MAXIMUM_DIGITS:
        return None
    if len(set(canonical)) == 1:
        return None
    if len(canonical) == 4 and YEAR_MIN <= int(canonical) <= YEAR_MAX:
        return None
    return canonical


def receipt_key(row: Mapping[str, Any], shard_id: str) -> str:
    if "id" not in row:
        raise RuntimeError("WildReceipt row is missing id")
    identifier = str(row["id"]).strip()
    if not identifier:
        raise RuntimeError("WildReceipt row has an empty id")
    return f"{shard_id}:{identifier}"


def annotation_bbox(
    value: object,
    image_size: tuple[int, int],
) -> tuple[tuple[int, int, int, int], bool]:
    """Project one LayoutLM-normalized box onto the original image pixels.

    Lower bounds use ``floor`` and upper bounds use ``ceil`` so projection never
    shrinks the annotated region. Coordinates outside the normalized canvas are
    clipped and reported; malformed, inverted, fully outside, and pixel-collapsed
    regions fail closed.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RuntimeError("WildReceipt bbox must be a numeric sequence")
    raw_values = list(value)
    try:
        coordinates = [float(item) for item in raw_values]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("WildReceipt bbox contains a non-numeric coordinate") from exc
    if not all(math.isfinite(item) for item in coordinates):
        raise RuntimeError("WildReceipt bbox contains a non-finite coordinate")
    if len(coordinates) == 4:
        x0, y0, x1, y1 = coordinates
    elif len(coordinates) == 8:
        xs = coordinates[0::2]
        ys = coordinates[1::2]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    else:
        raise RuntimeError(
            f"WildReceipt bbox must have 4 or 8 coordinates, got {len(coordinates)}"
        )
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError("WildReceipt normalized bbox has non-positive area")

    width, height = image_size
    if width <= 0 or height <= 0:
        raise RuntimeError("WildReceipt image dimensions must be positive")

    raw_normalized = (x0, y0, x1, y1)
    clipped_normalized = (
        max(BBOX_COORDINATE_MIN, min(BBOX_COORDINATE_MAX, x0)),
        max(BBOX_COORDINATE_MIN, min(BBOX_COORDINATE_MAX, y0)),
        max(BBOX_COORDINATE_MIN, min(BBOX_COORDINATE_MAX, x1)),
        max(BBOX_COORDINATE_MIN, min(BBOX_COORDINATE_MAX, y1)),
    )
    if (
        clipped_normalized[2] <= clipped_normalized[0]
        or clipped_normalized[3] <= clipped_normalized[1]
    ):
        raise RuntimeError(
            "WildReceipt normalized bbox has no overlap with the 0-1000 canvas"
        )

    projected = (
        int(
            math.floor(
                clipped_normalized[0] * width / BBOX_COORDINATE_MAX
            )
        ),
        int(
            math.floor(
                clipped_normalized[1] * height / BBOX_COORDINATE_MAX
            )
        ),
        int(
            math.ceil(
                clipped_normalized[2] * width / BBOX_COORDINATE_MAX
            )
        ),
        int(
            math.ceil(
                clipped_normalized[3] * height / BBOX_COORDINATE_MAX
            )
        ),
    )
    pixel_bbox = (
        max(0, min(width, projected[0])),
        max(0, min(height, projected[1])),
        max(0, min(width, projected[2])),
        max(0, min(height, projected[3])),
    )
    if pixel_bbox[2] <= pixel_bbox[0] or pixel_bbox[3] <= pixel_bbox[1]:
        raise RuntimeError(
            "WildReceipt normalized bbox collapsed during pixel projection"
        )
    return pixel_bbox, clipped_normalized != raw_normalized


def selection_rank(
    *,
    shard_id: str,
    key: str,
    image_sha256: str,
    bbox: Sequence[int],
    truth: str,
) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "dataset_revision": DATASET_REVISION,
                "shard_id": shard_id,
                "receipt_key": key,
                "image_sha256": image_sha256,
                "bbox": [int(value) for value in bbox],
                "truth": truth,
            }
        ).encode("utf-8")
    )


def select_numeric_annotation(
    *,
    row: Mapping[str, Any],
    shard_id: str,
    image_sha256: str,
    image_size: tuple[int, int],
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    for column in REQUIRED_COLUMNS:
        if column not in row:
            raise RuntimeError(f"WildReceipt row is missing {column}")
    words = row["words"]
    bboxes = row["bboxes"]
    if not isinstance(words, Sequence) or isinstance(words, (str, bytes, bytearray)):
        raise RuntimeError("WildReceipt words must be a sequence")
    if not isinstance(bboxes, Sequence) or isinstance(bboxes, (str, bytes, bytearray)):
        raise RuntimeError("WildReceipt bboxes must be a sequence")
    if len(words) != len(bboxes):
        raise RuntimeError(
            f"WildReceipt words/bboxes length mismatch: {len(words)} != {len(bboxes)}"
        )
    key = receipt_key(row, shard_id)
    candidates: dict[tuple[str, tuple[int, int, int, int]], dict[str, Any]] = {}
    counts = {
        "annotations_total": len(words),
        "annotations_outside_numeric_scope": 0,
        "numeric_annotations_in_scope": 0,
        "numeric_annotations_projected_to_pixels": 0,
        "numeric_annotations_clipped_to_image": 0,
    }
    for index, (raw_word, raw_bbox) in enumerate(zip(words, bboxes, strict=True)):
        truth = canonical_ascii_numeric_word(raw_word)
        if truth is None:
            counts["annotations_outside_numeric_scope"] += 1
            continue
        bbox, clipped = annotation_bbox(raw_bbox, image_size)
        counts["numeric_annotations_in_scope"] += 1
        counts["numeric_annotations_projected_to_pixels"] += 1
        counts["numeric_annotations_clipped_to_image"] += int(clipped)
        rank = selection_rank(
            shard_id=shard_id,
            key=key,
            image_sha256=image_sha256,
            bbox=bbox,
            truth=truth,
        )
        candidate = {
            "truth": truth,
            "annotation_text": str(raw_word),
            "bbox": list(bbox),
            "bbox_coordinate_space": "image_pixels",
            "source_bbox_coordinate_space": BBOX_COORDINATE_SPACE,
            "bbox_clipped_to_image": clipped,
            "word_index": index,
            "selection_rank_sha256": rank,
        }
        identity = (truth, bbox)
        previous = candidates.get(identity)
        if previous is None or (
            str(candidate["selection_rank_sha256"]),
            int(candidate["word_index"]),
        ) < (
            str(previous["selection_rank_sha256"]),
            int(previous["word_index"]),
        ):
            candidates[identity] = candidate
    counts["unique_numeric_candidates"] = len(candidates)
    if not candidates:
        return None, counts
    selected = min(
        candidates.values(),
        key=lambda candidate: (
            str(candidate["selection_rank_sha256"]),
            str(candidate["truth"]),
            tuple(int(value) for value in candidate["bbox"]),
        ),
    )
    return selected, counts


def physical_evidence_key(image_sha256: str, bbox: Sequence[int]) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "image_sha256": image_sha256,
                "bbox": [int(value) for value in bbox],
            }
        ).encode("utf-8")
    )


def row_image(row: Mapping[str, Any]) -> tuple[bytes, Image.Image, str]:
    image_bytes = image_bytes_from_row(row)
    from io import BytesIO

    with Image.open(BytesIO(image_bytes)) as opened:
        image = opened.convert("RGB")
    return image_bytes, image, sha256_bytes(image_bytes)


def iter_parquet_rows(
    path: Path,
    *,
    batch_size: int = 4,
) -> Iterable[tuple[int, dict[str, Any]]]:
    parquet = pq.ParquetFile(path)
    available = set(parquet.schema_arrow.names)
    missing = [column for column in REQUIRED_COLUMNS if column not in available]
    if missing:
        raise RuntimeError(f"WildReceipt parquet is missing columns: {missing}")
    row_index = 0
    for batch in parquet.iter_batches(columns=list(REQUIRED_COLUMNS), batch_size=batch_size):
        for row in batch.to_pylist():
            yield row_index, row
            row_index += 1
