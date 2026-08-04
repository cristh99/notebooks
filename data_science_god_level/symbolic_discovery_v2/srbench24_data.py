from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request

import numpy as np
import pandas as pd

from srbench24_runner import ALL_DATASETS, BLACKBOX_DATASETS

SELECTION_REPOSITORY = "cavalab/srbench"
SELECTION_COMMIT = "dc3f6daa93bf10955df8775256a6f8644f38fd93"
SELECTION_DEFINITION_PATH = "datasets/download_data.py"
DATA_REPOSITORY = "EpistasisLab/pmlb"
DATA_COMMIT = "7c1f4bdc00136dc2e55c87fa6b8ba6e8af6d1a68"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset_url(dataset_name: str) -> str:
    return (
        "https://media.githubusercontent.com/media/"
        f"{DATA_REPOSITORY}/{DATA_COMMIT}/datasets/{dataset_name}/"
        f"{dataset_name}.tsv.gz"
    )


def download_bytes(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "data-science-god-level-srbench24/3"},
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if len(data) < 20:
                raise ValueError(f"downloaded payload is too small: {url}")
            if data.startswith(b"version https://git-lfs.github.com/spec"):
                raise ValueError(f"received a Git LFS pointer instead of data: {url}")
            if data[:2] != b"\x1f\x8b":
                raise ValueError(f"downloaded payload is not gzip data: {url}")
            return data
        except Exception as error:
            last_error = error
            if attempt < 4:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed after retries: {url}: {last_error}")


def parse_dataset(payload: bytes, dataset_name: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as stream:
            frame = pd.read_csv(stream, sep="\t")
    except Exception as error:
        raise ValueError(f"could not parse pinned dataset {dataset_name}: {error}") from error
    if "target" not in frame.columns:
        raise ValueError(
            f"pinned dataset {dataset_name} does not contain the canonical target column"
        )
    feature_columns = [str(column) for column in frame.columns if column != "target"]
    if not feature_columns:
        raise ValueError(f"pinned dataset {dataset_name} has no feature columns")
    X = frame.loc[:, feature_columns].to_numpy(dtype=float)
    y = frame.loc[:, "target"].to_numpy(dtype=float).reshape(-1)
    return X, y, feature_columns


def download(data_root: Path, cache_root: Path, manifest_path: Path) -> dict[str, object]:
    data_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, object]] = []
    total_npz_bytes = 0
    total_source_bytes = 0
    for dataset_name in ALL_DATASETS:
        url = dataset_url(dataset_name)
        payload = download_bytes(url)
        raw_path = cache_root / f"{dataset_name}.tsv.gz"
        raw_path.write_bytes(payload)
        X, y, feature_columns = parse_dataset(payload, dataset_name)
        if X.ndim != 2 or X.shape[0] != y.shape[0] or X.shape[0] < 8:
            raise ValueError(
                f"invalid dataset shape: {dataset_name}: {X.shape}, {y.shape}"
            )
        if not np.all(np.isfinite(y)):
            raise ValueError(f"target contains non-finite values: {dataset_name}")
        path = data_root / f"{dataset_name}.npz"
        np.savez_compressed(path, X=X, y=y)
        npz_size = path.stat().st_size
        raw_size = raw_path.stat().st_size
        total_npz_bytes += npz_size
        total_source_bytes += raw_size
        tasks.append(
            {
                "dataset": dataset_name,
                "category": (
                    "blackbox"
                    if dataset_name in BLACKBOX_DATASETS
                    else "firstprinciples"
                ),
                "rows": int(X.shape[0]),
                "features": int(X.shape[1]),
                "feature_columns": feature_columns,
                "target_finite_fraction": float(np.mean(np.isfinite(y))),
                "source_url": url,
                "source_bytes": raw_size,
                "source_sha256": sha256(raw_path),
                "dataset_npz_bytes": npz_size,
                "dataset_npz_sha256": sha256(path),
            }
        )
    manifest: dict[str, object] = {
        "schema": "data-science-god-level/symbolic-v2-srbench24-data-manifest/3",
        "selection_repository": SELECTION_REPOSITORY,
        "selection_commit": SELECTION_COMMIT,
        "selection_definition_path": SELECTION_DEFINITION_PATH,
        "data_repository": DATA_REPOSITORY,
        "data_commit": DATA_COMMIT,
        "transport": "pinned media.githubusercontent.com Git LFS objects",
        "selection_rule": (
            "all datasets listed in the two pinned SRBench 2025 categories; "
            "no filtering"
        ),
        "minimum_rows_supported": 8,
        "task_count": len(tasks),
        "total_source_bytes": total_source_bytes,
        "total_npz_bytes": total_npz_bytes,
        "actual_external_evaluations_authorized": 1,
        "candidate_loaded_during_download": False,
        "dataset_values_accessed_before_candidate_freeze": False,
        "tasks": tasks,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = download(args.data_root, args.cache_root, args.manifest)
    print(
        json.dumps(
            {
                "task_count": manifest["task_count"],
                "total_source_bytes": manifest["total_source_bytes"],
                "total_npz_bytes": manifest["total_npz_bytes"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
