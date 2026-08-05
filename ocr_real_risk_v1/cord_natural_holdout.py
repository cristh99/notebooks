"""Outcome-blind CORD-v2 natural-receipt holdout for digit-forest-v3.

The frozen candidate is cryptographically bound before any OCR outcome is
opened. Exactly one numeric annotation is selected per receipt by SHA-256 from
expert geometry only. Tesseract receives the complete natural receipt image;
the candidate receives only the spatially matched Tesseract crop and claim.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import shutil
import statistics
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow.parquet as pq
from PIL import Image

from .core import canonical_json, mutate_one_digit, p95, sha256_bytes, sha256_file
from .cord_source_seal import verify as verify_source_seal
from .numeric_digit_forest import infer_claim
from .numeric_digit_forest_deterministic import load_frozen_candidate
from .sroie_natural_holdout import (
    canonical_numeric_region,
    crop_box,
    eligibility,
    image_bytes_from_row,
    match_ocr_claim,
    stable_payload,
    tesseract_tokens,
    verify_stable_payload,
)

DATASET_REPO = "naver-clova-ix/cord-v2"
DATASET_REVISION = "7f0115a4b758a71d6473b8d085751692da2fef98"
DATASET_LICENSE = "CC-BY-4.0"
DATASET_EXPECTED_SPLITS = {"train": 800, "validation": 100, "test": 100}
SHARD_SPECS: dict[str, dict[str, str]] = {
    "train-00000-of-00004": {
        "split": "train",
        "filename": "data/train-00000-of-00004-b4aaeceff1d90ecb.parquet",
    },
    "train-00001-of-00004": {
        "split": "train",
        "filename": "data/train-00001-of-00004-7dbbe248962764c5.parquet",
    },
    "train-00002-of-00004": {
        "split": "train",
        "filename": "data/train-00002-of-00004-688fe1305a55e5cc.parquet",
    },
    "train-00003-of-00004": {
        "split": "train",
        "filename": "data/train-00003-of-00004-2d0cd200555ed7fd.parquet",
    },
    "validation-00000-of-00001": {
        "split": "validation",
        "filename": "data/validation-00000-of-00001-cc3c5779fe22e8ca.parquet",
    },
    "test-00000-of-00001": {
        "split": "test",
        "filename": "data/test-00000-of-00001-9c204eb3f4e11791.parquet",
    },
}
MANIFEST_SCHEMA = "ocr-cord-natural-numeric-manifest/1"
PROTOCOL_SCHEMA = "ocr-cord-natural-protocol/1"
REPORT_SCHEMA = "ocr-cord-natural-numeric-shard/1"
CANDIDATE_ID = "digit-forest-v3"
TARGET_REDUCTION = 10.0
MINIMUM_SELECTED = 700
MINIMUM_ACCEPTED = 100
MINIMUM_COVERAGE = 0.25
COUNTERFACTUAL_MAXIMUM_RISK = 0.01
FAMILY_ALPHA = 0.05
ALPHA_PER_LEG = FAMILY_ALPHA / 4.0
_NORMALIZE_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hash_manifest(root: Path) -> None:
    manifest = root / "SHA256SUMS.txt"
    if not manifest.exists():
        raise RuntimeError(f"missing SHA256SUMS.txt in {root}")
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = raw.split("  ", 1)
        target = root / relative
        if sha256_path(target) != expected:
            raise RuntimeError(f"hash mismatch: {target}")


def iter_parquet_rows(
    path: Path, *, batch_size: int = 4
) -> Iterable[tuple[int, dict[str, Any]]]:
    parquet = pq.ParquetFile(path)
    row_index = 0
    for batch in parquet.iter_batches(batch_size=batch_size):
        for row in batch.to_pylist():
            yield row_index, row
            row_index += 1


def parse_ground_truth(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("CORD row has empty ground_truth")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("CORD ground_truth is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("CORD ground_truth must decode to an object")
    if not isinstance(payload.get("meta"), dict):
        raise RuntimeError("CORD ground_truth is missing meta")
    if not isinstance(payload.get("valid_line"), list):
        raise RuntimeError("CORD ground_truth is missing valid_line")
    return payload


def quad_bbox(quad: Mapping[str, object]) -> tuple[int, int, int, int]:
    xs: list[float] = []
    ys: list[float] = []
    for index in range(1, 5):
        try:
            x = float(quad[f"x{index}"])
            y = float(quad[f"y{index}"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("CORD numeric word has malformed quad") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise RuntimeError("CORD numeric word quad is non-finite")
        xs.append(x)
        ys.append(y)
    bbox = (
        int(math.floor(min(xs))),
        int(math.floor(min(ys))),
        int(math.ceil(max(xs))),
        int(math.ceil(max(ys))),
    )
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise RuntimeError("CORD numeric word quad is empty")
    return bbox


def clip_bbox_to_image(
    bbox: Sequence[int], image_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], bool]:
    """Clip annotation coordinates to the decoded image rectangle.

    CORD quads occasionally use inclusive or rounded edge coordinates that
    extend a few pixels beyond the decoded image. Clipping is deterministic,
    outcome-blind, and occurs before selection ranking. A box with no overlap
    still fails closed.
    """
    if len(bbox) != 4:
        raise RuntimeError("CORD bbox must contain four coordinates")
    width, height = image_size
    if width <= 0 or height <= 0:
        raise RuntimeError("CORD image dimensions must be positive")
    raw = tuple(int(value) for value in bbox)
    clipped = (
        max(0, min(width, raw[0])),
        max(0, min(height, raw[1])),
        max(0, min(width, raw[2])),
        max(0, min(height, raw[3])),
    )
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise RuntimeError("CORD numeric word quad has no overlap with image")
    return clipped, clipped != raw


def receipt_identity(
    payload: Mapping[str, Any],
    expected_split: str,
) -> tuple[str, int]:
    meta = payload["meta"]
    split = str(meta.get("split") or "").strip().lower()
    accepted_aliases = {
        "train": {"train", "training"},
        "validation": {"validation", "valid", "val", "dev"},
        "test": {"test", "testing", "eval", "evaluation"},
    }
    if split not in accepted_aliases[expected_split]:
        raise RuntimeError(
            f"CORD row split mismatch: {split!r} not in "
            f"{sorted(accepted_aliases[expected_split])}"
        )
    try:
        image_id = int(meta["image_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("CORD row has invalid meta.image_id") from exc
    return f"{expected_split}:{image_id:04d}", image_id


def normalized_merchant(payload: Mapping[str, Any], fallback: str) -> str:
    pieces: list[str] = []
    for line in payload.get("valid_line") or []:
        if not isinstance(line, Mapping):
            continue
        category = str(line.get("category") or "").lower()
        if not (
            category.startswith("company")
            or category.startswith("store")
            or category.startswith("merchant")
        ):
            continue
        for word in line.get("words") or []:
            if isinstance(word, Mapping):
                pieces.append(str(word.get("text") or ""))
    text = unicodedata.normalize("NFKD", " ".join(pieces))
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    normalized = _NORMALIZE_NON_ALNUM.sub("", text.upper())
    return normalized[:120] or f"KEY:{fallback}"


def selection_rank(
    *,
    shard_id: str,
    split: str,
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
                "split": split,
                "key": key,
                "image_sha256": image_sha256,
                "bbox": [int(value) for value in bbox],
                "truth": truth,
            }
        ).encode("utf-8")
    )


def select_numeric_annotation(
    *,
    payload: Mapping[str, Any],
    shard_id: str,
    split: str,
    key: str,
    image_sha256: str,
    image_size: tuple[int, int],
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    width, height = image_size
    candidates: dict[
        tuple[str, tuple[int, int, int, int]], dict[str, Any]
    ] = {}
    counts: Counter[str] = Counter()
    valid_lines = payload.get("valid_line") or []
    for line_index, line in enumerate(valid_lines):
        if not isinstance(line, Mapping):
            raise RuntimeError("CORD valid_line contains a non-object")
        words = line.get("words")
        if not isinstance(words, list):
            raise RuntimeError("CORD valid_line.words must be a list")
        for word_index, word in enumerate(words):
            if not isinstance(word, Mapping):
                raise RuntimeError("CORD words contains a non-object")
            annotation_text = str(word.get("text") or "")
            truth = canonical_numeric_region(annotation_text)
            if truth is None:
                counts["annotations_outside_numeric_scope"] += 1
                continue
            quad = word.get("quad")
            if not isinstance(quad, Mapping):
                raise RuntimeError("CORD numeric word is missing quad")
            raw_bbox = quad_bbox(quad)
            bbox, was_clipped = clip_bbox_to_image(
                raw_bbox, (width, height)
            )
            if was_clipped:
                counts["numeric_annotations_clipped_to_image"] += 1
            counts["numeric_annotations_in_scope"] += 1
            rank = selection_rank(
                shard_id=shard_id,
                split=split,
                key=key,
                image_sha256=image_sha256,
                bbox=bbox,
                truth=truth,
            )
            candidates[(truth, bbox)] = {
                "truth": truth,
                "annotation_text": annotation_text,
                "bbox": list(bbox),
                "annotation_bbox_raw": list(raw_bbox),
                "bbox_clipped_to_image": was_clipped,
                "selection_rank_sha256": rank,
                "line_index": line_index,
                "word_index": word_index,
                "category": str(line.get("category") or ""),
                "group_id": line.get("group_id"),
                "sub_group_id": line.get("sub_group_id"),
                "row_id": word.get("row_id"),
                "is_key": word.get("is_key"),
            }
    if not candidates:
        return None, dict(counts)
    selected = min(
        candidates.values(),
        key=lambda row: (
            str(row["selection_rank_sha256"]),
            str(row["truth"]),
            tuple(row["bbox"]),
        ),
    )
    counts["unique_numeric_candidates"] = len(candidates)
    return selected, dict(counts)


def candidate_binding_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "candidate_id": CANDIDATE_ID,
        "artifact_id": int(args.candidate_artifact_id),
        "artifact_zip_sha256": str(args.candidate_artifact_digest).removeprefix(
            "sha256:"
        ),
        "source_commit": str(args.candidate_source_commit),
        "model_sha256": str(args.expected_model_sha256),
        "candidate_stable_payload_sha256": str(
            args.expected_candidate_stable_sha256
        ),
    }


def load_bound_candidate(
    root: Path,
    binding: Mapping[str, Any],
) -> tuple[dict[str, Any], Any]:
    candidate, model = load_frozen_candidate(root)
    if candidate.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("unexpected frozen candidate id")
    if candidate.get("stable_payload_sha256") != binding.get(
        "candidate_stable_payload_sha256"
    ):
        raise RuntimeError("candidate stable payload is not bound")
    if candidate.get("model", {}).get("sha256") != binding.get("model_sha256"):
        raise RuntimeError("candidate model SHA-256 is not bound")
    if float(candidate.get("inference", {}).get("threshold", -1.0)) != 0.25:
        raise RuntimeError("candidate threshold changed")
    if candidate.get("inference", {}).get("uses_truth") is not False:
        raise RuntimeError("candidate inference unexpectedly uses truth")
    if candidate.get("inference", {}).get("uses_annotation_bbox") is not False:
        raise RuntimeError(
            "candidate inference unexpectedly uses annotation bbox"
        )
    if candidate.get("decision", {}).get("production_ready") is not False:
        raise RuntimeError("external candidate must not claim production readiness")
    return candidate, model


def _validate_meta_size(
    payload: Mapping[str, Any], image_size: tuple[int, int]
) -> None:
    meta_size = payload.get("meta", {}).get("image_size")
    if not isinstance(meta_size, Mapping):
        raise RuntimeError("CORD meta.image_size is missing")
    try:
        expected = (int(meta_size["width"]), int(meta_size["height"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("CORD meta.image_size is invalid") from exc
    if expected != image_size:
        raise RuntimeError(
            f"CORD meta.image_size mismatch: {expected} != {image_size}"
        )


def build_manifest(
    parquet_path: Path,
    shard_id: str,
    candidate_binding: Mapping[str, Any],
) -> dict[str, Any]:
    if shard_id not in SHARD_SPECS:
        raise ValueError(f"unknown CORD shard: {shard_id}")
    spec = SHARD_SPECS[shard_id]
    split = spec["split"]
    observed_parquet_sha = sha256_path(parquet_path)
    census: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    keys: set[str] = set()
    images: Counter[str] = Counter()
    truth_lengths: Counter[int] = Counter()
    merchant_groups: Counter[str] = Counter()

    for row_index, row in iter_parquet_rows(parquet_path):
        census["rows"] += 1
        payload = parse_ground_truth(row.get("ground_truth"))
        key, image_id = receipt_identity(payload, split)
        if key in keys:
            raise RuntimeError(f"duplicate CORD receipt key: {key}")
        keys.add(key)
        image_bytes = image_bytes_from_row(row)
        image_sha = sha256_bytes(image_bytes)
        images[image_sha] += 1
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image_size = opened.size
        _validate_meta_size(payload, image_size)
        merchant_group = normalized_merchant(payload, key)
        merchant_groups[merchant_group] += 1
        selected, counts = select_numeric_annotation(
            payload=payload,
            shard_id=shard_id,
            split=split,
            key=key,
            image_sha256=image_sha,
            image_size=image_size,
        )
        census.update(counts)
        if selected is None:
            census["rows_without_numeric_candidate"] += 1
            continue
        truth_lengths[len(str(selected["truth"]))] += 1
        records.append(
            {
                "shard_id": shard_id,
                "split": split,
                "row_index": row_index,
                "key": key,
                "image_id": image_id,
                "image_sha256": image_sha,
                "image_width": image_size[0],
                "image_height": image_size[1],
                "merchant_group": merchant_group,
                **selected,
                "counterfactual_claim": mutate_one_digit(
                    str(selected["truth"]),
                    (
                        f"{DATASET_REVISION}:{shard_id}:{key}:"
                        f"{selected['selection_rank_sha256']}"
                    ),
                ),
            }
        )
        census["rows_with_selected_numeric_location"] += 1

    records.sort(key=lambda row: (int(row["row_index"]), str(row["key"])))
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "dataset": {
            "repo": DATASET_REPO,
            "revision": DATASET_REVISION,
            "license": DATASET_LICENSE,
            "split": split,
            "shard_id": shard_id,
            "filename": spec["filename"],
            "parquet_sha256": observed_parquet_sha,
            "rows": census["rows"],
        },
        "candidate_binding": dict(candidate_binding),
        "protocol": {
            "risk_unit": "one pre-OCR SHA-selected numeric word per receipt",
            "numeric_scope": (
                "one self-contained 4-12 digit expression after declared "
                "currency/separator normalization; standalone years and "
                "repeated-digit junk excluded"
            ),
            "selection_uses_ocr": False,
            "selection_uses_candidate_outcome": False,
            "page_input": "entire original natural receipt image",
            "tesseract": {
                "language": "eng",
                "oem": 1,
                "psm": 3,
                "timeout_seconds": 90,
            },
            "spatial_match_minimum_truth_coverage": 0.35,
            "eligibility_minimum_truth_coverage": 0.50,
            "eligibility_equal_canonical_length_required": True,
            "primary_candidate_crop": "matched Tesseract token bbox plus 2 pixels",
            "truth_bbox_candidate_use": False,
            "candidate_frozen_before_dataset_ocr": True,
            "counterfactual": "one deterministic wrong digit at equal length",
            "family_alpha": FAMILY_ALPHA,
            "alpha_per_leg_bonferroni": ALPHA_PER_LEG,
            "target_error_reduction": TARGET_REDUCTION,
            "minimum_selected": MINIMUM_SELECTED,
            "minimum_accepted": MINIMUM_ACCEPTED,
            "minimum_coverage_lower": MINIMUM_COVERAGE,
            "counterfactual_maximum_upper": COUNTERFACTUAL_MAXIMUM_RISK,
        },
        "census": {
            **dict(sorted(census.items())),
            "unique_keys": len(keys),
            "unique_images": len(images),
            "duplicate_image_associations": sum(
                count - 1 for count in images.values() if count > 1
            ),
            "merchant_groups": len(merchant_groups),
            "selected_key_set_sha256": sha256_bytes(
                canonical_json([row["key"] for row in records]).encode("utf-8")
            ),
            "truth_length_distribution": {
                str(key): value for key, value in sorted(truth_lengths.items())
            },
        },
        "records": records,
    }
    return stable_payload(manifest, "manifest_sha256")


def write_manifest(manifest: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_protocol_bundle(
    manifest_paths: Sequence[Path],
    output_dir: Path,
    source_seal_path: Path,
) -> dict[str, Any]:
    source_seal = json.loads(
        source_seal_path.read_text(encoding="utf-8")
    )
    if not verify_source_seal(source_seal):
        raise RuntimeError("CORD source seal stable hash failed")
    if source_seal.get("resolved_revision") != DATASET_REVISION:
        raise RuntimeError("CORD source seal resolved a different revision")
    if source_seal.get("outcomes_opened") is not False:
        raise RuntimeError("CORD source seal claims outcomes were opened")
    if int(source_seal.get("parquet_rows_read", -1)) != 0:
        raise RuntimeError("CORD source seal read parquet rows")
    sealed_files = {
        str(row["path"]): row for row in source_seal.get("files") or []
    }
    if set(sealed_files) != {
        spec["filename"] for spec in SHARD_SPECS.values()
    }:
        raise RuntimeError("CORD source seal file set changed")

    manifests: dict[str, dict[str, Any]] = {}
    for path in manifest_paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise RuntimeError(f"unexpected manifest schema: {path}")
        if not verify_stable_payload(manifest, "manifest_sha256"):
            raise RuntimeError(f"manifest stable hash failed: {path}")
        shard_id = str(manifest["dataset"]["shard_id"])
        if shard_id in manifests:
            raise RuntimeError(f"duplicate CORD manifest: {shard_id}")
        manifests[shard_id] = manifest
    if set(manifests) != set(SHARD_SPECS):
        raise RuntimeError(
            f"protocol requires six exact shards: {sorted(manifests)}"
        )
    candidate_bindings = {
        canonical_json(manifest["candidate_binding"])
        for manifest in manifests.values()
    }
    if len(candidate_bindings) != 1:
        raise RuntimeError("CORD manifests bind different candidates")
    all_records = [
        record
        for shard_id in sorted(manifests)
        for record in manifests[shard_id]["records"]
    ]
    rows_by_split: Counter[str] = Counter(
        str(manifest["dataset"]["split"])
        for manifest in manifests.values()
        for _ in range(int(manifest["dataset"]["rows"]))
    )
    # The expansion above is deliberate and bounded to 1,000 rows.
    if dict(rows_by_split) != DATASET_EXPECTED_SPLITS:
        raise RuntimeError(
            f"CORD split row totals changed: {dict(rows_by_split)}"
        )
    for manifest in manifests.values():
        filename = str(manifest["dataset"]["filename"])
        sealed_oid = str(sealed_files[filename]["lfs_oid"]).removeprefix(
            "sha256:"
        )
        if manifest["dataset"]["parquet_sha256"] != sealed_oid:
            raise RuntimeError(
                f"downloaded CORD bytes do not match source seal: {filename}"
            )
        if int(manifest["dataset"]["rows"]) <= 0:
            raise RuntimeError(f"CORD shard has no rows: {filename}")
    keys = [str(record["key"]) for record in all_records]
    if len(set(keys)) != len(keys):
        raise RuntimeError("CORD selected receipt keys overlap across shards")
    image_counts = Counter(str(record["image_sha256"]) for record in all_records)
    protocol: dict[str, Any] = {
        "schema": PROTOCOL_SCHEMA,
        "status": "SEALED_BEFORE_CORD_OCR",
        "dataset": {
            "repo": DATASET_REPO,
            "revision": DATASET_REVISION,
            "license": DATASET_LICENSE,
            "published_rows": sum(DATASET_EXPECTED_SPLITS.values()),
            "splits": dict(DATASET_EXPECTED_SPLITS),
            "shards": dict(SHARD_SPECS),
        },
        "candidate_binding": dict(
            next(iter(manifests.values()))["candidate_binding"]
        ),
        "source_seal": {
            "schema": source_seal["schema"],
            "resolved_revision": source_seal["resolved_revision"],
            "stable_payload_sha256": source_seal[
                "stable_payload_sha256"
            ],
            "total_source_bytes": source_seal["total_source_bytes"],
            "outcomes_opened": source_seal["outcomes_opened"],
            "parquet_rows_read": source_seal["parquet_rows_read"],
            "files": {
                path: {
                    "size_bytes": int(row["size_bytes"]),
                    "lfs_oid": str(row["lfs_oid"]),
                }
                for path, row in sorted(sealed_files.items())
            },
        },
        "gates": {
            "family_alpha": FAMILY_ALPHA,
            "alpha_per_leg_bonferroni": ALPHA_PER_LEG,
            "target_error_reduction": TARGET_REDUCTION,
            "minimum_selected": MINIMUM_SELECTED,
            "minimum_accepted": MINIMUM_ACCEPTED,
            "minimum_coverage_lower": MINIMUM_COVERAGE,
            "counterfactual_maximum_upper": COUNTERFACTUAL_MAXIMUM_RISK,
            "minimum_leave_one_shard_out_pass_fraction": 0.80,
        },
        "execution_plan": {
            "selection_uses_ocr": False,
            "selection_uses_candidate_outcome": False,
            "candidate_bytes_fixed_before_ocr": True,
            "all_three_published_splits_are_external_to_training": True,
            "all_six_physical_parquet_shards_are_evaluated": True,
            "no_threshold_or_model_change_after_outcomes": True,
            "automatic_production_change": False,
        },
        "census": {
            "published_rows": sum(DATASET_EXPECTED_SPLITS.values()),
            "selected_locations": len(all_records),
            "unique_selected_receipt_keys": len(set(keys)),
            "unique_selected_images": len(image_counts),
            "duplicate_selected_image_associations": sum(
                count - 1 for count in image_counts.values() if count > 1
            ),
            "selected_key_set_sha256": sha256_bytes(
                canonical_json(sorted(keys)).encode("utf-8")
            ),
        },
        "manifests": {
            shard_id: {
                "manifest_sha256": manifest["manifest_sha256"],
                "parquet_sha256": manifest["dataset"]["parquet_sha256"],
                "rows": manifest["dataset"]["rows"],
                "selected_locations": manifest["census"].get(
                    "rows_with_selected_numeric_location", 0
                ),
            }
            for shard_id, manifest in sorted(manifests.items())
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    protocol = stable_payload(protocol, "stable_payload_sha256")
    shutil.rmtree(output_dir, ignore_errors=True)
    manifests_dir = output_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    for shard_id, manifest in sorted(manifests.items()):
        write_manifest(manifest, manifests_dir / f"{shard_id}.json")
    (output_dir / "protocol.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "source_seal.json").write_text(
        json.dumps(
            source_seal, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "ATTRIBUTION.md").write_text(
        "# Attribution\n\n"
        "`naver-clova-ix/cord-v2` revision "
        f"`{DATASET_REVISION}` is distributed under CC-BY-4.0 and derives "
        "from the CORD scanned-receipt dataset. This protocol stores only "
        "selection metadata and cryptographic bindings before OCR.\n",
        encoding="utf-8",
    )
    lines = [
        f"{sha256_path(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return protocol


def evaluate_shard(
    parquet_path: Path,
    manifest: Mapping[str, Any],
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise RuntimeError("unexpected CORD manifest schema")
    if not verify_stable_payload(manifest, "manifest_sha256"):
        raise RuntimeError("CORD manifest stable hash failed")
    if sha256_path(parquet_path) != manifest["dataset"]["parquet_sha256"]:
        raise RuntimeError("CORD parquet changed after manifest sealing")
    candidate, model = load_bound_candidate(
        candidate_root, manifest["candidate_binding"]
    )
    shard_id = str(manifest["dataset"]["shard_id"])
    split = str(manifest["dataset"]["split"])
    records = {
        int(record["row_index"]): dict(record)
        for record in manifest["records"]
    }
    if len(records) != len(manifest["records"]):
        raise RuntimeError("CORD manifest has duplicate row indices")
    shutil.rmtree(output_dir, ignore_errors=True)
    crops_dir = output_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    processed: set[int] = set()

    for row_index, row in iter_parquet_rows(parquet_path):
        record = records.get(row_index)
        if record is None:
            continue
        processed.add(row_index)
        payload = parse_ground_truth(row.get("ground_truth"))
        key, image_id = receipt_identity(payload, split)
        if key != record["key"] or image_id != int(record["image_id"]):
            raise RuntimeError("CORD receipt identity changed after sealing")
        image_bytes = image_bytes_from_row(row)
        image_sha = sha256_bytes(image_bytes)
        if image_sha != record["image_sha256"]:
            raise RuntimeError("CORD image changed after manifest sealing")
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")
        _validate_meta_size(payload, image.size)
        selected, _ = select_numeric_annotation(
            payload=payload,
            shard_id=shard_id,
            split=split,
            key=key,
            image_sha256=image_sha,
            image_size=image.size,
        )
        if selected is None or any(
            selected[field] != record[field]
            for field in ("truth", "bbox", "selection_rank_sha256")
        ):
            raise RuntimeError("CORD numeric selection changed after sealing")

        tokens, page_runtime = tesseract_tokens(image)
        matched = match_ocr_claim(record["bbox"], tokens)
        claim, eligible, reason = eligibility(str(record["truth"]), matched)
        reasons[reason] += 1
        claim_correct = bool(eligible and claim == record["truth"])
        candidate_runtime = 0.0
        counter_runtime = 0.0
        crop_file: str | None = None
        crop_sha256: str | None = None
        crop_coordinates: list[int] | None = None
        natural_decision: dict[str, Any] = {
            "claim": claim,
            "prediction": "",
            "accepted": False,
        }
        counter_decision: dict[str, Any] = {
            "claim": record["counterfactual_claim"],
            "prediction": "",
            "accepted": False,
        }
        if eligible:
            box = crop_box(image, matched["bbox"], margin=2)
            crop = image.crop(box)
            evidence_key = sha256_bytes(
                canonical_json(
                    {
                        "image_sha256": image_sha,
                        "bbox": record["bbox"],
                    }
                ).encode("utf-8")
            )
            retained = crops_dir / f"{evidence_key}.png"
            crop.save(retained, optimize=False)
            crop_file = f"crops/{retained.name}"
            crop_sha256 = sha256_file(retained)
            crop_coordinates = list(box)
            started = time.perf_counter()
            natural_decision = infer_claim(
                model,
                crop,
                claim,
                threshold=float(candidate["inference"]["threshold"]),
            )
            candidate_runtime = time.perf_counter() - started
            counter_started = time.perf_counter()
            counter_decision = infer_claim(
                model,
                crop,
                str(record["counterfactual_claim"]),
                threshold=float(candidate["inference"]["threshold"]),
            )
            counter_runtime = time.perf_counter() - counter_started
        else:
            evidence_key = sha256_bytes(
                canonical_json(
                    {
                        "image_sha256": image_sha,
                        "bbox": record["bbox"],
                    }
                ).encode("utf-8")
            )

        natural_accepted = bool(eligible and natural_decision["accepted"])
        counter_accepted = bool(eligible and counter_decision["accepted"])
        observation = {
            "evidence_key": evidence_key,
            "shard_id": shard_id,
            "split": split,
            "row_index": row_index,
            "key": key,
            "image_id": image_id,
            "image_sha256": image_sha,
            "image_width": image.width,
            "image_height": image.height,
            "merchant_group": record["merchant_group"],
            "truth": record["truth"],
            "annotation_text": record["annotation_text"],
            "bbox": record["bbox"],
            "selection_rank_sha256": record["selection_rank_sha256"],
            "tesseract": {
                "claim": claim,
                "eligible": eligible,
                "eligibility_reason": reason,
                "claim_correct": claim_correct,
                "matched": matched,
                "page_runtime": page_runtime,
            },
            "candidate": {
                "candidate_id": CANDIDATE_ID,
                "model_sha256": manifest["candidate_binding"]["model_sha256"],
                "crop_source": (
                    "tesseract_matched_bbox" if eligible else None
                ),
                "crop_box": crop_coordinates,
                "crop_file": crop_file,
                "crop_sha256": crop_sha256,
                "prediction": str(natural_decision.get("prediction") or ""),
                "minimum_mean_probability": natural_decision.get(
                    "minimum_mean_probability"
                ),
                "threshold": float(candidate["inference"]["threshold"]),
                "accepted": natural_accepted,
                "correct_accept": bool(natural_accepted and claim_correct),
                "false_accept": bool(natural_accepted and not claim_correct),
                "runtime_seconds": candidate_runtime,
            },
            "counterfactual": {
                "claim": record["counterfactual_claim"],
                "prediction": str(counter_decision.get("prediction") or ""),
                "minimum_mean_probability": counter_decision.get(
                    "minimum_mean_probability"
                ),
                "accepted": counter_accepted,
                "false_accept": counter_accepted,
                "runtime_seconds": counter_runtime,
            },
        }
        observations.append(observation)
        print(
            json.dumps(
                {
                    "shard_id": shard_id,
                    "selected_processed": len(observations),
                    "selected_total": len(records),
                    "eligible": sum(
                        item["tesseract"]["eligible"] for item in observations
                    ),
                    "baseline_errors": sum(
                        item["tesseract"]["eligible"]
                        and not item["tesseract"]["claim_correct"]
                        for item in observations
                    ),
                    "accepted": sum(
                        item["candidate"]["accepted"] for item in observations
                    ),
                    "false_accepted": sum(
                        item["candidate"]["false_accept"] for item in observations
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    if processed != set(records):
        missing = sorted(set(records) - processed)
        raise RuntimeError(f"CORD selected rows not evaluated: {missing[:10]}")
    observations.sort(key=lambda row: (int(row["row_index"]), str(row["key"])))
    eligible_rows = [
        row for row in observations if row["tesseract"]["eligible"]
    ]
    accepted_rows = [
        row for row in eligible_rows if row["candidate"]["accepted"]
    ]
    page_times = [
        float(row["tesseract"]["page_runtime"]["wall_seconds"])
        for row in observations
    ]
    candidate_times = [
        float(row["candidate"]["runtime_seconds"]) * 1000.0
        for row in eligible_rows
        if float(row["candidate"]["runtime_seconds"]) > 0
    ]
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "dataset": dict(manifest["dataset"]),
        "candidate_binding": dict(manifest["candidate_binding"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol": dict(manifest["protocol"]),
        "execution": {
            "rows": manifest["dataset"]["rows"],
            "selected_locations": len(observations),
            "eligible_claims": len(eligible_rows),
            "accepted": len(accepted_rows),
            "eligibility_reasons": dict(sorted(reasons.items())),
            "ocr_timeouts": sum(
                bool(row["tesseract"]["page_runtime"]["timeout"])
                for row in observations
            ),
        },
        "descriptive": {
            "baseline_errors": sum(
                not row["tesseract"]["claim_correct"] for row in eligible_rows
            ),
            "candidate_false_accepts": sum(
                row["candidate"]["false_accept"] for row in accepted_rows
            ),
            "counterfactual_false_accepts": sum(
                row["counterfactual"]["false_accept"] for row in observations
            ),
            "accepted_coverage_of_selected": (
                len(accepted_rows) / len(observations) if observations else 0.0
            ),
            "median_full_image_tesseract_seconds": (
                statistics.median(page_times) if page_times else None
            ),
            "p95_full_image_tesseract_seconds": p95(page_times),
            "median_candidate_ms": (
                statistics.median(candidate_times) if candidate_times else None
            ),
            "p95_candidate_ms": p95(candidate_times),
        },
        "decision": {
            "shard_execution_complete": True,
            "aggregate_exact_certificate_required": True,
            "formal_10x_claimed_at_shard_level": False,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
        "observations": observations,
    }
    report = stable_payload(report, "stable_payload_sha256")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(manifest, output_dir / "manifest.json")
    (output_dir / "shard_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "ATTRIBUTION.md").write_text(
        "# Attribution\n\n"
        "Eligible numeric token crops derive from "
        f"`{DATASET_REPO}` revision `{DATASET_REVISION}`, CC-BY-4.0. "
        "Full receipt images are not redistributed in this artifact.\n",
        encoding="utf-8",
    )
    lines = [
        f"{sha256_path(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report


def _add_candidate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--candidate-artifact-id", required=True, type=int)
    parser.add_argument("--candidate-artifact-digest", required=True)
    parser.add_argument("--candidate-source-commit", required=True)
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--expected-candidate-stable-sha256", required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    seal = subparsers.add_parser("seal")
    seal.add_argument("--parquet", required=True, type=Path)
    seal.add_argument("--shard-id", required=True, choices=tuple(SHARD_SPECS))
    seal.add_argument("--output", required=True, type=Path)
    _add_candidate_arguments(seal)

    bundle = subparsers.add_parser("bundle")
    bundle.add_argument("manifests", nargs="+", type=Path)
    bundle.add_argument("--source-seal", required=True, type=Path)
    bundle.add_argument("--output-dir", required=True, type=Path)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--parquet", required=True, type=Path)
    evaluate.add_argument("--manifest", required=True, type=Path)
    evaluate.add_argument("--candidate-root", required=True, type=Path)
    evaluate.add_argument("--output-dir", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "seal":
        binding = candidate_binding_from_args(args)
        load_bound_candidate(args.candidate_root, binding)
        manifest = build_manifest(args.parquet, args.shard_id, binding)
        write_manifest(manifest, args.output)
        print(
            json.dumps(
                {
                    "dataset": manifest["dataset"],
                    "candidate_binding": manifest["candidate_binding"],
                    "census": manifest["census"],
                    "manifest_sha256": manifest["manifest_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "bundle":
        protocol = build_protocol_bundle(
            args.manifests, args.output_dir, args.source_seal
        )
        print(json.dumps(protocol, indent=2, sort_keys=True))
        return 0
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = evaluate_shard(
        args.parquet,
        manifest,
        args.candidate_root,
        args.output_dir,
    )
    print(
        json.dumps(
            {
                "dataset": report["dataset"],
                "execution": report["execution"],
                "descriptive": report["descriptive"],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
