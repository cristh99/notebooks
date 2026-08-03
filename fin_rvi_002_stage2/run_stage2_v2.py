from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .build_frozen_corpus_v2 import build_corpus
from .evidence_ladder import amount_decimal, evidence_ladder, policy_view

SCHEMA = "fin-rvi-002/stage2-evidence-ladder/2"
CORPUS_SCHEMA = "fin-rvi-002/frozen-adjudication-corpus/2"
NEGATIVE_CONTROL_SEED = "FIN-RVI-002-STAGE2-EVIDENCE-LADDER-NEGATIVE-V2"
POLICIES = (
    "B0_CODE",
    "B1_CODE_SUPPLIER",
    "B2_CODE_SUPPLIER_AMOUNT",
    "B3_DOCUMENTARY",
    "EVIDENCE_LADDER",
)
EVIDENCE_FIELDS = {
    "B0_CODE": 1,
    "B1_CODE_SUPPLIER": 2,
    "B2_CODE_SUPPLIER_AMOUNT": 3,
    "B3_DOCUMENTARY": 4,
    "EVIDENCE_LADDER": 7,
}
ROTATED_FIELDS = (
    "sefin_object_text",
    "sefin_supplier_names",
    "sefin_supplier_ids",
    "sefin_dates",
    "supplier_supported",
    "documentary_decision",
    "relative_amount_difference",
    "amount_sefin",
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def policy_promotes(row: Mapping[str, Any], policy: str) -> bool:
    visible = policy_view(row)
    if policy == "B0_CODE":
        return True
    if policy == "B1_CODE_SUPPLIER":
        return bool(visible["supplier_supported"])
    if policy == "B2_CODE_SUPPLIER_AMOUNT":
        difference = visible["relative_amount_difference"]
        return bool(visible["supplier_supported"]) and difference is not None and Decimal(
            str(difference)
        ) <= Decimal("0.05")
    if policy == "B3_DOCUMENTARY":
        return visible["documentary_decision"] == "SUPPORTED"
    if policy == "EVIDENCE_LADDER":
        return bool(evidence_ladder(visible)["promote"])
    raise KeyError(policy)


def metric_template(policy: str) -> dict[str, Any]:
    return {
        "policy": policy,
        "evidence_fields": EVIDENCE_FIELDS[policy],
        "rows": 0,
        "positive_expected": 0,
        "nonpositive_expected": 0,
        "promotions": 0,
        "supported_recovered": 0,
        "missed_supported": 0,
        "unsafe_overpromotions": 0,
        "correct_nonpromotions": 0,
        "binary_correct": 0,
        "supported_amount_hnl": "0.00",
        "unsafe_amount_hnl": "0.00",
    }


def evaluate_policies(
    rows: list[dict[str, Any]], split: str | None = None
) -> dict[str, dict[str, Any]]:
    selected = [row for row in rows if split is None or row["split"] == split]
    metrics = {policy: metric_template(policy) for policy in POLICIES}
    supported_amounts = {policy: Decimal("0") for policy in POLICIES}
    unsafe_amounts = {policy: Decimal("0") for policy in POLICIES}
    for row in selected:
        expected_positive = row["gold_expected"] == "SUPPORTED"
        for policy in POLICIES:
            metric = metrics[policy]
            promote = policy_promotes(row, policy)
            metric["rows"] += 1
            metric["positive_expected"] += int(expected_positive)
            metric["nonpositive_expected"] += int(not expected_positive)
            metric["promotions"] += int(promote)
            if expected_positive and promote:
                metric["supported_recovered"] += 1
                metric["binary_correct"] += 1
                supported_amounts[policy] += amount_decimal(row)
            elif expected_positive:
                metric["missed_supported"] += 1
            elif promote:
                metric["unsafe_overpromotions"] += 1
                unsafe_amounts[policy] += amount_decimal(row)
            else:
                metric["correct_nonpromotions"] += 1
                metric["binary_correct"] += 1
    for policy in POLICIES:
        metrics[policy]["supported_amount_hnl"] = format(
            supported_amounts[policy].quantize(Decimal("0.01")), "f"
        )
        metrics[policy]["unsafe_amount_hnl"] = format(
            unsafe_amounts[policy].quantize(Decimal("0.01")), "f"
        )
        metrics[policy]["field_observations"] = (
            metrics[policy]["rows"] * metrics[policy]["evidence_fields"]
        )
        metrics[policy]["ordering_key"] = [
            metrics[policy]["unsafe_overpromotions"],
            metrics[policy]["unsafe_amount_hnl"],
            -metrics[policy]["supported_recovered"],
            metrics[policy]["missed_supported"],
            metrics[policy]["field_observations"],
            policy,
        ]
    return metrics


def rotate_sefin_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: hashlib.sha256(
            f"{row['candidate_id']}|{NEGATIVE_CONTROL_SEED}".encode("utf-8")
        ).hexdigest(),
    )
    evidence = [{field: row[field] for field in ROTATED_FIELDS} for row in ordered]
    if evidence:
        evidence = evidence[1:] + evidence[:1]
    by_candidate = {
        row["candidate_id"]: values
        for row, values in zip(ordered, evidence, strict=True)
    }
    output = copy.deepcopy(rows)
    for row in output:
        row.update(by_candidate[row["candidate_id"]])
    return output


def ladder_details(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": row["candidate_id"],
            "split": row["split"],
            "decision": evidence_ladder(row),
        }
        for row in sorted(rows, key=lambda item: item["candidate_id"])
    ]


def shadow_metrics(
    source_report: dict[str, Any], holdout_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    source = source_report.get("payload", source_report)
    source_metrics = source.get("holdout_metrics", {})
    blocker_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    supplier_supported = 0
    documentary_supported = 0
    for row in holdout_rows:
        adjudication = row.get("object_adjudication") or {}
        supplier_supported += int(bool(adjudication.get("supplier_identity_supported")))
        documentary_supported += int(adjudication.get("decision") == "SUPPORTED")
        text = str(row.get("sefin_object_text") or "").upper()
        if "REVERSION" in text or "REVERSIÓN" in text:
            event_counts["REVERSAL_PRESENT"] += 1
        elif "PAGO" in text or "FACTURA" in text or "ESTIMACION" in text:
            event_counts["PAYMENT_LANGUAGE"] += 1
        else:
            event_counts["OTHER"] += 1
        if not adjudication.get("supplier_identity_supported"):
            blocker_counts["PAYEE_IDENTITY_MISSING"] += 1
        if adjudication.get("decision") != "SUPPORTED":
            blocker_counts["OBJECT_SUPPORT_MISSING"] += 1
        if not row.get("absolute_days") and row.get("absolute_days") != 0:
            blocker_counts["CHRONOLOGY_MISSING"] += 1
        if row.get("cardinality_type") in {"MANY_TO_MANY", "MANY_ONCAE_TO_ONE_SEFIN"}:
            blocker_counts["CARDINALITY_REVIEW"] += 1
    return {
        "holdout_rows": len(holdout_rows),
        "supplier_supported": supplier_supported,
        "documentary_supported": documentary_supported,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "event_language_counts": dict(sorted(event_counts.items())),
        "observed_document_acquisition": {
            "attempts": source_metrics.get("document_acquisition_attempts"),
            "successes": source_metrics.get("document_acquisition_successes"),
            "bytes": source_metrics.get("document_acquisition_bytes"),
            "seconds": str(source_metrics.get("document_acquisition_seconds")),
        },
        "boundary": (
            "shadow rows lack independent labels and typed contract-date/payee-authority evidence; no correctness promotion is inferred from shadow coverage"
        ),
    }


def build_report(
    corpus: dict[str, Any],
    source_report: dict[str, Any],
    holdout_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if corpus.get("schema") != CORPUS_SCHEMA:
        raise ValueError("unexpected frozen corpus schema")
    rows = corpus["rows"]
    all_metrics = evaluate_policies(rows)
    development = evaluate_policies(rows, "DEVELOPMENT")
    sealed = evaluate_policies(rows, "SEALED_TEST")
    rotated = evaluate_policies(rotate_sefin_evidence(rows), "SEALED_TEST")
    ladder = sealed["EVIDENCE_LADDER"]
    strong = sealed["B1_CODE_SUPPLIER"]
    negative = rotated["EVIDENCE_LADDER"]
    development_ladder = development["EVIDENCE_LADDER"]
    unsafe_amount_avoided = Decimal(str(strong["unsafe_amount_hnl"])) - Decimal(
        str(ladder["unsafe_amount_hnl"])
    )
    baseline_names = (
        "B0_CODE",
        "B1_CODE_SUPPLIER",
        "B2_CODE_SUPPLIER_AMOUNT",
        "B3_DOCUMENTARY",
    )
    full_ladder = all_metrics["EVIDENCE_LADDER"]
    dominates_every_baseline = all(
        full_ladder["unsafe_overpromotions"] <= all_metrics[name]["unsafe_overpromotions"]
        and full_ladder["supported_recovered"] >= all_metrics[name]["supported_recovered"]
        and (
            full_ladder["unsafe_overpromotions"] < all_metrics[name]["unsafe_overpromotions"]
            or full_ladder["supported_recovered"] > all_metrics[name]["supported_recovered"]
            or full_ladder["missed_supported"] < all_metrics[name]["missed_supported"]
        )
        for name in baseline_names
    )
    gate_checks = {
        "development_has_both_classes": (
            development_ladder["positive_expected"] >= 1
            and development_ladder["nonpositive_expected"] >= 1
        ),
        "development_zero_unsafe": development_ladder["unsafe_overpromotions"] == 0,
        "development_recovers_all_supported": (
            development_ladder["supported_recovered"]
            == development_ladder["positive_expected"]
        ),
        "sealed_has_both_classes": (
            ladder["positive_expected"] >= 1 and ladder["nonpositive_expected"] >= 1
        ),
        "sealed_zero_unsafe": ladder["unsafe_overpromotions"] == 0,
        "sealed_recovers_all_supported": (
            ladder["supported_recovered"] == ladder["positive_expected"]
        ),
        "strictly_reduces_unsafe_vs_code_supplier": (
            ladder["unsafe_overpromotions"] < strong["unsafe_overpromotions"]
        ),
        "improves_binary_accuracy_vs_code_supplier": (
            ladder["binary_correct"] > strong["binary_correct"]
        ),
        "negative_control_is_worse": (
            negative["unsafe_overpromotions"] > ladder["unsafe_overpromotions"]
            or negative["binary_correct"] < ladder["binary_correct"]
        ),
        "dominates_every_declared_baseline_on_full_corpus": dominates_every_baseline,
        "frozen_source_hash_matches": corpus["source_hash_match"],
        "source_stage1_documents_acquired": (
            source_report.get("payload", source_report)
            .get("holdout_metrics", {})
            .get("document_acquisition_successes")
            == source_report.get("payload", source_report)
            .get("holdout_metrics", {})
            .get("holdout_size")
        ),
    }
    candidate_pass = all(gate_checks.values())
    selected = min(POLICIES, key=lambda policy: tuple(all_metrics[policy]["ordering_key"]))
    payload = {
        "schema": SCHEMA,
        "problem_solver_route": {
            "classes": [
                "ACTIVE_INFORMATION",
                "DECISION",
                "PLANNING",
                "VERIFICATION",
            ],
            "selected_method": "robust_minimax_regret",
            "selected_action": "stage2_evidence_ladder_then_clean_replay",
            "canonical_score_before": 820,
        },
        "frozen_corpus_sha256": sha256_payload(corpus),
        "frozen_corpus_file_sha256": hashlib.sha256(
            canonical_json(corpus).encode("utf-8")
        ).hexdigest(),
        "corpus_source_hashes": corpus["source_hashes"],
        "corpus_source_hash_match": corpus["source_hash_match"],
        "corpus_derivation": corpus["derivation"],
        "policy_metrics_all": all_metrics,
        "policy_metrics_development": development,
        "policy_metrics_sealed_test": sealed,
        "negative_control_sealed_test": negative,
        "selected_policy": selected,
        "evidence_ladder_details": ladder_details(rows),
        "utility_readout": {
            "sealed_unsafe_rows_avoided_vs_code_supplier": (
                strong["unsafe_overpromotions"] - ladder["unsafe_overpromotions"]
            ),
            "sealed_unsafe_amount_hnl_avoided_vs_code_supplier": format(
                unsafe_amount_avoided.quantize(Decimal("0.01")), "f"
            ),
            "sealed_supported_recovered": ladder["supported_recovered"],
            "sealed_supported_expected": ladder["positive_expected"],
            "additional_field_observations_vs_code_supplier": (
                ladder["field_observations"] - strong["field_observations"]
            ),
        },
        "prospective_shadow": shadow_metrics(source_report, holdout_rows),
        "gate_checks": gate_checks,
        "gate_readout": {
            "G07": (
                "PASS_CANDIDATE_PENDING_PUBLIC_CLEAN_REPLAY"
                if candidate_pass
                else "OPEN"
            ),
            "G09": "OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED",
            "score_if_public_replay_passes": 920 if candidate_pass else 820,
            "canonical_score_now": 820,
        },
        "boundary": (
            "The adversarial corpus tests maximum permissible contractor-payment promotion. It does not prove legality, receipt, quality, liquidation, fraud, or physical result; the random shadow cohort is operational evidence without independent labels."
        ),
    }
    return {"payload": payload, "sha256": sha256_payload(payload)}


def markdown(report: dict[str, Any]) -> str:
    payload = report["payload"]
    sealed = payload["policy_metrics_sealed_test"]
    lines = [
        "# FIN-RVI-002 Stage 2 v2 — evidence ladder",
        "",
        f"- Selected policy: `{payload['selected_policy']}`",
        f"- G07: `{payload['gate_readout']['G07']}`",
        f"- Canonical score now: `{payload['gate_readout']['canonical_score_now']}/1000`",
        f"- Score if public clean replay passes: `{payload['gate_readout']['score_if_public_replay_passes']}/1000`",
        f"- Report SHA-256: `{report['sha256']}`",
        "",
        "## Sealed test",
        "",
        "| Policy | Promotions | Unsafe | Unsafe HNL | Supported recovered | Correct |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for policy in POLICIES:
        metric = sealed[policy]
        lines.append(
            f"| {policy} | {metric['promotions']} | {metric['unsafe_overpromotions']} | "
            f"{metric['unsafe_amount_hnl']} | {metric['supported_recovered']} | {metric['binary_correct']} |"
        )
    lines.extend(
        [
            "",
            "## Utility",
            "",
            f"- Unsafe rows avoided vs code+supplier: **{payload['utility_readout']['sealed_unsafe_rows_avoided_vs_code_supplier']}**",
            f"- Unsafe amount avoided: **HNL {payload['utility_readout']['sealed_unsafe_amount_hnl_avoided_vs_code_supplier']}**",
            f"- Supported recovered: **{payload['utility_readout']['sealed_supported_recovered']}/{payload['utility_readout']['sealed_supported_expected']}**",
            "",
            "## Gates",
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
    package = Path("fin_rvi_002_stage2")
    source = Path("reports/fin_rvi_002_stage1")
    output = Path("reports/fin_rvi_002_stage2_v2")
    output.mkdir(parents=True, exist_ok=True)
    corpus = build_corpus(
        package / "frozen_pair_manifest_v2.json",
        source / "known_target_hits.json",
    )
    (output / "frozen_adjudication_corpus_v2.json").write_text(
        json.dumps(corpus, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    source_report = read_json(source / "report.json")
    holdout_rows = read_jsonl(source / "holdout_decisions.jsonl")
    report = build_report(corpus, source_report, holdout_rows)
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
    (output / "report.sha256").write_text(
        f"{hashlib.sha256(report_path.read_bytes()).hexdigest()}  report.json\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "g07": report["payload"]["gate_readout"]["G07"],
                "selected_policy": report["payload"]["selected_policy"],
                "report_sha256": report["sha256"],
                "score_now": report["payload"]["gate_readout"]["canonical_score_now"],
                "score_after_public_replay": report["payload"]["gate_readout"][
                    "score_if_public_replay_passes"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
