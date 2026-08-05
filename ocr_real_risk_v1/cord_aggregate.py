"""Exact aggregate certificate for the sealed CORD-v2 external holdout."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .cord_natural_holdout import (
    ALPHA_PER_LEG,
    COUNTERFACTUAL_MAXIMUM_RISK,
    DATASET_EXPECTED_SPLITS,
    DATASET_LICENSE,
    DATASET_REPO,
    DATASET_REVISION,
    MINIMUM_ACCEPTED,
    MINIMUM_COVERAGE,
    MINIMUM_SELECTED,
    PROTOCOL_SCHEMA,
    REPORT_SCHEMA,
    SHARD_SPECS,
    TARGET_REDUCTION,
    sha256_path,
    verify_hash_manifest,
)
from .core import canonical_json, p95, sha256_bytes
from .cord_source_seal import verify as verify_source_seal
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .sroie_natural_holdout import stable_payload, verify_stable_payload

AGGREGATE_SCHEMA = "ocr-cord-natural-numeric-aggregate/1"
REUSE_SCHEMA = "ocr-cord-natural-physical-evidence-reuse/1"
MINIMUM_STABILITY_PASS_FRACTION = 0.80


def physical_identity(
    row: Mapping[str, Any],
) -> tuple[str, tuple[int, int, int, int]]:
    bbox = tuple(int(value) for value in row["bbox"])
    if len(bbox) != 4:
        raise RuntimeError("CORD bbox identity must have four coordinates")
    return str(row["image_sha256"]), bbox


def evidence_key(
    identity: tuple[str, tuple[int, int, int, int]]
) -> str:
    image_sha, bbox = identity
    return sha256_bytes(
        canonical_json(
            {"image_sha256": image_sha, "bbox": list(bbox)}
        ).encode("utf-8")
    )


def deduplicate_physical_evidence(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[
        tuple[str, tuple[int, int, int, int]], list[dict[str, Any]]
    ] = defaultdict(list)
    for observation in observations:
        groups[physical_identity(observation)].append(dict(observation))
    unique: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    multiplicity: Counter[int] = Counter()
    for identity in sorted(groups):
        rows = sorted(
            groups[identity],
            key=lambda row: (
                str(row["split"]),
                str(row["shard_id"]),
                int(row["row_index"]),
                str(row["key"]),
            ),
        )
        representative = rows[0]
        for row in rows[1:]:
            conflicts: list[str] = []
            if row.get("truth") != representative.get("truth"):
                conflicts.append("truth")
            if row.get("annotation_text") != representative.get(
                "annotation_text"
            ):
                conflicts.append("annotation_text")
            for section, fields in {
                "tesseract": (
                    "claim",
                    "eligible",
                    "eligibility_reason",
                    "claim_correct",
                ),
                "candidate": (
                    "prediction",
                    "accepted",
                    "correct_accept",
                    "false_accept",
                ),
                "counterfactual": (
                    "claim",
                    "prediction",
                    "accepted",
                    "false_accept",
                ),
            }.items():
                for field in fields:
                    if row.get(section, {}).get(field) != representative.get(
                        section, {}
                    ).get(field):
                        conflicts.append(f"{section}.{field}")
            if conflicts:
                raise RuntimeError(
                    "conflicting outcomes for duplicate CORD physical evidence "
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
                    "association_count": len(rows),
                    "keys": [row["key"] for row in rows],
                    "splits": [row["split"] for row in rows],
                    "shards": [row["shard_id"] for row in rows],
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
        "multiplicity": {
            str(key): value for key, value in sorted(multiplicity.items())
        },
        "risk_denominator": "unique physical annotated locations",
        "groups": reused,
    }


def exact_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    minimum_accepted: int = MINIMUM_ACCEPTED,
    minimum_selected: int = MINIMUM_SELECTED,
) -> dict[str, Any]:
    selected = list(rows)
    eligible = [
        row for row in selected if bool(row["tesseract"]["eligible"])
    ]
    baseline_false = sum(
        not bool(row["tesseract"]["claim_correct"]) for row in eligible
    )
    accepted = [
        row for row in eligible if bool(row["candidate"]["accepted"])
    ]
    accepted_false = sum(
        bool(row["candidate"]["false_accept"]) for row in accepted
    )
    counter_false = sum(
        bool(row["counterfactual"]["false_accept"]) for row in selected
    )
    baseline_lower = (
        clopper_pearson_lower(
            baseline_false, len(eligible), ALPHA_PER_LEG
        )
        if eligible
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(
            accepted_false, len(accepted), ALPHA_PER_LEG
        )
        if accepted
        else 1.0
    )
    coverage_lower = (
        clopper_pearson_lower(
            len(accepted), len(selected), ALPHA_PER_LEG
        )
        if selected
        else 0.0
    )
    coverage_upper = (
        clopper_pearson_upper(
            len(accepted), len(selected), ALPHA_PER_LEG
        )
        if selected
        else 1.0
    )
    counter_upper = (
        clopper_pearson_upper(
            counter_false, len(selected), ALPHA_PER_LEG
        )
        if selected
        else 1.0
    )
    reduction_lower = (
        baseline_lower / candidate_upper if candidate_upper > 0 else None
    )
    passes = bool(
        len(selected) >= minimum_selected
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
        "minimum_selected_required": minimum_selected,
        "minimum_accepted_required": minimum_accepted,
        "pass": passes,
    }


def leave_one_shard_out_stability(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    shard_ids = sorted({str(row["shard_id"]) for row in rows})
    folds: list[dict[str, Any]] = []
    for shard_id in shard_ids:
        subset = [
            row for row in rows if str(row["shard_id"]) != shard_id
        ]
        scaled_accepted = max(
            1,
            math.floor(
                MINIMUM_ACCEPTED
                * len(subset)
                / max(len(rows), 1)
                * 0.75
            ),
        )
        summary = exact_summary(
            subset,
            minimum_accepted=scaled_accepted,
            minimum_selected=math.floor(MINIMUM_SELECTED * 0.75),
        )
        folds.append(
            {
                "held_out_shard": shard_id,
                "remaining_selected": len(subset),
                "summary": summary,
            }
        )
    passes = sum(bool(fold["summary"]["pass"]) for fold in folds)
    fraction = passes / len(folds) if folds else 0.0
    return {
        "shard_count": len(shard_ids),
        "fold_count": len(folds),
        "passes": passes,
        "pass_fraction": fraction,
        "minimum_required_pass_fraction": MINIMUM_STABILITY_PASS_FRACTION,
        "pass": bool(
            len(shard_ids) == len(SHARD_SPECS)
            and fraction >= MINIMUM_STABILITY_PASS_FRACTION
        ),
        "folds": folds,
    }


def _load_protocol(protocol_root: Path) -> dict[str, Any]:
    verify_hash_manifest(protocol_root)
    protocol = json.loads(
        (protocol_root / "protocol.json").read_text(encoding="utf-8")
    )
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RuntimeError("unexpected CORD protocol schema")
    if not verify_stable_payload(protocol, "stable_payload_sha256"):
        raise RuntimeError("CORD protocol stable hash failed")
    if protocol.get("status") != "SEALED_BEFORE_CORD_OCR":
        raise RuntimeError("CORD protocol was not sealed before OCR")
    if protocol.get("dataset") != {
        "repo": DATASET_REPO,
        "revision": DATASET_REVISION,
        "license": DATASET_LICENSE,
        "published_rows": sum(DATASET_EXPECTED_SPLITS.values()),
        "splits": dict(DATASET_EXPECTED_SPLITS),
        "shards": dict(SHARD_SPECS),
    }:
        raise RuntimeError("CORD protocol dataset identity changed")
    source_seal = json.loads(
        (protocol_root / "source_seal.json").read_text(encoding="utf-8")
    )
    if not verify_source_seal(source_seal):
        raise RuntimeError("CORD source seal stable hash failed")
    if source_seal.get("resolved_revision") != DATASET_REVISION:
        raise RuntimeError("CORD source revision changed")
    if source_seal.get("outcomes_opened") is not False:
        raise RuntimeError("CORD source seal indicates opened outcomes")
    if int(source_seal.get("parquet_rows_read", -1)) != 0:
        raise RuntimeError("CORD source seal read parquet rows")
    if protocol.get("source_seal", {}).get(
        "stable_payload_sha256"
    ) != source_seal.get("stable_payload_sha256"):
        raise RuntimeError("CORD protocol is not bound to source seal")
    if (
        protocol.get("execution_plan", {}).get(
            "candidate_bytes_fixed_before_ocr"
        )
        is not True
    ):
        raise RuntimeError("candidate was not fixed before CORD OCR")
    return protocol


def aggregate(
    protocol_root: Path,
    shard_roots: Iterable[Path],
    output_dir: Path,
) -> dict[str, Any]:
    protocol = _load_protocol(protocol_root)
    reports: dict[str, dict[str, Any]] = {}
    manifests: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []

    for root in sorted(shard_roots):
        verify_hash_manifest(root)
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        report = json.loads(
            (root / "shard_report.json").read_text(encoding="utf-8")
        )
        if report.get("schema") != REPORT_SCHEMA:
            raise RuntimeError(f"unexpected shard report schema: {root}")
        if not verify_stable_payload(manifest, "manifest_sha256"):
            raise RuntimeError(f"shard manifest stable hash failed: {root}")
        if not verify_stable_payload(
            report, "stable_payload_sha256"
        ):
            raise RuntimeError(f"shard report stable hash failed: {root}")
        shard_id = str(manifest["dataset"]["shard_id"])
        if shard_id in reports:
            raise RuntimeError(f"duplicate shard result: {shard_id}")
        protocol_manifest_path = (
            protocol_root / "manifests" / f"{shard_id}.json"
        )
        sealed_manifest = json.loads(
            protocol_manifest_path.read_text(encoding="utf-8")
        )
        if canonical_json(manifest) != canonical_json(sealed_manifest):
            raise RuntimeError(
                f"evaluated manifest differs from sealed protocol: {shard_id}"
            )
        if report["manifest_sha256"] != manifest["manifest_sha256"]:
            raise RuntimeError(
                f"report is not bound to manifest: {shard_id}"
            )
        if canonical_json(report["candidate_binding"]) != canonical_json(
            protocol["candidate_binding"]
        ):
            raise RuntimeError(
                f"report binds a different candidate: {shard_id}"
            )
        if int(report["execution"]["selected_locations"]) != len(
            report["observations"]
        ):
            raise RuntimeError(
                f"shard did not evaluate all selected rows: {shard_id}"
            )
        manifests[shard_id] = manifest
        reports[shard_id] = report
        observations.extend(
            dict(observation) for observation in report["observations"]
        )

    if set(reports) != set(SHARD_SPECS):
        raise RuntimeError(
            f"aggregate requires all six CORD shards: {sorted(reports)}"
        )
    if len(
        {
            (
                str(row["shard_id"]),
                int(row["row_index"]),
                str(row["key"]),
            )
            for row in observations
        }
    ) != len(observations):
        raise RuntimeError("duplicate receipt association across shard reports")

    unique, reuse = deduplicate_physical_evidence(observations)
    unique.sort(
        key=lambda row: (
            str(row["image_sha256"]),
            tuple(row["bbox"]),
        )
    )
    overall = exact_summary(unique)
    stability = leave_one_shard_out_stability(unique)
    split_summaries = {
        split: exact_summary(
            [row for row in unique if str(row["split"]) == split],
            minimum_accepted=max(
                1,
                math.floor(
                    MINIMUM_ACCEPTED
                    * sum(str(row["split"]) == split for row in unique)
                    / max(len(unique), 1)
                    * 0.75
                ),
            ),
            minimum_selected=max(
                1,
                math.floor(
                    MINIMUM_SELECTED
                    * sum(str(row["split"]) == split for row in unique)
                    / max(len(unique), 1)
                    * 0.75
                ),
            ),
        )
        for split in DATASET_EXPECTED_SPLITS
    }
    shard_summaries = {
        shard_id: exact_summary(
            [
                row
                for row in unique
                if str(row["shard_id"]) == shard_id
            ],
            minimum_accepted=1,
            minimum_selected=1,
        )
        for shard_id in sorted(SHARD_SPECS)
    }
    external_pass = bool(overall["pass"] and stability["pass"])
    if external_pass:
        verdict = "PASS_EXTERNAL_CORD_NATURAL_SCAN_10X_CERTIFICATE"
    elif overall["baseline_false"] == 0:
        verdict = "CORD_BASELINE_TOO_CLEAN_TO_CERTIFY"
    elif not overall["pass"]:
        verdict = "CORD_EXTERNAL_TENFOLD_BOUND_NOT_REACHED"
    else:
        verdict = "CORD_EXTERNAL_SHARD_STABILITY_FAILED"

    eligible_rows = [
        row for row in unique if bool(row["tesseract"]["eligible"])
    ]
    candidate_times = [
        float(row["candidate"]["runtime_seconds"]) * 1000.0
        for row in eligible_rows
        if float(row["candidate"]["runtime_seconds"]) > 0
    ]
    page_times = [
        float(row["tesseract"]["page_runtime"]["wall_seconds"])
        for row in unique
    ]
    reason_counts = Counter(
        str(row["tesseract"]["eligibility_reason"]) for row in unique
    )
    rows_by_split = Counter(
        str(manifest["dataset"]["split"])
        for manifest in manifests.values()
        for _ in range(int(manifest["dataset"]["rows"]))
    )

    result: dict[str, Any] = {
        "schema": AGGREGATE_SCHEMA,
        "dataset": {
            "repo": DATASET_REPO,
            "revision": DATASET_REVISION,
            "license": DATASET_LICENSE,
            "published_rows": sum(DATASET_EXPECTED_SPLITS.values()),
            "splits": dict(DATASET_EXPECTED_SPLITS),
            "shards": dict(SHARD_SPECS),
            "scope": (
                "external natural scanned-receipt benchmark; digit-forest-v3 "
                "bytes, threshold, selection, and exact gates fixed before OCR"
            ),
        },
        "candidate_binding": dict(protocol["candidate_binding"]),
        "protocol_binding": {
            "stable_payload_sha256": protocol[
                "stable_payload_sha256"
            ],
            "selected_key_set_sha256": protocol["census"][
                "selected_key_set_sha256"
            ],
            "status": protocol["status"],
        },
        "protocol": dict(protocol["gates"]),
        "execution": {
            "published_rows": sum(rows_by_split.values()),
            "published_rows_by_split": dict(sorted(rows_by_split.items())),
            "receipt_associated_selected_locations": len(observations),
            "unique_physical_locations": len(unique),
            "selected_location_yield_per_published_receipt": (
                len(observations) / sum(rows_by_split.values())
            ),
            "unique_location_yield_per_published_receipt": (
                len(unique) / sum(rows_by_split.values())
            ),
            "merchant_groups_with_selected_locations": len(
                {str(row["merchant_group"]) for row in unique}
            ),
            "eligibility_reasons": dict(sorted(reason_counts.items())),
            "ocr_timeouts": sum(
                bool(row["tesseract"]["page_runtime"]["timeout"])
                for row in unique
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
                if overall["eligible"]
                else None
            ),
            "simultaneous_95pct_lower": overall["baseline_lower"],
        },
        "candidate": {
            "accepted": overall["accepted"],
            "false_accepted": overall["accepted_false"],
            "observed_false_acceptance_rate": (
                overall["accepted_false"] / overall["accepted"]
                if overall["accepted"]
                else None
            ),
            "simultaneous_95pct_upper": overall["candidate_upper"],
            "accepted_coverage_of_selected": (
                overall["accepted"] / overall["selected"]
                if overall["selected"]
                else 0.0
            ),
            "simultaneous_95pct_coverage_lower": overall["coverage_lower"],
            "simultaneous_95pct_coverage_upper": overall["coverage_upper"],
            "certified_error_reduction_lower": overall["reduction_lower"],
            "median_runtime_ms": (
                statistics.median(candidate_times)
                if candidate_times
                else None
            ),
            "p95_runtime_ms": p95(candidate_times),
        },
        "counterfactual": {
            "cases": overall["selected"],
            "false_accepts": overall["counterfactual_false"],
            "rejection_or_abstention_rate": (
                1.0
                - overall["counterfactual_false"] / overall["selected"]
                if overall["selected"]
                else 0.0
            ),
            "simultaneous_95pct_upper": overall["counterfactual_upper"],
        },
        "stability": stability,
        "split_summaries": split_summaries,
        "shard_summaries": shard_summaries,
        "timing": {
            "median_full_image_tesseract_seconds": (
                statistics.median(page_times) if page_times else None
            ),
            "p95_full_image_tesseract_seconds": p95(page_times),
            "median_candidate_ms": (
                statistics.median(candidate_times)
                if candidate_times
                else None
            ),
            "p95_candidate_ms": p95(candidate_times),
        },
        "decision": {
            "external_natural_scan_validation_complete": True,
            "candidate_bound_before_ocr": True,
            "pass_statistical_10x": external_pass,
            "tenfold_bound_reached": bool(overall["pass"]),
            "shard_stability_passed": bool(stability["pass"]),
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
    result = stable_payload(result, "stable_payload_sha256")
    output_dir.mkdir(parents=True, exist_ok=True)
    aggregate_path = output_dir / "cord_natural_holdout_aggregate.json"
    reuse_path = output_dir / "physical_evidence_reuse.json"
    aggregate_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reuse_path.write_text(
        json.dumps(reuse, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            [
                f"{sha256_path(aggregate_path)}  {aggregate_path.name}",
                f"{sha256_path(reuse_path)}  {reuse_path.name}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-root", required=True, type=Path)
    parser.add_argument("shard_roots", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = aggregate(
        args.protocol_root, args.shard_roots, args.output_dir
    )
    print(
        json.dumps(
            {
                "execution": result["execution"],
                "baseline": result["baseline"],
                "candidate": result["candidate"],
                "counterfactual": result["counterfactual"],
                "stability": {
                    key: value
                    for key, value in result["stability"].items()
                    if key != "folds"
                },
                "timing": result["timing"],
                "decision": result["decision"],
                "stable_payload_sha256": result[
                    "stable_payload_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
