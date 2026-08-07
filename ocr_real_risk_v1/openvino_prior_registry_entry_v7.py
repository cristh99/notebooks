"""Canonical public entry point for the OpenVINO v7 prior registry.

All frozen identities live in :mod:`openvino_prior_registry_v7`.  This module is
only a stable import/CLI alias; it does not mutate implementation globals.
"""
from __future__ import annotations

from . import openvino_prior_registry_v7 as implementation

SOURCE_SPECS = implementation.SOURCE_SPECS
EXPECTED_SOURCE_IDS = implementation.EXPECTED_SOURCE_IDS
EXPECTED_TOTAL_ROWS = implementation.EXPECTED_TOTAL_ROWS
REGISTRY_STATUS = implementation.REGISTRY_STATUS
source_url = implementation.source_url
source_spec = implementation.source_spec
_dataset_matches = implementation._dataset_matches
verify_terminal_artifact = implementation.verify_terminal_artifact
fingerprint_source = implementation.fingerprint_source
verify_source_bundle = implementation.verify_source_bundle
build_prior_registry = implementation.build_prior_registry
verify_prior_registry = implementation.verify_prior_registry
main = implementation.main


if __name__ == "__main__":
    raise SystemExit(main())
