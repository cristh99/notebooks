"""Canonical entry point for the OpenVINO v7 prior-corpus registry.

Historical SROIE terminal manifests predate the explicit source-path field.
They remain bound by repository, immutable revision, exact Parquet SHA-256, and
row count. This entry point also corrects the full-population denominator and
the recovery-artifact digests from live GitHub artifact metadata.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import openvino_prior_registry_v7 as implementation

EXPECTED_TOTAL_ROWS = 38_601
implementation.EXPECTED_TOTAL_ROWS = EXPECTED_TOTAL_ROWS
implementation.SOURCE_SPECS["sroie-train"]["artifact_sha256"] = (
    "ada46e3e9a5ac2d0a29c7f2af20ee493959e4114e299f94cfc00218e8076badd"
)
implementation.SOURCE_SPECS["sroie-test"]["artifact_sha256"] = (
    "0dc86b73e14029fd45867ed7bbd2b83e3f6d1f22a0791a0a75371ecd3a841f90"
)


def _dataset_matches(dataset: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    path = dataset.get("path", dataset.get("filename", dataset.get("source_path")))
    repo = dataset.get("repo", dataset.get("id"))
    rows = dataset.get("rows", dataset.get("expected_rows"))
    if rows is None:
        rows = dataset.get("source_rows")
    return bool(
        repo == spec["repo"]
        and dataset.get("revision") == spec["revision"]
        and (path is None or path == spec["path"])
        and dataset.get("parquet_sha256", dataset.get("source_sha256"))
        == spec["source_sha256"]
        and (rows is None or int(rows) == int(spec["rows"]))
    )


implementation._dataset_matches = _dataset_matches

SOURCE_SPECS = implementation.SOURCE_SPECS
EXPECTED_SOURCE_IDS = implementation.EXPECTED_SOURCE_IDS
source_url = implementation.source_url
source_spec = implementation.source_spec
verify_terminal_artifact = implementation.verify_terminal_artifact
fingerprint_source = implementation.fingerprint_source
verify_source_bundle = implementation.verify_source_bundle
build_prior_registry = implementation.build_prior_registry
verify_prior_registry = implementation.verify_prior_registry
main = implementation.main


if __name__ == "__main__":
    raise SystemExit(main())
