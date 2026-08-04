from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from pmlb import fetch_data

from srbench24_runner import ALL_DATASETS, BLACKBOX_DATASETS

SOURCE_REPOSITORY = "cavalab/srbench"
SOURCE_COMMIT = "dc3f6daa93bf10955df8775256a6f8644f38fd93"
SOURCE_DEFINITION_PATH = "datasets/download_data.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(data_root: Path, cache_root: Path, manifest_path: Path) -> dict[str, object]:
    data_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, object]] = []
    total_bytes = 0
    for dataset_name in ALL_DATASETS:
        X, y = fetch_data(
            dataset_name,
            return_X_y=True,
            local_cache_dir=str(cache_root),
        )
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).reshape(-1)
        if X.ndim != 2 or X.shape[0] != y.shape[0] or X.shape[0] < 40:
            raise ValueError(f"invalid dataset shape: {dataset_name}: {X.shape}, {y.shape}")
        path = data_root / f"{dataset_name}.npz"
        np.savez_compressed(path, X=X, y=y)
        size = path.stat().st_size
        total_bytes += size
        tasks.append(
            {
                "dataset": dataset_name,
                "category": "blackbox" if dataset_name in BLACKBOX_DATASETS else "firstprinciples",
                "rows": int(X.shape[0]),
                "features": int(X.shape[1]),
                "target_finite_fraction": float(np.mean(np.isfinite(y))),
                "dataset_npz_bytes": size,
                "dataset_npz_sha256": sha256(path),
            }
        )
    manifest: dict[str, object] = {
        "schema": "data-science-god-level/symbolic-v2-srbench24-data-manifest/1",
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": SOURCE_COMMIT,
        "source_definition_path": SOURCE_DEFINITION_PATH,
        "selection_rule": "all datasets listed in the two pinned SRBench 2025 categories; no filtering",
        "task_count": len(tasks),
        "total_npz_bytes": total_bytes,
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
    print(json.dumps({"task_count": manifest["task_count"], "total_npz_bytes": manifest["total_npz_bytes"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
