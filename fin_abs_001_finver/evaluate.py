from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .verifier import POLICY_ID, predict, reporting_variant


UPSTREAM_COMMIT = "8aef2f48befdab5c57cc383a521711fe11c2df98"
PUBLISHED_RULE_BASELINE = {
    "source": "FinVerBench repository commit 8aef2f48, published rule-based system",
    "accuracy": 0.538,
    "precision": 1.0,
    "recall": 0.528,
    "f1": 0.691,
    "false_positive_rate": 0.0,
}
PUBLISHED_ROUNDED_CALIBRATED_FRONTIER = {
    "source": "FinVerBench paper realistic rounded diagnostic subset",
    "recall": 0.790,
    "false_positive_rate": 0.0,
}
PERMUTATION_SEED = "FIN-ABS-001A-PERMUTATION-V1"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def error_records(ground_truth: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if isinstance(ground_truth.get("errors"), list):
        return [value for value in ground_truth["errors"] if isinstance(value, Mapping)]
    return [ground_truth]


def error_locations(ground_truth: Mapping[str, Any]) -> set[str]:
    return {
        str(value.get("error_location"))
        for value in error_records(ground_truth)
        if value.get("error_location")
    }


def error_categories(ground_truth: Mapping[str, Any]) -> set[str]:
    return {
        str(value.get("error_category"))
        for value in error_records(ground_truth)
        if value.get("error_category")
    }


def is_observable(ground_truth: Mapping[str, Any], visible_paths: set[str]) -> bool:
    if not bool(ground_truth.get("has_error")):
        return True
    locations = error_locations(ground_truth)
    return bool(locations & visible_paths)


def localized(ground_truth: Mapping[str, Any], prediction: Mapping[str, Any]) -> bool:
    locations = error_locations(ground_truth)
    failed_paths = {
        path
        for check in prediction.get("failed_checks", [])
        if isinstance(check, Mapping)
        for path in check.get("paths", [])
    }
    return bool(locations & failed_paths)


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row["observable"]]
    clean = [row for row in eligible if not row["gold_error"]]
    errors = [row for row in eligible if row["gold_error"]]
    tp = sum(row["decision"] == "ERROR" for row in errors)
    fn = sum(row["decision"] != "ERROR" for row in errors)
    tn = sum(row["decision"] == "CLEAN" for row in clean)
    fp = sum(row["decision"] == "ERROR" for row in clean)
    abstain_clean = sum(row["decision"] == "ABSTAIN" for row in clean)
    abstain_error = sum(row["decision"] == "ABSTAIN" for row in errors)
    promoted = tp + fp
    fpr_denom = fp + tn
    precision = _safe_div(tp, promoted)
    recall = _safe_div(tp, tp + fn)
    specificity = _safe_div(tn, fpr_denom)
    fpr = _safe_div(fp, fpr_denom)
    accuracy = _safe_div(tp + tn, len(eligible))
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    balanced = (
        (recall + specificity) / 2
        if recall is not None and specificity is not None
        else None
    )
    detected = [row for row in errors if row["decision"] == "ERROR"]
    localization = _safe_div(
        sum(bool(row["localized"]) for row in detected),
        len(detected),
    )
    category_totals: Counter[str] = Counter()
    category_hits: Counter[str] = Counter()
    for row in errors:
        for category in row["categories"]:
            category_totals[category] += 1
            if row["decision"] == "ERROR":
                category_hits[category] += 1
    return {
        "eligible_rows": len(eligible),
        "clean_rows": len(clean),
        "observable_error_rows": len(errors),
        "true_positive": tp,
        "false_negative": fn,
        "true_negative": tn,
        "false_positive": fp,
        "clean_abstentions": abstain_clean,
        "error_abstentions": abstain_error,
        "coverage": _safe_div(len(eligible) - abstain_clean - abstain_error, len(eligible)),
        "accuracy": accuracy,
        "balanced_accuracy": balanced,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": fpr,
        "f1": f1,
        "localization_accuracy_on_detected": localization,
        "category_recall": {
            category: _safe_div(category_hits[category], count)
            for category, count in sorted(category_totals.items())
        },
    }


def evaluate_variant(instances: list[dict[str, Any]], variant: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance in instances:
        raw = instance.get("raw_statements", {})
        statement = reporting_variant(raw) if variant == "rounded_millions" else raw
        prediction = predict(statement)
        ground_truth = instance.get("ground_truth", {})
        visible_paths = set(prediction.get("visible_paths", []))
        row = {
            "instance_id": instance.get("instance_id"),
            "company": instance.get("company"),
            "period": instance.get("period"),
            "variant": variant,
            "gold_error": bool(ground_truth.get("has_error")),
            "observable": is_observable(ground_truth, visible_paths),
            "error_locations": sorted(error_locations(ground_truth)),
            "categories": sorted(error_categories(ground_truth)),
            "decision": prediction["decision"],
            "check_count": prediction["check_count"],
            "failed_count": prediction["failed_count"],
            "failed_check_ids": [value["check_id"] for value in prediction["failed_checks"]],
            "localized": localized(ground_truth, prediction),
            "prediction_sha256": digest(prediction),
        }
        rows.append(row)
    return rows, metrics(rows)


def permutation_control(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = sorted(
        (row for row in rows if row["observable"]),
        key=lambda row: digest(f"{row['instance_id']}|{PERMUTATION_SEED}"),
    )
    decisions = [row["decision"] for row in eligible]
    if decisions:
        decisions = decisions[1:] + decisions[:1]
    permuted = [dict(row, decision=decision) for row, decision in zip(eligible, decisions, strict=True)]
    return {
        "seed": PERMUTATION_SEED,
        "metrics": metrics(permuted),
    }


def build_report(
    benchmark_path: Path,
    build_manifest_path: Path,
    adapter_manifest_path: Path,
    upstream_audit_path: Path,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    instances = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if not isinstance(instances, list):
        raise ValueError("benchmark must be a list")
    build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    adapter_manifest = json.loads(adapter_manifest_path.read_text(encoding="utf-8"))
    upstream_audit = json.loads(upstream_audit_path.read_text(encoding="utf-8"))

    exact_rows, exact_metrics = evaluate_variant(instances, "exact")
    rounded_rows, rounded_metrics = evaluate_variant(instances, "rounded_millions")
    permutation = permutation_control(exact_rows)

    exact_recall = exact_metrics.get("recall") or 0.0
    exact_fpr = exact_metrics.get("false_positive_rate")
    rounded_recall = rounded_metrics.get("recall") or 0.0
    rounded_fpr = rounded_metrics.get("false_positive_rate")
    checks = {
        "external_repo_pinned": build_manifest.get("upstream_commit") == UPSTREAM_COMMIT,
        "upstream_schema_mismatch_recorded": upstream_audit.get("pipeline_status") == "SCHEMA_MISMATCH",
        "adapter_boundary_declared": "residual" in str(adapter_manifest.get("boundary", "")).lower(),
        "enough_companies": int(build_manifest.get("adapted_statement_count", 0)) >= 40,
        "enough_clean_rows": int(exact_metrics.get("clean_rows", 0)) >= 40,
        "enough_observable_errors": int(exact_metrics.get("observable_error_rows", 0)) >= 50,
        "exact_zero_fpr": exact_fpr == 0.0,
        "exact_precision_one": exact_metrics.get("precision") == 1.0,
        "exact_full_coverage": exact_metrics.get("coverage") == 1.0,
        "beats_published_rule_recall": exact_recall > PUBLISHED_RULE_BASELINE["recall"],
        "rounded_zero_fpr": rounded_fpr == 0.0,
        "rounded_recall_meets_frontier": rounded_recall >= PUBLISHED_ROUNDED_CALIBRATED_FRONTIER["recall"],
        "permutation_is_worse": (
            (permutation["metrics"].get("false_positive_rate") or 0.0) > (exact_fpr or 0.0)
            or (permutation["metrics"].get("recall") or 0.0) < exact_recall
        ),
        "no_absolute_score_promotion_from_adapter": True,
    }
    if all(checks.values()):
        status = "PASS_EXTERNAL_CONSTRUCT_VALIDITY_CANDIDATE"
    elif all(value for key, value in checks.items() if key != "rounded_recall_meets_frontier"):
        status = "PARTIAL_EXACT_PASS_ROUNDED_FRONTIER_NOT_MET"
    else:
        status = "OPEN_EXTERNAL_SLICE_DID_NOT_PASS"

    payload = {
        "schema": "fin-abs-001a/finver-external-slice/1",
        "status": status,
        "policy_id": POLICY_ID,
        "upstream": {
            "repository": "SiluPanda/finverification-bench",
            "commit": UPSTREAM_COMMIT,
            "benchmark_sha256": sha256_file(benchmark_path),
            "build_manifest_sha256": sha256_file(build_manifest_path),
            "upstream_schema_audit": upstream_audit,
        },
        "adapter": {
            "adapted_statement_count": adapter_manifest.get("adapted"),
            "excluded_statement_count": adapter_manifest.get("excluded"),
            "boundary": adapter_manifest.get("boundary"),
        },
        "published_comparators": {
            "rule_baseline": PUBLISHED_RULE_BASELINE,
            "rounded_calibrated_frontier": PUBLISHED_ROUNDED_CALIBRATED_FRONTIER,
        },
        "exact_metrics": exact_metrics,
        "rounded_metrics": rounded_metrics,
        "permutation_control": permutation,
        "gate_checks": checks,
        "absolute_score_readout": {
            "before": 423,
            "after": 423,
            "reason": (
                "The slice uses a transparent adapter because the pinned upstream repository's committed processed schema does not match its dataset builder input contract. "
                "A passing adapted slice is evidence for the next exact experiment, not authority to promote the absolute score."
            ),
        },
        "next_action": (
            "If the slice passes, reconstruct or obtain the exact upstream observable rounded subset and rerun the same policy byte-for-byte; "
            "otherwise use the failing error categories to revise the verifier before any new domain is attempted."
        ),
        "boundary": (
            "This benchmark tests visible numerical consistency. It does not value a company, predict returns, certify audited statements, or establish general Finance SOTA."
        ),
    }
    report = {"payload": payload, "sha256": digest(payload)}
    return report, {"exact": exact_rows, "rounded": rounded_rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("build_manifest", type=Path)
    parser.add_argument("adapter_manifest", type=Path)
    parser.add_argument("upstream_audit", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report, predictions = build_report(
        args.benchmark,
        args.build_manifest,
        args.adapter_manifest,
        args.upstream_audit,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for variant, rows in predictions.items():
        (args.output_dir / f"predictions_{variant}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
    payload = report["payload"]
    (args.output_dir / "report.md").write_text(
        "\n".join(
            [
                "# FIN-ABS-001A — FinVerBench external construct-validity slice",
                "",
                f"- Status: **{payload['status']}**",
                f"- Exact recall: **{payload['exact_metrics']['recall']:.4f}**",
                f"- Exact FPR: **{payload['exact_metrics']['false_positive_rate']:.4f}**",
                f"- Rounded recall: **{payload['rounded_metrics']['recall']:.4f}**",
                f"- Rounded FPR: **{payload['rounded_metrics']['false_positive_rate']:.4f}**",
                f"- Companies: **{payload['adapter']['adapted_statement_count']}**",
                f"- Report SHA-256: `{report['sha256']}`",
                "",
                "## Absolute score",
                "",
                "**423/1000 remains unchanged.** The adapter result cannot promote the broad score.",
                "",
                "## Boundary",
                "",
                payload["boundary"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": payload["status"],
        "exact_recall": payload["exact_metrics"]["recall"],
        "exact_fpr": payload["exact_metrics"]["false_positive_rate"],
        "rounded_recall": payload["rounded_metrics"]["recall"],
        "rounded_fpr": payload["rounded_metrics"]["false_positive_rate"],
        "absolute_score": 423,
        "report_sha256": report["sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
