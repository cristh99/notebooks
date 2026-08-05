"""Byte-identical distributed Tesseract throughput proof on real receipt pages.

The serial and distributed paths consume the same sealed raster page pack and
run the same pinned Tesseract configuration. The only permitted difference is
page assignment across isolated workers. The aggregate fails closed unless the
combined distributed OCR payload is byte-identical to the serial payload.

The measured 10x gate is distributed OCR service throughput. It is not a claim
of 10x single-page latency, compute efficiency, cost efficiency, or complete
pipeline wall time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import canonical_json, sha256_bytes

PAGE_PACK_SCHEMA = "ocr-real-page-pack/1"
PARTITION_REPORT_SCHEMA = "ocr-distributed-partition/1"
AGGREGATE_SCHEMA = "ocr-distributed-throughput-proof/1"
DEFAULT_PAGE_LIMIT = 80
DEFAULT_PARTITIONS = 20
DEFAULT_MINIMUM_SPEEDUP = 10.0
OCR_LANGUAGE = "eng"
OCR_CONFIG = "--oem 1 --psm 3"
OCR_TIMEOUT_SECONDS = 90


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_payload(value: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(hash_field, None)
    result[hash_field] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def verify_stable_payload(value: Mapping[str, Any], hash_field: str) -> bool:
    expected = str(value.get(hash_field) or "")
    payload = dict(value)
    payload.pop(hash_field, None)
    return expected == sha256_bytes(canonical_json(payload).encode("utf-8"))


def encode_rows(rows: Sequence[Mapping[str, Any]]) -> bytes:
    ordered = sorted(rows, key=lambda row: int(row["page_index"]))
    return (
        "".join(canonical_json(dict(row)) + "\n" for row in ordered)
    ).encode("utf-8")


def decode_rows(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    indices = [int(row["page_index"]) for row in rows]
    if len(set(indices)) != len(indices):
        raise RuntimeError(f"duplicate page indices in {path}")
    return rows


def balanced_assignments(
    pages: Sequence[Mapping[str, Any]], partition_count: int
) -> list[list[int]]:
    if partition_count <= 0:
        raise ValueError("partition_count must be positive")
    assignments: list[list[int]] = [[] for _ in range(partition_count)]
    loads = [0 for _ in range(partition_count)]
    ranked = sorted(
        pages,
        key=lambda page: (
            -int(page["width"]) * int(page["height"]),
            int(page["page_index"]),
        ),
    )
    for page in ranked:
        partition = min(range(partition_count), key=lambda idx: (loads[idx], idx))
        page_index = int(page["page_index"])
        assignments[partition].append(page_index)
        loads[partition] += int(page["width"]) * int(page["height"])
    for values in assignments:
        values.sort()
    flattened = [value for values in assignments for value in values]
    expected = sorted(int(page["page_index"]) for page in pages)
    if sorted(flattened) != expected or len(flattened) != len(set(flattened)):
        raise RuntimeError("partition assignment does not cover pages exactly once")
    return assignments


def _iter_image_rows(parquet_path: Path) -> Iterable[dict[str, Any]]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(parquet_path)
    for batch in parquet.iter_batches(columns=["image"], batch_size=8):
        for row in batch.to_pylist():
            yield row


def prepare_page_pack(
    parquet_path: Path,
    output_dir: Path,
    *,
    expected_parquet_sha256: str,
    page_limit: int = DEFAULT_PAGE_LIMIT,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if page_limit <= 0:
        raise ValueError("page_limit must be positive")
    observed = sha256_path(parquet_path)
    if observed != expected_parquet_sha256:
        raise RuntimeError(
            f"source parquet SHA-256 mismatch: {observed} != {expected_parquet_sha256}"
        )
    from PIL import Image
    from .sroie_natural_holdout import image_bytes_from_row

    shutil.rmtree(output_dir, ignore_errors=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    for page_index, row in enumerate(_iter_image_rows(parquet_path)):
        if page_index >= page_limit:
            break
        image_bytes = image_bytes_from_row(row)
        with Image.open(__import__("io").BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")
        filename = f"pages/page-{page_index:04d}.png"
        target = output_dir / filename
        image.save(target, format="PNG", optimize=False, compress_level=6)
        pages.append(
            {
                "page_index": page_index,
                "file": filename,
                "sha256": sha256_path(target),
                "width": image.width,
                "height": image.height,
                "pixels": image.width * image.height,
            }
        )
    if len(pages) != page_limit:
        raise RuntimeError(f"expected {page_limit} pages, found {len(pages)}")
    manifest: dict[str, Any] = {
        "schema": PAGE_PACK_SCHEMA,
        "source": {
            **dict(source or {}),
            "parquet_sha256": observed,
        },
        "protocol": {
            "page_limit": page_limit,
            "selection": "first N physical rows; labels and annotations not read",
            "raster": "RGB PNG, Pillow 12.2.0, optimize=false, compress_level=6",
            "ocr_language": OCR_LANGUAGE,
            "ocr_config": OCR_CONFIG,
            "ocr_timeout_seconds": OCR_TIMEOUT_SECONDS,
        },
        "page_count": len(pages),
        "total_pixels": sum(int(page["pixels"]) for page in pages),
        "pages": pages,
    }
    manifest = stable_payload(manifest, "stable_payload_sha256")
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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
    return manifest


def load_page_pack(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != PAGE_PACK_SCHEMA:
        raise RuntimeError("unexpected page-pack schema")
    if not verify_stable_payload(manifest, "stable_payload_sha256"):
        raise RuntimeError("page-pack stable payload mismatch")
    if int(manifest.get("page_count", -1)) != len(manifest.get("pages") or []):
        raise RuntimeError("page-pack count mismatch")
    return manifest


def _tesseract_version() -> str:
    completed = subprocess.run(
        ["tesseract", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    first = completed.stdout.splitlines()[0].strip()
    if not first:
        raise RuntimeError("Tesseract version was empty")
    return first


def ocr_page(page_path: Path, page_index: int, page_sha256: str) -> dict[str, Any]:
    import pytesseract
    from PIL import Image
    from pytesseract import Output

    with Image.open(page_path) as opened:
        image = opened.convert("RGB")
    data = pytesseract.image_to_data(
        image,
        lang=OCR_LANGUAGE,
        config=OCR_CONFIG,
        output_type=Output.DICT,
        timeout=OCR_TIMEOUT_SECONDS,
    )
    token_count = len(data.get("text") or [])
    fields = (
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    )
    tokens: list[dict[str, Any]] = []
    for token_index in range(token_count):
        text = str(data.get("text", [""] * token_count)[token_index])
        if not text.strip():
            continue
        token: dict[str, Any] = {"token_index": token_index, "text": text}
        for field in fields[:-1]:
            values = data.get(field) or []
            if token_index >= len(values):
                raise RuntimeError(f"Tesseract output is missing {field}")
            value = values[token_index]
            if field == "conf":
                token[field] = str(value)
            else:
                token[field] = int(value)
        tokens.append(token)
    return {
        "page_index": page_index,
        "page_sha256": page_sha256,
        "tokens": tokens,
    }


def run_partition(
    page_pack_root: Path,
    output_dir: Path,
    *,
    partition_count: int,
    partition_index: int,
) -> dict[str, Any]:
    if not 0 <= partition_index < partition_count:
        raise ValueError("partition_index outside partition_count")
    manifest = load_page_pack(page_pack_root)
    pages = list(manifest["pages"])
    assignments = balanced_assignments(pages, partition_count)
    assigned_indices = assignments[partition_index]
    by_index = {int(page["page_index"]): page for page in pages}
    rows: list[dict[str, Any]] = []
    started_epoch = time.time()
    started = time.perf_counter()
    for page_index in assigned_indices:
        page = by_index[page_index]
        path = page_pack_root / str(page["file"])
        observed = sha256_path(path)
        if observed != str(page["sha256"]):
            raise RuntimeError(f"page hash mismatch: {path}")
        rows.append(ocr_page(path, page_index, observed))
    elapsed = time.perf_counter() - started
    ended_epoch = time.time()
    payload = encode_rows(rows)
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "rows.jsonl"
    rows_path.write_bytes(payload)
    report: dict[str, Any] = {
        "schema": PARTITION_REPORT_SCHEMA,
        "page_pack_stable_payload_sha256": manifest["stable_payload_sha256"],
        "partition_count": partition_count,
        "partition_index": partition_index,
        "page_indices": assigned_indices,
        "page_count": len(assigned_indices),
        "token_count": sum(len(row["tokens"]) for row in rows),
        "rows_sha256": hashlib.sha256(payload).hexdigest(),
        "ocr_started_epoch": started_epoch,
        "ocr_ended_epoch": ended_epoch,
        "ocr_wall_seconds": elapsed,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "tesseract": _tesseract_version(),
            "omp_thread_limit": os.environ.get("OMP_THREAD_LIMIT"),
        },
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{sha256_path(path)}  {path.name}"
            for path in (rows_path, output_dir / "report.json")
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def discover_output_root(path: Path) -> Path:
    direct = path / "report.json"
    if direct.exists():
        return path
    matches = sorted(path.rglob("report.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one report.json below {path}, found {len(matches)}")
    return matches[0].parent


def load_partition_output(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    resolved = discover_output_root(root)
    report = json.loads((resolved / "report.json").read_text(encoding="utf-8"))
    if report.get("schema") != PARTITION_REPORT_SCHEMA:
        raise RuntimeError(f"unexpected partition report schema: {resolved}")
    rows_path = resolved / "rows.jsonl"
    payload = rows_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != report.get("rows_sha256"):
        raise RuntimeError(f"partition rows hash mismatch: {resolved}")
    rows = decode_rows(rows_path)
    if len(rows) != int(report["page_count"]):
        raise RuntimeError(f"partition page count mismatch: {resolved}")
    if [int(row["page_index"]) for row in rows] != list(report["page_indices"]):
        raise RuntimeError(f"partition page indices mismatch: {resolved}")
    return report, rows, payload


def aggregate_outputs(
    serial_root: Path,
    parallel_roots: Sequence[Path],
    output_dir: Path,
    *,
    minimum_speedup: float = DEFAULT_MINIMUM_SPEEDUP,
) -> dict[str, Any]:
    if minimum_speedup <= 0:
        raise ValueError("minimum_speedup must be positive")
    serial_report, serial_rows, serial_payload = load_partition_output(serial_root)
    if int(serial_report["partition_count"]) != 1:
        raise RuntimeError("serial reference must have partition_count=1")
    reports: list[dict[str, Any]] = []
    combined_rows: list[dict[str, Any]] = []
    for root in parallel_roots:
        report, rows, _ = load_partition_output(root)
        reports.append(report)
        combined_rows.extend(rows)
    if not reports:
        raise RuntimeError("no parallel partition outputs supplied")
    counts = {int(report["partition_count"]) for report in reports}
    if len(counts) != 1:
        raise RuntimeError("parallel outputs disagree on partition_count")
    partition_count = next(iter(counts))
    indices = sorted(int(report["partition_index"]) for report in reports)
    if indices != list(range(partition_count)):
        raise RuntimeError(f"parallel partition set incomplete: {indices}")
    bindings = {
        str(report["page_pack_stable_payload_sha256"]) for report in reports
    }
    bindings.add(str(serial_report["page_pack_stable_payload_sha256"]))
    if len(bindings) != 1:
        raise RuntimeError("serial and parallel paths consumed different page packs")
    combined_payload = encode_rows(combined_rows)
    exact_identity = combined_payload == serial_payload
    serial_indices = [int(row["page_index"]) for row in serial_rows]
    combined_indices = sorted(int(row["page_index"]) for row in combined_rows)
    if combined_indices != serial_indices or len(combined_indices) != len(set(combined_indices)):
        raise RuntimeError("parallel outputs do not cover the serial page set exactly once")
    serial_seconds = float(serial_report["ocr_wall_seconds"])
    service_seconds = max(float(report["ocr_wall_seconds"]) for report in reports)
    observed_window = max(float(report["ocr_ended_epoch"]) for report in reports) - min(
        float(report["ocr_started_epoch"]) for report in reports
    )
    total_worker_seconds = sum(float(report["ocr_wall_seconds"]) for report in reports)
    service_speedup = serial_seconds / service_seconds if service_seconds > 0 else 0.0
    observed_window_speedup = (
        serial_seconds / observed_window if observed_window > 0 else 0.0
    )
    compute_ratio = serial_seconds / total_worker_seconds if total_worker_seconds > 0 else 0.0
    passed = bool(exact_identity and service_speedup >= minimum_speedup)
    report: dict[str, Any] = {
        "schema": AGGREGATE_SCHEMA,
        "page_pack_stable_payload_sha256": next(iter(bindings)),
        "serial": {
            "page_count": len(serial_rows),
            "rows_sha256": hashlib.sha256(serial_payload).hexdigest(),
            "ocr_wall_seconds": serial_seconds,
        },
        "distributed": {
            "partition_count": partition_count,
            "page_count": len(combined_rows),
            "combined_rows_sha256": hashlib.sha256(combined_payload).hexdigest(),
            "maximum_partition_ocr_seconds": service_seconds,
            "observed_ocr_window_seconds": observed_window,
            "total_worker_ocr_seconds": total_worker_seconds,
            "service_throughput_speedup": service_speedup,
            "observed_window_speedup": observed_window_speedup,
            "serial_to_total_worker_compute_ratio": compute_ratio,
        },
        "equivalence": {
            "byte_identical_outputs": exact_identity,
            "page_set_identical": combined_indices == serial_indices,
            "same_ocr_configuration_required": True,
        },
        "decision": {
            "minimum_distributed_service_speedup": minimum_speedup,
            "pass_10x_distributed_service_throughput": passed,
            "single_page_latency_10x_claimed": False,
            "end_to_end_pipeline_10x_claimed": False,
            "compute_efficiency_10x_claimed": False,
            "cost_efficiency_10x_claimed": False,
            "quality_changed": False,
            "production_modified": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    report = stable_payload(report, "stable_payload_sha256")
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "distributed_rows.jsonl").write_bytes(combined_payload)
    (output_dir / "throughput_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{sha256_path(path)}  {path.name}"
            for path in (
                output_dir / "distributed_rows.jsonl",
                output_dir / "throughput_report.json",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    if not exact_identity:
        raise RuntimeError("distributed OCR output differs from serial output")
    if service_speedup < minimum_speedup:
        raise RuntimeError(
            f"distributed service speedup {service_speedup:.6f}x < {minimum_speedup:.6f}x"
        )
    return report


def _source_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "dataset": args.source_dataset,
        "revision": args.source_revision,
        "split": args.source_split,
        "file": args.source_file,
        "labels_opened": False,
        "annotations_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--parquet", required=True, type=Path)
    prepare.add_argument("--expected-parquet-sha256", required=True)
    prepare.add_argument("--output-dir", required=True, type=Path)
    prepare.add_argument("--page-limit", type=int, default=DEFAULT_PAGE_LIMIT)
    prepare.add_argument("--source-dataset", required=True)
    prepare.add_argument("--source-revision", required=True)
    prepare.add_argument("--source-split", required=True)
    prepare.add_argument("--source-file", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--page-pack-root", required=True, type=Path)
    run.add_argument("--output-dir", required=True, type=Path)
    run.add_argument("--partition-count", required=True, type=int)
    run.add_argument("--partition-index", required=True, type=int)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--serial-root", required=True, type=Path)
    aggregate.add_argument("--parallel-parent", required=True, type=Path)
    aggregate.add_argument("--parallel-prefix", required=True)
    aggregate.add_argument("--output-dir", required=True, type=Path)
    aggregate.add_argument(
        "--minimum-speedup", type=float, default=DEFAULT_MINIMUM_SPEEDUP
    )

    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_page_pack(
            args.parquet,
            args.output_dir,
            expected_parquet_sha256=args.expected_parquet_sha256,
            page_limit=args.page_limit,
            source=_source_payload(args),
        )
    elif args.command == "run":
        result = run_partition(
            args.page_pack_root,
            args.output_dir,
            partition_count=args.partition_count,
            partition_index=args.partition_index,
        )
    else:
        roots = sorted(
            path
            for path in args.parallel_parent.iterdir()
            if path.is_dir() and path.name.startswith(args.parallel_prefix)
        )
        result = aggregate_outputs(
            args.serial_root,
            roots,
            args.output_dir,
            minimum_speedup=args.minimum_speedup,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
