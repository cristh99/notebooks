from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from .constants import (
    ABSOLUTE_SCORE_BEFORE,
    ABSOLUTE_SCORE_PASS_DELTA,
    POLICY_ID,
    SCHEMA,
    UNIVERSE,
)
from .metrics import metrics, permutation_control
from .policy import predict
from .utils import canonical, digest


def direct_provenance(
    case: Mapping[str, Any],
) -> bool:
    values = case.get("values", {})
    provenance = case.get("provenance", {})
    if set(values) != set(provenance):
        return False
    for key, source in provenance.items():
        if not isinstance(source, Mapping):
            return False
        if source.get("accn") != case.get("accession"):
            return False
        if source.get("form") not in {"10-K", "10-K/A"}:
            return False
        if (
            not source.get("concept")
            or not source.get("filed")
            or not source.get("end")
        ):
            return False
        if float(source.get("value")) != float(values[key]):
            return False
    return True


def build_report(
    cases: Sequence[Mapping[str, Any]],
    fetch_log: Sequence[Mapping[str, Any]],
    exact_rows: Sequence[Mapping[str, Any]],
    rounded_rows: Sequence[Mapping[str, Any]],
    *,
    cases_file_sha256: str,
) -> dict[str, Any]:
    exact = metrics(exact_rows)
    rounded = metrics(rounded_rows)
    permutation = permutation_control(exact_rows)
    relation_counts = [
        predict(case)["relation_count"]
        for case in cases
    ]
    sics = {
        str(case.get("sic", ""))
        for case in cases
        if case.get("sic")
    }
    checks = {
        "frozen_universe_50": (
            len(UNIVERSE) == 50
            and len(
                {item["cik"] for item in UNIVERSE}
            )
            == 50
        ),
        "official_sec_only": all(
            str(case.get("source_url", "")).startswith(
                "https://data.sec.gov/"
            )
            for case in cases
        ),
        "all_values_directly_reported": all(
            direct_provenance(case)
            for case in cases
        ),
        "same_accession_per_case": all(
            all(
                source.get("accn")
                == case.get("accession")
                for source
                in case.get(
                    "provenance",
                    {},
                ).values()
            )
            for case in cases
        ),
        "eligible_companies_at_least_40": (
            len(cases) >= 40
        ),
        "companies_with_two_relations_at_least_25": (
            sum(
                count >= 2
                for count in relation_counts
            )
            >= 25
        ),
        "total_relations_at_least_80": (
            sum(relation_counts) >= 80
        ),
        "sic_breadth_at_least_20": (
            len(sics) >= 20
        ),
        "exact_zero_fpr": (
            exact.get("false_positive_rate")
            == 0.0
        ),
        "exact_precision_one": (
            exact.get("precision") == 1.0
        ),
        "exact_recall_at_least_90pct": (
            exact.get("recall") or 0.0
        )
        >= 0.90,
        "exact_full_coverage": (
            exact.get("coverage") == 1.0
        ),
        "rounded_zero_fpr": (
            rounded.get("false_positive_rate")
            == 0.0
        ),
        "rounded_recall_at_least_85pct": (
            rounded.get("recall") or 0.0
        )
        >= 0.85,
        "permutation_worse": (
            (
                permutation["metrics"].get(
                    "false_positive_rate"
                )
                or 0.0
            )
            > (
                exact.get(
                    "false_positive_rate"
                )
                or 0.0
            )
            or (
                permutation["metrics"].get(
                    "recall"
                )
                or 0.0
            )
            < (exact.get("recall") or 0.0)
        ),
    }
    passed = all(checks.values())
    score_after = (
        ABSOLUTE_SCORE_BEFORE
        + ABSOLUTE_SCORE_PASS_DELTA
        if passed
        else ABSOLUTE_SCORE_BEFORE
    )
    payload = {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "status": (
            "PASS_SEC_DIRECT_BREADTH"
            if passed
            else "OPEN_SEC_DIRECT_BREADTH"
        ),
        "protocol": {
            "universe_size": len(UNIVERSE),
            "universe_sha256": digest(UNIVERSE),
            "score_delta_if_all_gates_pass": (
                ABSOLUTE_SCORE_PASS_DELTA
            ),
            "score_promotion_dimensions": {
                "generality": 4,
                "external_validation": 4,
                "sota_world": 0,
                "originality": 0,
            },
        },
        "fetch": {
            "success": sum(
                item.get("status")
                in {"FETCHED", "CACHE"}
                for item in fetch_log
            ),
            "failed": sum(
                item.get("status") == "FAILED"
                for item in fetch_log
            ),
            "log": list(fetch_log),
        },
        "cohort": {
            "eligible_companies": len(cases),
            "companies_with_two_relations": sum(
                count >= 2
                for count in relation_counts
            ),
            "total_relations": sum(relation_counts),
            "relation_count_distribution": dict(
                Counter(relation_counts)
            ),
            "sic_count": len(sics),
            "tickers": [
                case["ticker"] for case in cases
            ],
            "cases_file_sha256": (
                cases_file_sha256
            ),
        },
        "exact_metrics": exact,
        "rounded_metrics": rounded,
        "permutation_control": permutation,
        "gate_checks": checks,
        "absolute_score": {
            "before": ABSOLUTE_SCORE_BEFORE,
            "after": score_after,
            "delta": (
                score_after
                - ABSOLUTE_SCORE_BEFORE
            ),
            "boundary": (
                "A pass can add only eight absolute "
                "points for cross-company generality "
                "and external validation. It adds no "
                "world-SOTA or historical-originality "
                "points and does not establish Finance "
                "1000."
            ),
        },
        "boundary": (
            "The experiment verifies direct numerical "
            "consistency of selected SEC facts. It "
            "does not value companies, forecast "
            "returns, certify audits, judge fraud, "
            "or establish universal Finance SOTA."
        ),
    }
    payload_canonical = canonical(payload)
    return {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": digest(payload),
    }
