"""Conservative aggregate for the external SROIE natural-scan holdout."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import canonical_json, p95, sha256_bytes
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .sroie_natural_holdout import (
    DATASET_EXPECTED_ROWS,
    DATASET_LICENSE,
    DATASET_PARQUET_SHA256,
    DATASET_REPO,
    DATASET_REVISION,
    MANIFEST_SCHEMA,
    REPORT_SCHEMA,
    sha256_path,
    verify_stable_payload,
)

AGGREGATE_SCHEMA = "ocr-sroie-natural-numeric-aggregate/1"
REUSE_SCHEMA = "ocr-sroie-natural-physical-evidence-reuse/1"
FAMILY_ALPHA = 0.05
ALPHA_PER_LEG = FAMILY_ALPHA / 4.0
TARGET_REDUCTION = 10.0
MINIMUM_SELECTED = 583
MINIMUM_ACCEPTED = 100
MINIMUM_COVERAGE = 0.25
COUNTERFACTUAL_MAXIMUM_RISK = 0.01
MINIMUM_COMPANIES = 50
MINIMUM_COMPANY_FOLD_PASS_FRACTION = 0.80


def verify_hash_manifest(root: Path) -> None:
    manifest = root / "SHA256SUMS.txt"
    if not manifest.exists():
        raise RuntimeError(f"missing SHA256SUMS.txt in {root}")
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        target = root / relative
        if sha256_path(target) != expected:
            raise RuntimeError(f"hash mismatch: {target}")


def physical_identity(row: Mapping[str, Any]) -> tuple[str, tuple[int, int, int, int]]:
    bbox = tuple(int(value) for value in row["bbox"])
    if len(bbox) != 4:
        raise ValueError("SROIE bbox identity must contain four coordinates")
    return str(row["image_sha256"]), bbox


def evidence_key(identity: tuple[str, tuple[int, int, int, int]]) -> str:
    image_sha, bbox = identity
    return sha256_bytes(
        canonical_json({"image_sha256": image_sha, "bbox": list(bbox)}).encode("utf-8")
    )


def deduplicate_physical_evidence(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[
        tuple[str, tuple[int, int, int, int]], list[dict[str, Any]]
    ] = defaultdict(list)
    for observation in observations:
        groups[physical_identity(observation)].append(dict(observation))
    outcome_fields = ("truth", "annotation_text", "tesseract", "verifier", "counterfactual")
    unique: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    multiplicity: Counter[int] = Counter()
    for identity in sorted(groups):
        rows = sorted(
            groups[identity],
            key=lambda row: (str(row["split"]), int(row["row_index"]), str(row["key"])),
        )
        representative = rows[0]
        for row in rows[1:]:
            conflicts = [
                field for field in outcome_fields if row.get(field) != representative.get(field)
            ]
            if conflicts:
                raise RuntimeError(
                    "conflicting annotation or OCR outcome for duplicate SROIE physical evidence "
                    f"{evidence_key(identity)}: {conflicts}"
                )
        unique.append(representative)
        multiplicity[len(rows)] += 1
        if len(rows) > 1:
            reused.append(
                {
                    "evidence_key": evidence_key(identity),
                    "image_sha256": identity[0],
                    "bbox": list(identity[1]),
                    "truth": representative["truth"],
                    "association_count": len(rows),
                    "keys": [row["key"] for row in rows],
                    "splits": [row["split"] for row in rows],
                    "outcomes_identical": True,
                }
            )
    return unique, {
        "schema": REUSE_SCHEMA,
        "receipt_associated_locations": len(observations),
        "unique_physical_locations": len(unique),
        "duplicate_receipt_associations": len(observations) - len(unique),
        "reused_location_groups": len(reused),
        "maximum_receipts_per_location": max(multiplicity, default=0),
        "multiplicity": {str(key): value for key, value in sorted(multiplicity.items())},
        "risk_denominator": "unique physical annotated locations",
        "selection_denominator": "published receipt rows with a selected numeric annotation",
        "groups": reused,
    }


def exact_summary(
    rows: Sequence[Mapping[str, Any]], *, minimum_accepted: int
) -> dict[str, Any]:
    selected = list(rows)
    eligible = [row for row in selected if row["tesseract"]["eligible"]]
    baseline_false = sum(not row["tesseract"]["claim_correct"] for row in eligible)
    accepted = [row for row in eligible if row["verifier"]["accepted"]]
    accepted_false = sum(row["verifier"]["false_accept"] for row in accepted)
    counter_false = sum(row["counterfactual"]["false_accept"] for row in selected)
    baseline_lower = (
        clopper_pearson_lower(baseline_false, len(eligible), ALPHA_PER_LEG)
        if eligible else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(accepted_false, len(accepted), ALPHA_PER_LEG)
        if accepted else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(len(accepted), len(selected), ALPHA_PER_LEG)
        if selected else 0.0
    )
    coverage_upper = (
        clopper_pearson_upper(len(accepted), len(selected), ALPHA_PER_LEG)
        if selected else 1.0
    )
    counter_upper = (
        clopper_pearson_upper(counter_false, len(selected), ALPHA_PER_LEG)
        if selected else 1.0
    )
    reduction_lower = baseline_lower / candidate_upper if candidate_upper > 0 else None
    passes = bool(
        len(selected) >= MINIMUM_SELECTED
        and baseline_false > 0
        and len(accepted) >= minimum_accepted
        and coverage_lower >= MINIMUM_COVERAGE
        and candidate_upper <= baseline_lower / TARGET_REDUCTION
        and counter_upper <= COUNTERFACTUAL_MAXIMUM_RISK
    )
    return {
        "selected": len(selected),
        "eligible": len(eligible),
        "baseline_false": baseline_false,
        "accepted": len(accepted),
        "accepted_false": accepted_false,
        "counterfactual_false": counter_false,
        "baseline_lower": baseline_lower,
        "candidate_upper": candidate_upper,
        "coverage_lower": coverage_lower,
        "coverage_upper": coverage_upper,
        "counterfactual_upper": counter_upper,
        "reduction_lower": reduction_lower,
        "minimum_accepted_required": minimum_accepted,
        "pass": passes,
    }


def company_stability(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    companies = sorted({str(row["company_group"]) for row in rows})
    folds: list[dict[str, Any]] = []
    for company in companies:
        subset = [row for row in rows if str(row["company_group"]) != company]
        scaled_minimum = max(
            1,
            math.floor(MINIMUM_ACCEPTED * len(subset) / max(len(rows), 1) * 0.75),
        )
        summary = exact_summary(subset, minimum_accepted=scaled_minimum)
        folds.append(
            {
                "held_out_company": company,
                "remaining_selected": len(subset),
                "summary": summary,
            }
        )
    passes = sum(fold["summary"]["pass"] for fold in folds)
    fraction = passes / len(folds) if folds else 0.0
    return {
        "company_count": len(companies),
        "fold_count": len(folds),
        "passes": passes,
        "pass_fraction": fraction,
        "minimum_required_pass_fraction": MINIMUM_COMPANY_FOLD_PASS_FRACTION,
        "pass": bool(
            len(companies) >= MINIMUM_COMPANIES
            and fraction >= MINIMUM_COMPANY_FOLD_PASS_FRACTION
        ),
        "folds": folds,
    }


def aggregate(roots: Iterable[Path], output_dir: Path) -> dict[str, Any]:
    manifests: dict[str, dict[str, Any]] = {}
    reports: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for root in sorted(roots):
        verify_hash_manifest(root)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        report = json.loads((root / "split_report.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise RuntimeError("unexpected SROIE manifest schema")
        if report.get("schema") != REPORT_SCHEMA:
            raise RuntimeError("unexpected SROIE split report schema")
        if not verify_stable_payload(manifest, "manifest_sha256"):
            raise RuntimeError("SROIE manifest stable hash failed")
        if not verify_stable_payload(report, "stable_payload_sha256"):
            raise RuntimeError("SROIE split report stable hash failed")
        split = str(manifest["dataset"]["split"])
        if split in manifests:
            raise RuntimeError(f"duplicate SROIE split artifact: {split}")
        if report["manifest_sha256"] != manifest["manifest_sha256"]:
            raise RuntimeError("split report is not bound to its manifest")
        manifests[split] = manifest
        reports[split] = report
        observations.extend(dict(row) for row in report["observations"])
    if set(manifests) != set(DATASET_EXPECTED_ROWS):
        raise RuntimeError("SROIE aggregate requires exactly train and test")
    for split, expected_rows in DATASET_EXPECTED_ROWS.items():
        manifest = manifests[split]
        report = reports[split]
        if manifest["dataset"] != {
            "repo": DATASET_REPO,
            "revision": DATASET_REVISION,
            "license": DATASET_LICENSE,
            "split": split,
            "parquet_sha256": DATASET_PARQUET_SHA256[split],
            "expected_rows": expected_rows,
        }:
            raise RuntimeError(f"SROIE {split} dataset identity changed")
        if int(manifest["census"]["rows"]) != expected_rows:
            raise RuntimeError(f"SROIE {split} row count mismatch")
        if int(report["execution"]["selected_locations"]) != len(report["observations"]):
            raise RuntimeError(f"SROIE {split} did not evaluate every selected location")
    if len({(row["split"], row["key"]) for row in observations}) != len(observations):
        raise RuntimeError("duplicate receipt association across split reports")

    unique, reuse = deduplicate_physical_evidence(observations)
    unique.sort(key=lambda row: (str(row["image_sha256"]), tuple(row["bbox"])))
    overall = exact_summary(unique, minimum_accepted=MINIMUM_ACCEPTED)
    stability = company_stability(unique)
    split_summaries = {
        split: exact_summary(
            [row for row in unique if row["split"] == split],
            minimum_accepted=max(
                1,
                math.floor(
                    MINIMUM_ACCEPTED
                    * sum(row["split"] == split for row in unique)
                    / max(len(unique), 1)
                    * 0.75
                ),
            ),
        )
        for split in sorted(DATASET_EXPECTED_ROWS)
    }
    eligible = [row for row in unique if row["tesseract"]["eligible"]]
    page_times = [row["tesseract"]["page_runtime"]["wall_seconds"] for row in unique]
    verifier_times = [
        row["verifier"]["runtime_seconds"] * 1000.0
        for row in eligible if row["verifier"]["runtime_seconds"] > 0
    ]
    reason_counts = Counter(row["tesseract"]["eligibility_reason"] for row in unique)
    selected_associations = sum(len(report["observations"]) for report in reports.values())
    total_rows = sum(DATASET_EXPECTED_ROWS.values())
    external_pass = bool(overall["pass"] and stability["pass"])
    if external_pass:
        verdict = "PASS_EXTERNAL_NATURAL_SCAN_10X_CERTIFICATE"
    elif overall["baseline_false"] == 0:
        verdict = "EXTERNAL_NATURAL_SCAN_BASELINE_TOO_CLEAN_TO_CERTIFY"
    elif not overall["pass"]:
        verdict = "EXTERNAL_NATURAL_SCAN_TENFOLD_BOUND_NOT_REACHED"
    else:
        verdict = "EXTERNAL_NATURAL_SCAN_COMPANY_STABILITY_FAILED"

    result: dict[str, Any] = {
        "schema": AGGREGATE_SCHEMA,
        "dataset": {
            "repo": DATASET_REPO,
            "revision": DATASET_REVISION,
            "license": DATASET_LICENSE,
            "published_rows": total_rows,
            "splits": dict(DATASET_EXPECTED_ROWS),
            "parquet_sha256": dict(DATASET_PARQUET_SHA256),
            "scope": (
                "external natural scanned-receipt benchmark; verifier and protocol "
                "frozen before executing either published split"
            ),
        },
        "protocol": {
            **dict(next(iter(manifests.values()))["protocol"]),
            "family_alpha": FAMILY_ALPHA,
            "alpha_per_leg_bonferroni": ALPHA_PER_LEG,
            "target_error_reduction": TARGET_REDUCTION,
            "minimum_selected": MINIMUM_SELECTED,
            "minimum_accepted": MINIMUM_ACCEPTED,
            "minimum_coverage_lower": MINIMUM_COVERAGE,
            "counterfactual_maximum_upper": COUNTERFACTUAL_MAXIMUM_RISK,
            "minimum_companies": MINIMUM_COMPANIES,
            "minimum_company_fold_pass_fraction": MINIMUM_COMPANY_FOLD_PASS_FRACTION,
            "risk_denominator": "unique physical annotated locations",
        },
        "execution": {
            "published_rows": total_rows,
            "receipt_associated_selected_locations": selected_associations,
            "selected_location_yield_per_published_receipt": selected_associations / total_rows,
            "unique_physical_locations": len(unique),
            "unique_location_yield_per_published_receipt": len(unique) / total_rows,
            "companies_with_selected_locations": len(
                {row["company_group"] for row in unique}
            ),
            "eligibility_reasons": dict(sorted(reason_counts.items())),
            "ocr_timeouts": sum(
                row["tesseract"]["page_runtime"]["timeout"] for row in unique
            ),
            "physical_evidence_reuse": {
                key: value for key, value in reuse.items() if key != "groups"
            },
        },
        "baseline": {
            "claims": overall["eligible"],
            "false_predictions": overall["baseline_false"],
            "observed_error_rate": (
                overall["baseline_false"] / overall["eligible"]
                if overall["eligible"] else None
            ),
            "simultaneous_95pct_lower": overall["baseline_lower"],
        },
        "verifier": {
            "accepted": overall["accepted"],
            "false_accepted": overall["accepted_false"],
            "observed_false_acceptance_rate": (
                overall["accepted_false"] / overall["accepted"]
                if overall["accepted"] else None
            ),
            "simultaneous_95pct_upper": overall["candidate_upper"],
            "accepted_coverage_of_selected": (
                overall["accepted"] / overall["selected"]
                if overall["selected"] else 0.0
            ),
            "simultaneous_95pct_coverage_lower": overall["coverage_lower"],
            "simultaneous_95pct_coverage_upper": overall["coverage_upper"],
            "certified_error_reduction_lower": overall["reduction_lower"],
            "median_runtime_ms": statistics.median(verifier_times) if verifier_times else None,
            "p95_runtime_ms": p95(verifier_times),
        },
        "counterfactual": {
            "cases": overall["selected"],
            "false_accepts": overall["counterfactual_false"],
            "rejection_or_abstention_rate": (
                1 - overall["counterfactual_false"] / overall["selected"]
                if overall["selected"] else None
            ),
            "simultaneous_95pct_upper": overall["counterfactual_upper"],
        },
        "stability": stability,
        "split_summaries": split_summaries,
        "timing": {
            "median_full_image_tesseract_seconds": (
                statistics.median(page_times) if page_times else None
            ),
            "p95_full_image_tesseract_seconds": p95(page_times),
            "median_verifier_ms": statistics.median(verifier_times) if verifier_times else None,
            "p95_verifier_ms": p95(verifier_times),
        },
        "decision": {
            "external_natural_scan_validation_complete": True,
            "tenfold_bound_reached": external_pass,
            "pass_statistical_10x": external_pass,
            "automatic_production_change": False,
            "honduras_production_readiness_claimed": False,
            "verdict": verdict,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    result["stable_payload_sha256"] = sha256_bytes(
        canonical_json(result).encode("utf-8")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "sroie_natural_holdout_aggregate.json"
    reuse_path = output_dir / "physical_evidence_reuse.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reuse_path.write_text(
        json.dumps(reuse, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"{sha256_path(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = aggregate(args.roots, args.output_dir)
    print(
        json.dumps(
            {
                "execution": result["execution"],
                "baseline": result["baseline"],
                "verifier": result["verifier"],
                "counterfactual": result["counterfactual"],
                "stability": {
                    key: value for key, value in result["stability"].items() if key != "folds"
                },
                "timing": result["timing"],
                "decision": result["decision"],
                "stable_payload_sha256": result["stable_payload_sha256"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
