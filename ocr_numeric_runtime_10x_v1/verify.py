"""Independent semantic replay for the runtime numeric proof report."""
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
)

from .runtime import (
    MAX_OVERHEAD_RATIO,
    MAX_OVERHEAD_SECONDS_PER_PAGE,
    MIN_BASELINE_PARITY_F1,
    SCHEMA,
    accepted_from_candidates,
    counter_parity,
    evaluate_pages,
    loo_diagnostics,
    stable_payload,
)


def _canonical_counter(values: Any) -> Counter[str]:
    return Counter(str(value) for value in values)


def verify_report(
    report: Mapping[str, Any],
    *,
    quality_report_path: Path,
    artifact_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema mismatch")
    source = report.get("source") or {}
    if source.get("quality_report_sha256") != sha256_file(quality_report_path):
        errors.append("quality report hash mismatch")
    if source.get("quality_artifact_sha256") != artifact_sha256:
        errors.append("quality artifact hash mismatch")

    observed_digest = report.get("stable_payload_sha256")
    rebuilt_digest = sha256_bytes(
        canonical_json(stable_payload(report)).encode("utf-8")
    )
    if observed_digest != rebuilt_digest:
        errors.append("stable payload digest mismatch")

    pages = report.get("pages") or []
    if len(pages) != 20:
        errors.append(f"expected 20 pages, observed {len(pages)}")
    if len({str(page.get("page_id")) for page in pages}) != len(pages):
        errors.append("duplicate page identities")

    for page in pages:
        rebuilt = accepted_from_candidates(page.get("candidates") or [])
        observed = _canonical_counter(page.get("accepted_tokens") or [])
        if rebuilt != observed:
            errors.append(
                f"accepted-token replay mismatch: {page.get('page_id')}"
            )
        if sum(rebuilt.values()) != int(page.get("accepted_count", -1)):
            errors.append(
                f"accepted denominator mismatch: {page.get('page_id')}"
            )
        for candidate in page.get("candidates") or []:
            baseline = candidate.get("baseline_token")
            agrees = candidate.get("paddle_token") == baseline
            if bool(candidate.get("agrees")) != bool(agrees):
                errors.append(
                    f"candidate agreement mismatch: {candidate.get('candidate_id')}"
                )

    rebuilt_evaluation = evaluate_pages(pages)
    if rebuilt_evaluation != report.get("evaluation"):
        errors.append("evaluation replay mismatch")
    rebuilt_loo = loo_diagnostics(pages)
    if rebuilt_loo != report.get("leave_one_page_out"):
        errors.append("leave-one-page-out replay mismatch")

    frozen_baseline: Counter[str] = Counter()
    runtime_baseline: Counter[str] = Counter()
    frozen_accepted: Counter[str] = Counter()
    runtime_accepted: Counter[str] = Counter()
    for page in pages:
        frozen_baseline.update(
            str(value) for value in page.get("frozen_baseline_tokens") or []
        )
        runtime_baseline.update(
            str(value) for value in page.get("baseline_tokens") or []
        )
        frozen_accepted.update(
            str(value) for value in page.get("frozen_accepted_tokens") or []
        )
        runtime_accepted.update(
            str(value) for value in page.get("accepted_tokens") or []
        )
    rebuilt_parity = {
        "runtime_vs_frozen_tesseract": counter_parity(
            runtime_baseline,
            frozen_baseline,
        ),
        "runtime_vs_frozen_accepted_channel": counter_parity(
            runtime_accepted,
            frozen_accepted,
        ),
    }
    if rebuilt_parity != report.get("parity"):
        errors.append("parity replay mismatch")

    evaluation = rebuilt_evaluation
    policy = evaluation["policy"]
    reduction = evaluation["false_acceptance_error_reduction_factor"]
    quality_gate = bool(
        (reduction is None or float(reduction) >= MIN_ERROR_REDUCTION)
        and float(policy["precision"]) >= MIN_PRECISION
        and float(policy["reference_coverage"]) >= MIN_REFERENCE_COVERAGE
        and int(policy["prediction_count"]) >= MIN_ACCEPTED
        and int(rebuilt_loo["passes"]) >= MIN_LOO_PASSES
    )
    runtime = report.get("runtime") or {}
    overhead = runtime.get("incremental_overhead") or {}
    recognition = runtime.get("recognition") or {}
    candidate_count = sum(
        len(page.get("candidates") or []) for page in pages
    )
    runtime_gate = bool(
        float(rebuilt_parity["runtime_vs_frozen_tesseract"]["f1"])
        >= MIN_BASELINE_PARITY_F1
        and float(overhead.get("mean_wall_seconds_per_page", float("inf")))
        <= MAX_OVERHEAD_SECONDS_PER_PAGE
        and float(overhead.get("ratio_to_tesseract", float("inf")))
        <= MAX_OVERHEAD_RATIO
        and int(recognition.get("crops", -1)) == candidate_count
    )
    decision = report.get("decision") or {}
    if bool(decision.get("quality_gate")) != quality_gate:
        errors.append("quality decision mismatch")
    if bool(decision.get("runtime_gate")) != runtime_gate:
        errors.append("runtime decision mismatch")
    if bool(decision.get("promotion_gate")) != (quality_gate and runtime_gate):
        errors.append("promotion decision mismatch")

    contract = report.get("runtime_contract") or {}
    if int(contract.get("full_page_ocr_passes", -1)) != 1:
        errors.append("full-page pass count is not one")
    if bool(contract.get("second_detector")):
        errors.append("second detector was enabled")
    constraints = report.get("constraints") or {}
    if bool(constraints.get("logic_power_in_runtime")):
        errors.append("Logic Power entered runtime")
    if float(constraints.get("external_spend_usd", -1)) != 0:
        errors.append("external spend is nonzero")

    return {
        "valid": not errors,
        "errors": errors,
        "observed_stable_payload_sha256": observed_digest,
        "rebuilt_stable_payload_sha256": rebuilt_digest,
        "quality_gate": quality_gate,
        "runtime_gate": runtime_gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = verify_report(
        report,
        quality_report_path=args.quality_report,
        artifact_sha256=args.artifact_sha256,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
