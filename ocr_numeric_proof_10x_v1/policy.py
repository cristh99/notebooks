"""Evidence-grade numeric OCR acceptance with explicit abstention.

This policy does not replace general OCR. It creates a high-integrity numeric
channel: a canonical number is accepted only when Tesseract and PP-OCRv6 tiny
both emit it at least twice on the same page. Accepted multiplicity is the
minimum count emitted by the two independent engines. Every other number
remains ordinary OCR or abstains; it is never silently promoted as evidence.

The policy is evaluated from the exact frozen full-content quality artifact and
therefore performs no OCR in this stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "ocr-numeric-proof-10x/policy/1"
BASELINE_ENGINE = "tesseract"
SECOND_ENGINE = "pp_tiny"
MIN_REPEAT = 2
MIN_PRECISION = 0.98
MIN_REFERENCE_COVERAGE = 0.30
MIN_ACCEPTED = 300
MIN_ERROR_REDUCTION = 10.0
MIN_LOO_PASSES = 18


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def multiset_metrics(
    reference: Counter[str],
    prediction: Counter[str],
) -> dict[str, float | int]:
    true_positive = sum((reference & prediction).values())
    reference_count = sum(reference.values())
    prediction_count = sum(prediction.values())
    precision = (
        true_positive / prediction_count
        if prediction_count
        else float(reference_count == 0)
    )
    recall = (
        true_positive / reference_count
        if reference_count
        else float(prediction_count == 0)
    )
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "true_positive": true_positive,
        "reference_count": reference_count,
        "prediction_count": prediction_count,
        "precision": precision,
        "false_acceptance_rate": 1.0 - precision,
        "reference_coverage": recall,
        "f1": f1,
    }


def accepted_counter(
    first: Counter[str],
    second: Counter[str],
    *,
    min_repeat: int = MIN_REPEAT,
) -> Counter[str]:
    if min_repeat < 1:
        raise ValueError("min_repeat must be positive")
    accepted: Counter[str] = Counter()
    for token in first.keys() & second.keys():
        count = min(first[token], second[token])
        if first[token] >= min_repeat and second[token] >= min_repeat:
            accepted[token] = count
    return +accepted


def evaluate_pages(
    pages: Sequence[Mapping[str, Any]],
    *,
    min_repeat: int = MIN_REPEAT,
) -> dict[str, Any]:
    reference_all: Counter[str] = Counter()
    baseline_all: Counter[str] = Counter()
    accepted_all: Counter[str] = Counter()
    dispositions: list[dict[str, Any]] = []

    for page in pages:
        page_id = str(page["page_id"])
        reference = Counter(
            str(value)
            for value in page["reference_numeric_tokens"]
        )
        baseline = Counter(
            str(value)
            for value in page["engine_numeric_tokens"][BASELINE_ENGINE]
        )
        second = Counter(
            str(value)
            for value in page["engine_numeric_tokens"][SECOND_ENGINE]
        )
        accepted = accepted_counter(
            baseline,
            second,
            min_repeat=min_repeat,
        )
        reference_all.update(reference)
        baseline_all.update(baseline)
        accepted_all.update(accepted)
        dispositions.append(
            {
                "page_id": page_id,
                "reference_count": sum(reference.values()),
                "baseline_count": sum(baseline.values()),
                "second_engine_count": sum(second.values()),
                "accepted_count": sum(accepted.values()),
                "accepted_tokens": [
                    {"token": token, "count": accepted[token]}
                    for token in sorted(accepted)
                ],
                "abstained_baseline_count": max(
                    0,
                    sum(baseline.values()) - sum(accepted.values()),
                ),
            }
        )

    baseline_metrics = multiset_metrics(reference_all, baseline_all)
    policy_metrics = multiset_metrics(reference_all, accepted_all)
    baseline_error = float(
        baseline_metrics["false_acceptance_rate"]
    )
    policy_error = float(policy_metrics["false_acceptance_rate"])
    reduction = (
        baseline_error / policy_error
        if policy_error > 1e-15
        else None
    )
    return {
        "pages": len(pages),
        "baseline": baseline_metrics,
        "policy": policy_metrics,
        "false_acceptance_error_reduction_factor": reduction,
        "dispositions": dispositions,
    }


def loo_diagnostics(
    pages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for index, held_out in enumerate(pages):
        subset = [page for offset, page in enumerate(pages) if offset != index]
        result = evaluate_pages(subset)
        policy = result["policy"]
        reduction = result["false_acceptance_error_reduction_factor"]
        passes = bool(
            (reduction is None or float(reduction) >= MIN_ERROR_REDUCTION)
            and float(policy["precision"]) >= MIN_PRECISION
            and float(policy["reference_coverage"]) >= MIN_REFERENCE_COVERAGE
            and int(policy["prediction_count"]) >= 250
        )
        folds.append(
            {
                "held_out_page_id": held_out["page_id"],
                "passes": passes,
                "precision": policy["precision"],
                "reference_coverage": policy["reference_coverage"],
                "accepted_count": policy["prediction_count"],
                "error_reduction_factor": reduction,
            }
        )
    reductions = [
        float(fold["error_reduction_factor"])
        for fold in folds
        if fold["error_reduction_factor"] is not None
    ]
    return {
        "folds": folds,
        "passes": sum(bool(fold["passes"]) for fold in folds),
        "fold_count": len(folds),
        "minimum_error_reduction_factor": min(reductions),
        "maximum_error_reduction_factor": max(reductions),
    }


def extract_pages(quality_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for observation in quality_report.get("observations") or []:
        metrics = observation.get("metrics") or {}
        reference = observation.get("reference") or {}
        engines = observation.get("engines") or {}
        # The exact numeric token lists are not persisted in the quality
        # artifact, so rebuild them with the same canonical parser.
        from ocr_god_10x_quality_v1.full_content_quality import (
            number_tokens,
        )

        pages.append(
            {
                "page_id": str(observation["page_id"]),
                "reference_numeric_tokens": number_tokens(
                    str(reference["full"])
                ),
                "engine_numeric_tokens": {
                    BASELINE_ENGINE: number_tokens(
                        str(engines[BASELINE_ENGINE])
                    ),
                    SECOND_ENGINE: number_tokens(
                        str(engines[SECOND_ENGINE])
                    ),
                },
                "source_metric_checks": {
                    BASELINE_ENGINE: metrics[BASELINE_ENGINE][
                        "full_numeric"
                    ],
                    SECOND_ENGINE: metrics[SECOND_ENGINE][
                        "full_numeric"
                    ],
                },
            }
        )
    if len(pages) != 20:
        raise RuntimeError(
            f"expected 20 frozen pages, observed {len(pages)}"
        )
    if len({page["page_id"] for page in pages}) != len(pages):
        raise RuntimeError("duplicate page identities")
    return pages


def build_report(
    quality_report_path: Path,
    artifact_sha256: str,
) -> dict[str, Any]:
    quality = json.loads(
        quality_report_path.read_text(encoding="utf-8")
    )
    pages = extract_pages(quality)
    evaluation = evaluate_pages(pages)
    loo = loo_diagnostics(pages)
    policy = evaluation["policy"]
    reduction = evaluation[
        "false_acceptance_error_reduction_factor"
    ]
    promotion_gate = bool(
        reduction is not None
        and float(reduction) >= MIN_ERROR_REDUCTION
        and float(policy["precision"]) >= MIN_PRECISION
        and float(policy["reference_coverage"])
        >= MIN_REFERENCE_COVERAGE
        and int(policy["prediction_count"]) >= MIN_ACCEPTED
        and int(loo["passes"]) >= MIN_LOO_PASSES
    )
    verdict = (
        "PASS_NUMERIC_PROOF_CHANNEL_10X_DEVELOPMENT"
        if promotion_gate
        else "NUMERIC_PROOF_CHANNEL_GATE_FAILED"
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "quality_report_sha256": sha256_file(
                quality_report_path
            ),
            "quality_stable_payload_sha256": quality[
                "stable_payload_sha256"
            ],
            "quality_artifact_sha256": artifact_sha256,
        },
        "policy": {
            "baseline_engine": BASELINE_ENGINE,
            "second_engine": SECOND_ENGINE,
            "canonical_number_parser": (
                "same parser as repaired full-content quality audit"
            ),
            "minimum_repetitions_per_engine_per_page": MIN_REPEAT,
            "accepted_multiplicity": (
                "minimum count emitted by both engines"
            ),
            "all_other_numbers": "ABSTAIN_FROM_EVIDENCE_PROMOTION",
            "runtime_stage": False,
        },
        "gates": {
            "minimum_precision": MIN_PRECISION,
            "minimum_reference_coverage": MIN_REFERENCE_COVERAGE,
            "minimum_accepted_count": MIN_ACCEPTED,
            "minimum_false_acceptance_error_reduction": (
                MIN_ERROR_REDUCTION
            ),
            "minimum_leave_one_page_out_passes": MIN_LOO_PASSES,
        },
        "evaluation": evaluation,
        "leave_one_page_out": loo,
        "decision": {
            "verdict": verdict,
            "promotion_gate": promotion_gate,
            "automatic_production_change": False,
            "next_experiment": (
                "execute PP-OCR tiny only on Tesseract numeric crops and "
                "measure actual overhead without a second full-page OCR"
            ),
        },
        "constraints": {
            "ocr_rerun": False,
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "logic_power_in_runtime": False,
        },
    }
    payload["stable_payload_sha256"] = sha256_bytes(
        canonical_json(payload).encode("utf-8")
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_numeric_proof_10x_v1/run"),
    )
    args = parser.parse_args()
    report = build_report(
        args.quality_report,
        args.artifact_sha256,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "numeric_proof_policy.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "numeric_proof_policy.sha256").write_text(
        f"{sha256_file(path)}  numeric_proof_policy.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": str(path),
                "evaluation": report["evaluation"],
                "leave_one_page_out": report[
                    "leave_one_page_out"
                ],
                "decision": report["decision"],
                "stable_payload_sha256": report[
                    "stable_payload_sha256"
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
