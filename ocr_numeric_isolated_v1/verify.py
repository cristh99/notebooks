"""Independent semantic replay for the process-isolated OCR benchmark."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from ocr_god_10x_quality_v1.full_content_quality import (
    canonical_json,
    sha256_bytes,
    sha256_file,
)
from ocr_numeric_proof_10x_v1.policy import (
    MIN_ACCEPTED,
    MIN_ERROR_REDUCTION,
    MIN_LOO_PASSES,
    MIN_PRECISION,
    MIN_REFERENCE_COVERAGE,
    accepted_counter,
)

from .benchmark import (
    MAX_MEAN_EXTRA_SECONDS,
    MAX_PAIR_RATIO,
    MAX_P90_EXTRA_SECONDS,
    SCHEMA,
    affinity_evidence,
    counter_parity,
    evaluate_pages,
    loo_diagnostics,
    model_file_manifest,
    output_parity,
    runtime_metrics,
    stable_payload,
    thread_evidence,
)


def _counter(values: Any) -> Counter[str]:
    return Counter(str(value) for value in values or [])


def verify_report(
    report: Mapping[str, Any],
    *,
    quality_report_path: Path,
    speed_frontier_report_path: Path,
    quality_artifact_sha256: str,
    speed_artifact_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema mismatch")

    source = report.get("source") or {}
    if source.get("quality_report_sha256") != sha256_file(quality_report_path):
        errors.append("quality report hash mismatch")
    if source.get("speed_frontier_report_sha256") != sha256_file(
        speed_frontier_report_path
    ):
        errors.append("speed-frontier report hash mismatch")
    if source.get("quality_artifact_sha256") != quality_artifact_sha256:
        errors.append("quality artifact hash mismatch")
    if source.get("speed_artifact_sha256") != speed_artifact_sha256:
        errors.append("speed artifact hash mismatch")

    observed_digest = report.get("stable_payload_sha256")
    rebuilt_digest = sha256_bytes(
        canonical_json(stable_payload(report)).encode("utf-8")
    )
    if observed_digest != rebuilt_digest:
        errors.append("stable payload digest mismatch")

    pages = report.get("pages") or []
    if len(pages) != 20:
        errors.append(f"expected 20 pages, observed {len(pages)}")
    page_ids = [str(page.get("page_id")) for page in pages]
    if len(set(page_ids)) != len(page_ids):
        errors.append("duplicate page identities")

    for page in pages:
        tesseract = _counter(page.get("tesseract_tokens"))
        pp = _counter(page.get("pp_1024_tokens"))
        rebuilt_accepted = accepted_counter(tesseract, pp)
        observed_accepted = _counter(page.get("accepted_tokens"))
        if rebuilt_accepted != observed_accepted:
            errors.append(
                f"accepted-token replay mismatch: {page.get('page_id')}"
            )

    rebuilt_evaluation = evaluate_pages(pages)
    if rebuilt_evaluation != report.get("evaluation"):
        errors.append("evaluation replay mismatch")
    rebuilt_loo = loo_diagnostics(pages)
    if rebuilt_loo != report.get("leave_one_page_out"):
        errors.append("leave-one-page-out replay mismatch")
    rebuilt_runtime = runtime_metrics(pages)
    if rebuilt_runtime != report.get("runtime"):
        errors.append("runtime replay mismatch")
    rebuilt_threads = thread_evidence(pages)
    if rebuilt_threads != report.get("thread_evidence"):
        errors.append("thread evidence replay mismatch")
    rebuilt_output_parity = output_parity(pages)
    if rebuilt_output_parity != report.get("output_parity"):
        errors.append("output parity replay mismatch")

    affinity_report = report.get("affinity_evidence") or {}
    rebuilt_affinity = affinity_evidence(
        pages,
        affinity_report.get("original_allowed_cpus") or [],
        affinity_report.get("primary_tesseract_cpus") or [],
        int((affinity_report.get("verifier_cpus") or [-1])[0]),
        {"affinity": affinity_report.get("worker_reported_cpus") or []},
    )
    if rebuilt_affinity != affinity_report:
        errors.append("affinity evidence replay mismatch")

    actual_tesseract: Counter[str] = Counter()
    actual_pp: Counter[str] = Counter()
    frozen_tesseract: Counter[str] = Counter()
    frozen_pp: Counter[str] = Counter()
    for page in pages:
        actual_tesseract.update(_counter(page.get("tesseract_tokens")))
        actual_pp.update(_counter(page.get("pp_1024_tokens")))
        frozen_tesseract.update(_counter(page.get("frozen_tesseract_tokens")))
        frozen_pp.update(_counter(page.get("frozen_pp_1024_tokens")))
    rebuilt_drift = {
        "tesseract_vs_frozen_speed_frontier": counter_parity(
            actual_tesseract,
            frozen_tesseract,
        ),
        "pp_1024_vs_frozen_speed_frontier": counter_parity(
            actual_pp,
            frozen_pp,
        ),
        "blocking": False,
    }
    if rebuilt_drift != report.get("historical_drift_diagnostic"):
        errors.append("historical drift replay mismatch")

    rebuilt_manifest = model_file_manifest()
    if rebuilt_manifest != report.get("model_manifest"):
        errors.append("model manifest mismatch")

    policy = rebuilt_evaluation["policy"]
    reduction = rebuilt_evaluation[
        "false_acceptance_error_reduction_factor"
    ]
    quality_gate = bool(
        (reduction is None or float(reduction) >= MIN_ERROR_REDUCTION)
        and float(policy["precision"]) >= MIN_PRECISION
        and float(policy["reference_coverage"]) >= MIN_REFERENCE_COVERAGE
        and int(policy["prediction_count"]) >= MIN_ACCEPTED
        and int(rebuilt_loo["passes"]) >= MIN_LOO_PASSES
    )
    runtime_gate = bool(
        float(rebuilt_runtime["pair_ratio_to_all_core_tesseract"])
        <= MAX_PAIR_RATIO
        and float(rebuilt_runtime["mean_extra_wall_seconds_per_page"])
        <= MAX_MEAN_EXTRA_SECONDS
        and float(rebuilt_runtime["p90_extra_wall_seconds_per_page"])
        <= MAX_P90_EXTRA_SECONDS
    )
    promotion_gate = bool(
        quality_gate
        and runtime_gate
        and rebuilt_affinity["passes"]
        and rebuilt_threads["passes"]
        and rebuilt_output_parity["passes"]
    )
    verdict = (
        "PASS_PROCESS_ISOLATED_NUMERIC_PROOF_10X"
        if promotion_gate
        else (
            "QUALITY_PASS_PROCESS_RUNTIME_FAILED"
            if quality_gate
            else "PROCESS_ISOLATED_NUMERIC_PROOF_QUALITY_FAILED"
        )
    )
    decision = report.get("decision") or {}
    expected_decision = {
        "verdict": verdict,
        "quality_gate": quality_gate,
        "runtime_gate": runtime_gate,
        "affinity_gate": rebuilt_affinity["passes"],
        "thread_gate": rebuilt_threads["passes"],
        "output_parity_gate": rebuilt_output_parity["passes"],
        "promotion_gate": promotion_gate,
    }
    for field, value in expected_decision.items():
        if decision.get(field) != value:
            errors.append(f"decision mismatch: {field}")

    contract = report.get("runtime_contract") or {}
    if contract.get("charged_baseline") != (
        "Tesseract on every originally allowed CPU"
    ):
        errors.append("charged baseline contract mismatch")
    if contract.get("pp_engine") != "paddle_static":
        errors.append("PP engine mismatch")
    engine_config = contract.get("pp_engine_config") or {}
    if int(engine_config.get("cpu_threads", -1)) != 1:
        errors.append("PP thread configuration mismatch")
    for field in (
        "shared_boxes",
        "shared_crops",
        "shared_segmentation",
        "shared_output",
        "result_cache",
    ):
        if bool(contract.get(field)):
            errors.append(f"independence contract violated: {field}")

    constraints = report.get("constraints") or {}
    if float(constraints.get("external_spend_usd", -1)) != 0:
        errors.append("external spend is nonzero")
    if bool(constraints.get("gcloud_used")):
        errors.append("GCloud was used")
    if bool(constraints.get("gpu_used")):
        errors.append("GPU was used")
    if bool(constraints.get("paid_api_used")):
        errors.append("paid API was used")
    if bool(constraints.get("logic_power_in_runtime")):
        errors.append("Logic Power entered runtime")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_digest,
        "rebuilt_stable_payload_sha256": rebuilt_digest,
        "quality_gate": quality_gate,
        "runtime_gate": runtime_gate,
        "affinity_gate": rebuilt_affinity["passes"],
        "thread_gate": rebuilt_threads["passes"],
        "output_parity_gate": rebuilt_output_parity["passes"],
        "promotion_gate": promotion_gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--speed-frontier-report", type=Path, required=True)
    parser.add_argument("--quality-artifact-sha256", required=True)
    parser.add_argument("--speed-artifact-sha256", required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = verify_report(
        report,
        quality_report_path=args.quality_report,
        speed_frontier_report_path=args.speed_frontier_report,
        quality_artifact_sha256=args.quality_artifact_sha256,
        speed_artifact_sha256=args.speed_artifact_sha256,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
