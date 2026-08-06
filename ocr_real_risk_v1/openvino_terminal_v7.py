"""Independent terminal adjudicator for the OpenVINO v7 metadata gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .core import canonical_json, sha256_bytes
from .openvino_adapter_v7 import (
    ADAPTER_SCHEMA,
    CENSUS_SCHEMA,
    DATASET_REVISION,
    DEVELOPMENT_ACCEPTANCE_RATE,
    MINIMUM_ACCEPTED,
    MINIMUM_SELECTED,
    REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS,
    SOURCE_PATH,
    SOURCE_SHA256,
    SOURCE_SIZE_BYTES,
)
from .openvino_source_seal_v7 import verify as verify_source_seal

TERMINAL_SCHEMA = "ocr-openvino-v7-census-terminal/1"
CANDIDATE_ID = "numeric-consensus-v7-openvino"
PREDECESSOR_STABLE = (
    "33d14875f0d2f9681ced662e452a5f28943ecb65e30a9242663d6a472034da9d"
)


def verify_stable(payload: Mapping[str, Any]) -> bool:
    stable = dict(payload)
    observed = str(stable.pop("stable_payload_sha256", ""))
    return observed == sha256_bytes(canonical_json(stable).encode("utf-8"))


def _assert_constraints(value: object) -> None:
    expected = {
        "external_spend_usd": 0,
        "gcloud_used": False,
        "gpu_used": False,
        "paid_api_used": False,
        "production_modified": False,
    }
    if value != expected:
        raise RuntimeError("OpenVINO constraints changed")


def adjudicate(
    report: Mapping[str, Any],
    candidate: Mapping[str, Any],
    source_seal: Mapping[str, Any],
    *,
    source_commit: str,
    census_file_sha256: str,
) -> dict[str, Any]:
    if len(source_commit) != 40:
        raise RuntimeError("full source commit required")
    if len(census_file_sha256) != 64:
        raise RuntimeError("census file SHA-256 is invalid")
    if not verify_stable(report):
        raise RuntimeError("census stable payload mismatch")
    if not verify_stable(candidate):
        raise RuntimeError("candidate stable payload mismatch")
    if not verify_source_seal(source_seal):
        raise RuntimeError("source seal stable payload mismatch")

    if (
        report.get("schema") != CENSUS_SCHEMA
        or report.get("adapter_schema") != ADAPTER_SCHEMA
    ):
        raise RuntimeError("OpenVINO census schema mismatch")
    dataset = report["dataset"]
    if (
        dataset.get("revision") != DATASET_REVISION
        or dataset.get("source_path") != SOURCE_PATH
        or dataset.get("source_sha256") != SOURCE_SHA256
        or dataset.get("source_size_bytes") != SOURCE_SIZE_BYTES
    ):
        raise RuntimeError("OpenVINO dataset binding mismatch")
    if (
        candidate.get("candidate_id") != CANDIDATE_ID
        or candidate.get("source_commit") != source_commit
        or candidate["predecessor_v7"]["stable_payload_sha256"]
        != PREDECESSOR_STABLE
        or candidate["metadata_power_gate"]["image_column_forbidden"]
        is not True
        or candidate["metadata_power_gate"][
            "full_image_download_authorized_in_this_gate"
        ]
        is not False
    ):
        raise RuntimeError("OpenVINO candidate binding mismatch")
    binding = report["candidate_binding"]
    if (
        binding.get("stable_payload_sha256")
        != candidate.get("stable_payload_sha256")
        or binding.get("source_commit") != source_commit
    ):
        raise RuntimeError("census does not bind the frozen candidate")
    source = source_seal["source_object"]
    if (
        source.get("path") != SOURCE_PATH
        or source.get("sha256") != SOURCE_SHA256
        or source.get("size_bytes") != SOURCE_SIZE_BYTES
        or source_seal.get("outcomes_opened") is not False
        or source_seal.get("images_opened") != 0
    ):
        raise RuntimeError("OpenVINO source seal mismatch")

    schema = report["schema_fingerprint"]
    if (
        schema.get("image_column_read") is not False
        or schema.get("stage_a_columns_only") != ["texts"]
        or schema.get("stage_b_columns_only")
        != ["texts", "bboxes", "polygons", "num_text_regions"]
    ):
        raise RuntimeError("forbidden OpenVINO columns were read")
    selection = report["selection"]
    if (
        selection.get("uses_image_bytes") is not False
        or selection.get("uses_ocr") is not False
        or selection.get("uses_candidate_output") is not False
    ):
        raise RuntimeError("metadata gate opened outcomes")

    stage_a = report["stage_a_texts_only_upper_bound"]
    rows_scanned = int(stage_a["row_count"])
    upper_bound = int(stage_a["selected_upper_bound"])
    if rows_scanned < upper_bound:
        raise RuntimeError("selected upper bound exceeds row count")
    if (
        int(stage_a["required_selected_for_projected_verified"])
        != REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS
    ):
        raise RuntimeError("OpenVINO power threshold changed")
    exact_required = bool(stage_a["exact_geometry_stage_required"])
    exact = report.get("exact_census")
    power = report["power_gate"]
    if exact_required:
        if exact is None:
            raise RuntimeError("exact geometry census is missing")
        records = exact["records"]
        selected = int(exact["selected_count"])
        if selected != len(records):
            raise RuntimeError("exact selected count mismatch")
        if len({int(row["row_index"]) for row in records}) != selected:
            raise RuntimeError("exact census contains duplicate risk units")
        if (
            power.get("decision_is_exact") is not True
            or power.get("decision_basis") != "exact_geometry_census"
        ):
            raise RuntimeError("exact decision basis mismatch")
    else:
        if exact is not None:
            raise RuntimeError("geometry opened after conclusive upper-bound fail")
        selected = upper_bound
        if upper_bound >= REQUIRED_SELECTED_FOR_PROJECTED_ACCEPTS:
            raise RuntimeError("upper bound was not conclusive")
        if (
            power.get("decision_is_exact") is not False
            or power.get("decision_basis")
            != "texts_only_conservative_upper_bound"
        ):
            raise RuntimeError("upper-bound decision basis mismatch")

    projected = selected * DEVELOPMENT_ACCEPTANCE_RATE
    expected_power = bool(
        exact_required
        and selected >= MINIMUM_SELECTED
        and projected >= MINIMUM_ACCEPTED
    )
    if (
        int(power["selected_available"]) != selected
        or not math.isclose(
            float(power["projected_accepted"]),
            projected,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or bool(power["metadata_power_pass"]) != expected_power
        or bool(
            power["separate_full_gate_eligible_after_license_review"]
        )
        != expected_power
        or power.get("full_image_download_authorized") is not False
        or power.get("ocr_authorized") is not False
        or power.get("decision_is_conclusive") is not True
    ):
        raise RuntimeError("OpenVINO power adjudication mismatch")

    decision = report["decision"]
    if (
        decision.get("image_bytes_opened") is not False
        or decision.get("ocr_executed") is not False
        or decision.get("candidate_inference_executed") is not False
        or decision.get(
            "license_review_required_before_full_image_download"
        )
        is not True
    ):
        raise RuntimeError("OpenVINO decision boundary mismatch")
    expected_verdict = (
        "OPENVINO_V7_SCHEMA_AND_POWER_GATE_PASS"
        if expected_power
        else (
            "OPENVINO_V7_TERMINAL_EXACT_POWER_FAIL"
            if exact_required
            else "OPENVINO_V7_TERMINAL_UPPER_BOUND_POWER_FAIL"
        )
    )
    if decision.get("verdict") != expected_verdict:
        raise RuntimeError("OpenVINO verdict mismatch")
    _assert_constraints(report.get("constraints"))

    status = (
        "READY_FOR_LICENSE_REVIEW_AND_SEPARATE_FULL_GATE"
        if expected_power
        else (
            "TERMINAL_EXACT_POWER_FAIL"
            if exact_required
            else "TERMINAL_UPPER_BOUND_POWER_FAIL"
        )
    )
    terminal: dict[str, Any] = {
        "schema": TERMINAL_SCHEMA,
        "status": status,
        "scientific_verdict": "UNKNOWN_NO_IMAGE_OUTCOMES_OPENED",
        "metadata_power_pass": expected_power,
        "separate_full_gate_eligible_after_license_review": expected_power,
        "full_image_download_authorized": False,
        "ocr_authorized": False,
        "decision_basis": power["decision_basis"],
        "rows_scanned": rows_scanned,
        "selected_or_upper_bound": selected,
        "projected_verified_claims": projected,
        "minimum_selected": MINIMUM_SELECTED,
        "minimum_projected_verified_claims": MINIMUM_ACCEPTED,
        "candidate_stable_payload_sha256": candidate[
            "stable_payload_sha256"
        ],
        "predecessor_stable_payload_sha256": PREDECESSOR_STABLE,
        "source_seal_stable_payload_sha256": source_seal[
            "stable_payload_sha256"
        ],
        "census_stable_payload_sha256": report["stable_payload_sha256"],
        "census_file_sha256": census_file_sha256,
        "candidate_source_commit": source_commit,
        "image_bytes_opened": False,
        "ocr_executed": False,
        "candidate_inference_executed": False,
        "license_review_complete": False,
        "external_spend_usd": 0,
        "automatic_production_change": False,
    }
    terminal["stable_payload_sha256"] = sha256_bytes(
        canonical_json(terminal).encode("utf-8")
    )
    return terminal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--census", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--source-seal", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    census_bytes = args.census.read_bytes()
    terminal = adjudicate(
        json.loads(census_bytes),
        json.loads(args.candidate.read_text()),
        json.loads(args.source_seal.read_text()),
        source_commit=args.source_commit,
        census_file_sha256=hashlib.sha256(census_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(terminal, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(terminal, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
