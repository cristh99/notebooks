from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .benchmark import (
    build_instances,
    evaluate_instances,
)
from .constants import UNIVERSE
from .policy import predict
from .report import build_report
from .sec_extract import extract_case
from .sec_fetch import fetch_bulk_companyfacts
from .utils import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
    )
    args = parser.parse_args()

    output = args.output_dir
    cache = args.cache_dir or output / "cache"
    output.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    extraction_log: list[dict[str, Any]] = []

    companyfacts_by_ticker, fetch_log = fetch_bulk_companyfacts(
        UNIVERSE,
        cache,
    )
    fetch_by_ticker = {
        str(record.get("ticker")): record
        for record in fetch_log
    }
    for company in UNIVERSE:
        companyfacts = companyfacts_by_ticker.get(
            company["ticker"]
        )
        fetch_record = fetch_by_ticker.get(
            company["ticker"],
            {},
        )
        if companyfacts is None:
            extraction_log.append(
                {
                    "ticker": company["ticker"],
                    "status": "FETCH_FAILED",
                    "error": fetch_record.get("error"),
                }
            )
        else:
            case = extract_case(
                companyfacts,
                company,
            )
            if case is None:
                extraction_log.append(
                    {
                        "ticker": company["ticker"],
                        "status": "NO_DIRECT_RELATION_CASE",
                    }
                )
            else:
                cases.append(case)
                extraction_log.append(
                    {
                        "ticker": company["ticker"],
                        "status": "ELIGIBLE",
                        "accession": case["accession"],
                        "report_end": case["report_end"],
                        "relations": predict(case)[
                            "relation_count"
                        ],
                    }
                )

    instances = build_instances(cases)
    exact_rows = evaluate_instances(
        instances,
        rounded=False,
    )
    rounded_rows = evaluate_instances(
        instances,
        rounded=True,
    )

    cases_path = output / "cases.json"
    cases_path.write_text(
        json.dumps(
            cases,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report = build_report(
        cases,
        fetch_log,
        exact_rows,
        rounded_rows,
        cases_file_sha256=sha256_file(
            cases_path
        ),
    )

    artifacts = {
        "instances.json": instances,
        "fetch_log.json": fetch_log,
        "extraction_log.json": extraction_log,
        "report.json": report,
    }
    for name, value in artifacts.items():
        (output / name).write_text(
            json.dumps(
                value,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    (output / "predictions_exact.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True)
            + "\n"
            for row in exact_rows
        ),
        encoding="utf-8",
    )
    (
        output
        / "predictions_rounded.jsonl"
    ).write_text(
        "".join(
            json.dumps(row, sort_keys=True)
            + "\n"
            for row in rounded_rows
        ),
        encoding="utf-8",
    )

    payload = report["payload"]
    exact = payload["exact_metrics"]
    rounded = payload["rounded_metrics"]

    def metric_text(value: object) -> str:
        return (
            "NULL"
            if value is None
            else f"{float(value):.4f}"
        )

    (output / "report.md").write_text(
        "\n".join(
            [
                (
                    "# FIN-ABS-001B — SEC "
                    "direct-fact breadth benchmark"
                ),
                "",
                (
                    f"- Status: "
                    f"**{payload['status']}**"
                ),
                (
                    f"- Eligible companies: "
                    f"**{payload['cohort']['eligible_companies']}**"
                ),
                (
                    f"- Total direct relations: "
                    f"**{payload['cohort']['total_relations']}**"
                ),
                (
                    f"- Exact recall / FPR: "
                    f"**{metric_text(exact['recall'])} / "
                    f"{metric_text(exact['false_positive_rate'])}**"
                ),
                (
                    f"- Rounded recall / FPR: "
                    f"**{metric_text(rounded['recall'])} / "
                    f"{metric_text(rounded['false_positive_rate'])}**"
                ),
                (
                    f"- Absolute score: "
                    f"**{payload['absolute_score']['before']} "
                    f"→ {payload['absolute_score']['after']}**"
                ),
                (
                    f"- Report SHA-256: "
                    f"`{report['sha256']}`"
                ),
                "",
                (
                    "No value is residualized or "
                    "synthesized; every evaluated "
                    "number carries a direct SEC "
                    "accession and concept."
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": payload["status"],
                "eligible_companies": payload[
                    "cohort"
                ]["eligible_companies"],
                "total_relations": payload[
                    "cohort"
                ]["total_relations"],
                "exact_recall": exact["recall"],
                "exact_fpr": exact[
                    "false_positive_rate"
                ],
                "rounded_recall": rounded[
                    "recall"
                ],
                "rounded_fpr": rounded[
                    "false_positive_rate"
                ],
                "score_before": payload[
                    "absolute_score"
                ]["before"],
                "score_after": payload[
                    "absolute_score"
                ]["after"],
                "report_sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
