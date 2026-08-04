from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .core import (
    SCORE_BEFORE,
    build_benchmark,
    build_report,
    canonical,
    digest,
    evaluate_rows,
    inject_error,
    relation_check,
)
from .sec import acquire_relations


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def synthetic_relation() -> dict[str, Any]:
    context = {"period_type": "instant", "end": "2025-12-31"}

    def fact(concept: str, value: float) -> dict[str, Any]:
        return {
            "concept": concept,
            "value": value,
            "provenance": {
                "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                "cik": "0000000001",
                "sic": "9999",
                "concept": concept,
                "unit": "USD",
                "accession": "0000000001-25-000001",
                "filed": "2026-01-31",
                "form": "10-K",
                "context": context,
                "frame": None,
            },
        }

    relation = {
        "relation_id": "SYNTHETIC_BALANCE",
        "family": "BALANCE_IDENTITY",
        "company": "Synthetic Co.",
        "ticker": "SYN",
        "cik": "0000000001",
        "sic": "9999",
        "accession": "0000000001-25-000001",
        "context": context,
        "observed": fact("Assets", 1_000_000_000.0),
        "terms": [
            {**fact("Liabilities", 600_000_000.0), "coefficient": 1.0},
            {**fact("StockholdersEquity", 400_000_000.0), "coefficient": 1.0},
        ],
        "adapter": None,
        "selection_rule": "synthetic self-test only",
    }
    relation["relation_uid"] = digest({"synthetic": relation["relation_id"], "context": context})
    return relation


def self_test() -> None:
    relation = synthetic_relation()
    assert relation_check(relation, "exact")["passed"]
    assert relation_check(relation, "rounded_millions")["passed"]
    altered = inject_error(relation)
    assert not relation_check(altered, "exact")["passed"]
    assert canonical({"x": 1.0}) == canonical({"x": 1})
    assert digest({"b": 2, "a": 1}) == digest({"a": 1, "b": 2})
    rows = build_benchmark([relation])
    assert len(rows) == 2
    exact = evaluate_rows(rows, "exact")
    assert [row["decision"] for row in exact] == ["CLEAN", "ERROR"]
    rounded = evaluate_rows(rows, "rounded_millions")
    assert rounded[0]["decision"] == "CLEAN"
    report = build_report(
        relations=[relation],
        benchmark=rows,
        exact_predictions=exact,
        rounded_predictions=rounded,
        acquisition={"official_sec_endpoint_only": True, "frozen_company_universe": True},
    )
    assert report["payload"]["score"]["after"] == SCORE_BEFORE
    forged = copy.deepcopy(report)
    forged["payload"]["score"]["after"] = 1000
    assert digest(forged["payload"]) != forged["sha256"]
    print(json.dumps({"self_test": "PASS", "checks": 10}, sort_keys=True))


def execute(cache_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    relations, acquisition = acquire_relations(cache_dir)
    benchmark = build_benchmark(relations)
    exact_predictions = evaluate_rows(benchmark, "exact")
    rounded_predictions = evaluate_rows(benchmark, "rounded_millions")

    acquisition_path = output_dir / "acquisition.json"
    relations_path = output_dir / "relations.json"
    benchmark_path = output_dir / "benchmark.jsonl"
    exact_path = output_dir / "predictions_exact.jsonl"
    rounded_path = output_dir / "predictions_rounded.jsonl"
    write_json(acquisition_path, acquisition)
    write_json(relations_path, relations)
    write_jsonl(benchmark_path, benchmark)
    write_jsonl(exact_path, exact_predictions)
    write_jsonl(rounded_path, rounded_predictions)

    acquisition_for_report = dict(acquisition)
    acquisition_for_report["evidence_sha256"] = {
        "acquisition": sha256_file(acquisition_path),
        "relations": sha256_file(relations_path),
        "benchmark": sha256_file(benchmark_path),
        "predictions_exact": sha256_file(exact_path),
        "predictions_rounded": sha256_file(rounded_path),
    }
    report = build_report(
        relations=relations,
        benchmark=benchmark,
        exact_predictions=exact_predictions,
        rounded_predictions=rounded_predictions,
        acquisition=acquisition_for_report,
    )
    report_path = output_dir / "report.json"
    write_json(report_path, report)

    payload = report["payload"]
    exact = payload["exact_metrics"]
    rounded = payload["rounded_metrics"]
    failed = [name for name, passed in payload["gate_checks"].items() if not passed]
    markdown = [
        "# FIN-ABS-001B — direct SEC breadth benchmark",
        "",
        f"- Status: **{payload['status']}**",
        f"- Absolute score: **{payload['score']['before']} → {payload['score']['after']}**",
        f"- Eligible companies: **{payload['cohort']['eligible_companies']}**",
        f"- Companies with at least two relations: **{payload['cohort']['companies_with_two_relations']}**",
        f"- SIC codes: **{payload['cohort']['sic_codes']}**",
        f"- Direct relations: **{payload['cohort']['direct_relations']}**",
        f"- Exact recall / FPR: **{exact['recall']:.4f} / {exact['false_positive_rate']:.4f}**",
        f"- Rounded recall / FPR: **{rounded['recall']:.4f} / {rounded['false_positive_rate']:.4f}**",
        f"- Failed gates: **{', '.join(failed) if failed else 'none'}**",
        f"- Report SHA-256: `{report['sha256']}`",
        "",
        "## Boundary",
        "",
        payload["boundary"],
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(markdown), encoding="utf-8")

    manifest_targets = [
        acquisition_path,
        relations_path,
        benchmark_path,
        exact_path,
        rounded_path,
        report_path,
        output_dir / "report.md",
    ]
    (output_dir / "manifest.sha256").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in manifest_targets),
        encoding="utf-8",
    )
    summary = {
        "status": payload["status"],
        "score_before": payload["score"]["before"],
        "score_after": payload["score"]["after"],
        "eligible_companies": payload["cohort"]["eligible_companies"],
        "companies_with_two_relations": payload["cohort"]["companies_with_two_relations"],
        "sic_codes": payload["cohort"]["sic_codes"],
        "direct_relations": payload["cohort"]["direct_relations"],
        "exact_recall": exact["recall"],
        "exact_fpr": exact["false_positive_rate"],
        "rounded_recall": rounded["recall"],
        "rounded_fpr": rounded["false_positive_rate"],
        "failed_gates": failed,
        "report_sha256": report["sha256"],
    }
    print(json.dumps(summary, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output_dir is None:
        parser.error("--output-dir is required unless --self-test is used")
    if args.cache_dir is None:
        with tempfile.TemporaryDirectory(prefix="fin-abs-001b-sec-") as temp:
            execute(Path(temp), args.output_dir)
    else:
        execute(args.cache_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
