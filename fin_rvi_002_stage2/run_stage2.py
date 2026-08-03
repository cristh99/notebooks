from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from fin_rvi_002_stage1.known_gold import matching_rules

SCHEMA = "fin-rvi-002/stage2-strong-baselines/1"
SEED = "FIN-RVI-002-STAGE2-NEGATIVE-CONTROL-V1"
POLICIES = (
    "B0_CODE",
    "B1_CODE_SUPPLIER",
    "B2_CODE_SUPPLIER_AMOUNT",
    "POLICY_DOCUMENTARY",
)
EVIDENCE_FIELDS = {
    "B0_CODE": 1,
    "B1_CODE_SUPPLIER": 2,
    "B2_CODE_SUPPLIER_AMOUNT": 3,
    "POLICY_DOCUMENTARY": 4,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def documentary_decision(row: dict[str, Any]) -> str:
    compact = row.get("documentary_decision")
    if compact in {"SUPPORTED", "REJECTED", "UNRESOLVED"}:
        return str(compact)
    nested = row.get("object_adjudication")
    if not isinstance(nested, dict):
        return "UNRESOLVED"
    value = nested.get("decision")
    return value if value in {"SUPPORTED", "REJECTED", "UNRESOLVED"} else "UNRESOLVED"


def supplier_supported(row: dict[str, Any]) -> bool:
    if "supplier_supported" in row:
        return bool(row.get("supplier_supported"))
    nested = row.get("object_adjudication")
    return bool(isinstance(nested, dict) and nested.get("supplier_identity_supported"))


def policy_promotes(row: dict[str, Any], policy: str) -> bool:
    if policy == "B0_CODE":
        return True
    supplier = supplier_supported(row)
    if policy == "B1_CODE_SUPPLIER":
        return supplier
    if policy == "B2_CODE_SUPPLIER_AMOUNT":
        return supplier and float(row.get("relative_amount_difference", 1.0)) <= 0.05
    if policy == "POLICY_DOCUMENTARY":
        return documentary_decision(row) == "SUPPORTED"
    raise KeyError(policy)


def compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("candidate_id", ""))):
        rules = matching_rules(row)
        output.append(
            {
                "candidate_id": row.get("candidate_id"),
                "shared_code": row.get("shared_code"),
                "amount_sefin": round(float(row.get("amount_sefin", 0.0)), 2),
                "relative_amount_difference": round(
                    float(row.get("relative_amount_difference", 1.0)), 8
                ),
                "supplier_supported": supplier_supported(row),
                "documentary_decision": documentary_decision(row),
                "gold": [
                    {
                        "rule_id": rule.rule_id,
                        "expected": rule.expected,
                        "source_url": rule.source_url,
                    }
                    for rule in rules
                ],
            }
        )
    return output


def _metric_template(policy: str) -> dict[str, Any]:
    return {
        "policy": policy,
        "evidence_fields": EVIDENCE_FIELDS[policy],
        "holdout_promotions": 0,
        "evaluated_rule_hits": 0,
        "matched_candidates": 0,
        "positive_expected": 0,
        "nonpositive_expected": 0,
        "supported_recovered": 0,
        "unsafe_overpromotions": 0,
        "correct_nonpromotions": 0,
        "missed_supported": 0,
        "binary_correct": 0,
    }


def evaluate_policies(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metrics = {policy: _metric_template(policy) for policy in POLICIES}
    for policy in POLICIES:
        matched: set[str] = set()
        for row in rows:
            promote = policy_promotes(row, policy)
            metrics[policy]["holdout_promotions"] += int(promote)
            if row["gold"]:
                matched.add(str(row["candidate_id"]))
            for gold in row["gold"]:
                expected_positive = gold["expected"] == "SUPPORTED"
                metrics[policy]["evaluated_rule_hits"] += 1
                if expected_positive:
                    metrics[policy]["positive_expected"] += 1
                    if promote:
                        metrics[policy]["supported_recovered"] += 1
                        metrics[policy]["binary_correct"] += 1
                    else:
                        metrics[policy]["missed_supported"] += 1
                else:
                    metrics[policy]["nonpositive_expected"] += 1
                    if promote:
                        metrics[policy]["unsafe_overpromotions"] += 1
                    else:
                        metrics[policy]["correct_nonpromotions"] += 1
                        metrics[policy]["binary_correct"] += 1
        metrics[policy]["matched_candidates"] = len(matched)
        metrics[policy]["ordering_key"] = [
            metrics[policy]["unsafe_overpromotions"],
            -metrics[policy]["supported_recovered"],
            metrics[policy]["missed_supported"],
            metrics[policy]["evidence_fields"],
            policy,
        ]
    return metrics


def rotate_documentary_decisions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: hashlib.sha256(
            f"{row['candidate_id']}|{SEED}".encode("utf-8")
        ).hexdigest(),
    )
    decisions = [row["documentary_decision"] for row in ordered]
    if decisions:
        decisions = decisions[1:] + decisions[:1]
    rotated_by_id = {
        str(row["candidate_id"]): decision
        for row, decision in zip(ordered, decisions, strict=True)
    }
    output = json.loads(json.dumps(rows))
    for row in output:
        row["documentary_decision"] = rotated_by_id[str(row["candidate_id"])]
    return output


def evaluate_rotated(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rotated = rotate_documentary_decisions(rows)
    metric = _metric_template("POLICY_DOCUMENTARY")
    matched: set[str] = set()
    for row in rotated:
        promote = row["documentary_decision"] == "SUPPORTED"
        metric["holdout_promotions"] += int(promote)
        if row["gold"]:
            matched.add(str(row["candidate_id"]))
        for gold in row["gold"]:
            expected_positive = gold["expected"] == "SUPPORTED"
            metric["evaluated_rule_hits"] += 1
            if expected_positive:
                metric["positive_expected"] += 1
                if promote:
                    metric["supported_recovered"] += 1
                    metric["binary_correct"] += 1
                else:
                    metric["missed_supported"] += 1
            else:
                metric["nonpositive_expected"] += 1
                if promote:
                    metric["unsafe_overpromotions"] += 1
                else:
                    metric["correct_nonpromotions"] += 1
                    metric["binary_correct"] += 1
    metric["matched_candidates"] = len(matched)
    metric["seed"] = SEED
    return metric


def build_report(rows: list[dict[str, Any]], source_report: dict[str, Any]) -> dict[str, Any]:
    compact = compact_rows(rows)
    metrics = evaluate_policies(compact)
    rotated = evaluate_rotated(compact)
    b1 = metrics["B1_CODE_SUPPLIER"]
    documentary = metrics["POLICY_DOCUMENTARY"]
    positive = documentary["positive_expected"]
    nonpositive = documentary["nonpositive_expected"]
    negative_control_worse = (
        rotated["unsafe_overpromotions"] > documentary["unsafe_overpromotions"]
        or rotated["binary_correct"] < documentary["binary_correct"]
    )
    gate_checks = {
        "has_positive_gold": positive >= 1,
        "has_nonpositive_gold": nonpositive >= 1,
        "documentary_zero_unsafe": documentary["unsafe_overpromotions"] == 0,
        "strictly_reduces_unsafe_vs_b1": (
            documentary["unsafe_overpromotions"] < b1["unsafe_overpromotions"]
        ),
        "recovers_no_fewer_supported_vs_b1": (
            documentary["supported_recovered"] >= b1["supported_recovered"]
        ),
        "negative_control_worse": negative_control_worse,
    }
    g07 = "PASS_CANDIDATE_PENDING_CLEAN_REPLAY" if all(gate_checks.values()) else "OPEN"
    incremental_rows = [
        row
        for row in compact
        if row["supplier_supported"] and row["documentary_decision"] != "SUPPORTED"
    ]
    incremental_amount = round(sum(row["amount_sefin"] for row in incremental_rows), 2)
    winner = min(POLICIES, key=lambda policy: tuple(metrics[policy]["ordering_key"]))
    payload = {
        "schema": SCHEMA,
        "source_stage1_report_sha256": source_report.get("sha256"),
        "source_stage1_holdout_sha256": sha256_payload(compact),
        "input_rows": compact,
        "policy_metrics": metrics,
        "selected_policy": winner,
        "negative_control": rotated,
        "documentary_increment_over_b1": {
            "blocked_rows": len(incremental_rows),
            "blocked_candidate_ids": [row["candidate_id"] for row in incremental_rows],
            "amount_sefin": incremental_amount,
        },
        "gate_checks": gate_checks,
        "gate_readout": {
            "G07_STRONG_BASELINE": g07,
            "G09": "OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED",
        },
        "boundary": (
            "frozen adversarial gold tests maximum permissible promotion; it does not prove legality, receipt, quality or physical result"
        ),
    }
    return {"payload": payload, "sha256": sha256_payload(payload)}


def markdown(report: dict[str, Any]) -> str:
    payload = report["payload"]
    lines = [
        "# FIN-RVI-002 Stage 2 — strong-baseline result",
        "",
        f"- Selected policy: `{payload['selected_policy']}`",
        f"- G07 strong-baseline gate: `{payload['gate_readout']['G07_STRONG_BASELINE']}`",
        f"- Stage 1 report: `{payload['source_stage1_report_sha256']}`",
        f"- Stage 2 report: `{report['sha256']}`",
        "",
        "## Policies",
        "",
        "| Policy | Promotions | Gold hits | Unsafe | Supported recovered | Missed supported |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for policy in POLICIES:
        metric = payload["policy_metrics"][policy]
        lines.append(
            f"| {policy} | {metric['holdout_promotions']} | {metric['evaluated_rule_hits']} | "
            f"{metric['unsafe_overpromotions']} | {metric['supported_recovered']} | {metric['missed_supported']} |"
        )
    lines.extend(
        [
            "",
            "## Gate checks",
            "",
            *[
                f"- {name}: **{'PASS' if value else 'FAIL'}**"
                for name, value in payload["gate_checks"].items()
            ],
            "",
            "## Boundary",
            "",
            payload["boundary"],
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    source_dir = Path("reports/fin_rvi_002_stage1")
    output = Path("reports/fin_rvi_002_stage2")
    output.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(source_dir / "holdout_decisions.jsonl")
    source_report = json.loads((source_dir / "report.json").read_text(encoding="utf-8"))
    report = build_report(rows, source_report)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
    (output / "report.sha256").write_text(
        f"{hashlib.sha256((output / 'report.json').read_bytes()).hexdigest()}  report.json\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "g07": report["payload"]["gate_readout"]["G07_STRONG_BASELINE"],
        "selected_policy": report["payload"]["selected_policy"],
        "report_sha256": report["sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
