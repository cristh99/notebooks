from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from .rescue import (
    RescuePolicy,
    canonical_json,
    classify_candidate,
    digest_payload,
    sequence_accuracy,
    summarize_candidates,
)

SCHEMA = "ocr-numeric-rescue-v1/report/1"
STABLE_KEYS = (
    "schema",
    "source_canary",
    "dataset",
    "policy",
    "pages",
    "candidates",
    "metrics",
    "denominators",
    "constraints",
)


def stable_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in STABLE_KEYS}


def verify(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    try:
        expected_hash = digest_payload(stable_payload(report))
    except Exception:
        return errors + ["shape"]
    if expected_hash != report.get("stable_payload_sha256"):
        errors.append("stable-payload-hash")

    constraints = report.get("constraints") or {}
    if (
        constraints.get("external_spend_usd") != 0
        or constraints.get("gcloud_used") is not False
        or constraints.get("paid_api_used") is not False
        or constraints.get("gpu_used") is not False
    ):
        errors.append("constraints")

    pages = report.get("pages")
    candidates = report.get("candidates")
    denominators = report.get("denominators") or {}
    metrics = report.get("metrics") or {}
    if not isinstance(pages, list) or not isinstance(candidates, list):
        return sorted(set(errors + ["rows-shape"]))
    if int(denominators.get("pages", -1)) != len(pages):
        errors.append("page-denominator")
    if int(denominators.get("candidates", -1)) != len(candidates):
        errors.append("candidate-denominator")

    try:
        policy = RescuePolicy(**report["policy"])
    except Exception:
        return sorted(set(errors + ["policy-shape"]))

    page_map = {page.get("page_id"): page for page in pages}
    if len(page_map) != len(pages):
        errors.append("duplicate-page")
    candidate_ids = [item.get("candidate_id") for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("duplicate-candidate")

    for candidate in candidates:
        expected = classify_candidate(candidate, policy)
        if canonical_json(expected) != canonical_json(candidate.get("decision")):
            errors.append("candidate-decision")
            break
        if candidate.get("page_id") not in page_map:
            errors.append("candidate-page")
            break

    rebuilt_summary = summarize_candidates(candidates)
    if canonical_json(rebuilt_summary) != canonical_json(metrics.get("candidate_summary")):
        errors.append("candidate-summary")

    baseline_scores = []
    strict_scores = []
    candidates_by_page: dict[str, list[Mapping[str, Any]]] = {}
    for candidate in candidates:
        candidates_by_page.setdefault(str(candidate.get("page_id")), []).append(candidate)

    for page in pages:
        page_id = str(page.get("page_id"))
        reference = tuple(page.get("reference_numbers") or [])
        baseline = tuple(page.get("baseline_numbers") or [])
        reconstructed = list(baseline)
        for candidate in candidates_by_page.get(page_id, []):
            decision = candidate.get("decision") or {}
            if decision.get("propose_change"):
                index = int(candidate["baseline_index"])
                if not 0 <= index < len(reconstructed):
                    errors.append("candidate-index")
                    continue
                reconstructed[index] = candidate["paddle_token"]
        baseline_score = sequence_accuracy(reference, baseline)
        strict_score = sequence_accuracy(reference, reconstructed)
        baseline_scores.append(baseline_score)
        strict_scores.append(strict_score)
        if abs(float(page.get("baseline_numeric_accuracy", -9)) - baseline_score) > 1e-12:
            errors.append("page-baseline-score")
        if abs(float(page.get("strict_numeric_accuracy", -9)) - strict_score) > 1e-12:
            errors.append("page-strict-score")
        if list(page.get("strict_rescued_numbers") or []) != reconstructed:
            errors.append("page-rescued-sequence")

    avg_baseline = sum(baseline_scores) / max(len(baseline_scores), 1)
    avg_strict = sum(strict_scores) / max(len(strict_scores), 1)
    if abs(float(metrics.get("baseline_numeric_accuracy", -9)) - avg_baseline) > 1e-12:
        errors.append("aggregate-baseline-score")
    if abs(float(metrics.get("strict_numeric_accuracy", -9)) - avg_strict) > 1e-12:
        errors.append("aggregate-strict-score")
    if abs(float(metrics.get("strict_delta_pp", -9)) - 100 * (avg_strict - avg_baseline)) > 1e-10:
        errors.append("aggregate-delta")

    source = report.get("source_canary") or {}
    if source.get("run_id") != 30833428126 or source.get("artifact_id") != 8864530547:
        errors.append("source-canary")

    return sorted(set(errors))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    errors = verify(report)
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2, sort_keys=True))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
