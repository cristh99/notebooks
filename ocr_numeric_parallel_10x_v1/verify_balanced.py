"""Independent semantic replay for the asymmetric parallel OCR benchmark."""
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

from . import benchmark as base
from .balanced import (
    PP_THREAD_BUDGET,
    SCHEMA,
    TESSERACT_THREAD_BUDGET,
    decision_from,
    model_file_manifest,
    stable_payload,
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

        isolated = page.get("isolated") or {}
        parallel = page.get("parallel") or {}
        isolated_t = (isolated.get("tesseract") or {}).get(
            "prediction_sha256"
        )
        parallel_t = (parallel.get("tesseract") or {}).get(
            "prediction_sha256"
        )
        isolated_p = (isolated.get("pp_1024") or {}).get(
            "prediction_sha256"
        )
        parallel_p = (parallel.get("pp_1024") or {}).get(
            "prediction_sha256"
        )
        if isolated_t != parallel_t:
            errors.append(
                f"Tesseract isolated/parallel mismatch: {page.get('page_id')}"
            )
        if isolated_p != parallel_p:
            errors.append(
                f"PP isolated/parallel mismatch: {page.get('page_id')}"
            )

    rebuilt_evaluation = base.evaluate_pages(pages)
    if rebuilt_evaluation != report.get("evaluation"):
        errors.append("evaluation replay mismatch")
    rebuilt_loo = base.loo_diagnostics(pages)
    if rebuilt_loo != report.get("leave_one_page_out"):
        errors.append("leave-one-page-out replay mismatch")
    rebuilt_runtime = base.runtime_metrics(pages)
    if rebuilt_runtime != report.get("runtime"):
        errors.append("runtime replay mismatch")

    actual_tesseract: Counter[str] = Counter()
    actual_pp: Counter[str] = Counter()
    frozen_tesseract: Counter[str] = Counter()
    frozen_pp: Counter[str] = Counter()
    for page in pages:
        actual_tesseract.update(_counter(page.get("tesseract_tokens")))
        actual_pp.update(_counter(page.get("pp_1024_tokens")))
        frozen_tesseract.update(_counter(page.get("frozen_tesseract_tokens")))
        frozen_pp.update(_counter(page.get("frozen_pp_1024_tokens")))

    rebuilt_parity = {
        "tesseract_vs_frozen_speed_frontier": base.counter_parity(
            actual_tesseract,
            frozen_tesseract,
        ),
        "pp_1024_vs_frozen_speed_frontier": base.counter_parity(
            actual_pp,
            frozen_pp,
        ),
        "isolated_parallel_text_hashes_equal": all(
            (page.get("isolated") or {})
            .get("tesseract", {})
            .get("prediction_sha256")
            == (page.get("parallel") or {})
            .get("tesseract", {})
            .get("prediction_sha256")
            and (page.get("isolated") or {})
            .get("pp_1024", {})
            .get("prediction_sha256")
            == (page.get("parallel") or {})
            .get("pp_1024", {})
            .get("prediction_sha256")
            for page in pages
        ),
    }
    if rebuilt_parity != report.get("parity"):
        errors.append("parity replay mismatch")

    rebuilt_decision = decision_from(
        {
            "evaluation": rebuilt_evaluation,
            "leave_one_page_out": rebuilt_loo,
            "parity": rebuilt_parity,
            "runtime": rebuilt_runtime,
        }
    )
    decision = report.get("decision") or {}
    for field in (
        "quality_gate",
        "concurrency_parity_gate",
        "frozen_drift_detected",
        "runtime_gate",
        "promotion_gate",
        "verdict",
    ):
        if decision.get(field) != rebuilt_decision.get(field):
            errors.append(f"decision mismatch: {field}")

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
    if quality_gate != bool(decision.get("quality_gate")):
        errors.append("quality gate replay mismatch")

    contract = report.get("runtime_contract") or {}
    if int(contract.get("tesseract_thread_budget", -1)) != (
        TESSERACT_THREAD_BUDGET
    ):
        errors.append("Tesseract thread budget mismatch")
    if int(contract.get("pp_thread_budget", -1)) != PP_THREAD_BUDGET:
        errors.append("PP thread budget mismatch")
    for field in ("shared_boxes", "shared_crops", "shared_segmentation"):
        if bool(contract.get(field)):
            errors.append(f"independence contract violated: {field}")
    if contract.get("execution") != "concurrent on the same raster page":
        errors.append("execution contract mismatch")
    if bool(contract.get("output_cache_reuse")):
        errors.append("output cache reuse was enabled")

    observed_manifest = report.get("model_manifest")
    rebuilt_manifest = model_file_manifest()
    if observed_manifest != rebuilt_manifest:
        errors.append("runtime model manifest mismatch")

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
        "quality_gate": rebuilt_decision["quality_gate"],
        "concurrency_parity_gate": rebuilt_decision[
            "concurrency_parity_gate"
        ],
        "frozen_drift_detected": rebuilt_decision[
            "frozen_drift_detected"
        ],
        "runtime_gate": rebuilt_decision["runtime_gate"],
        "promotion_gate": rebuilt_decision["promotion_gate"],
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
