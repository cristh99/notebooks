from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any, Iterable, Mapping

SCHEMA = "fin-abs-001b/sec-direct/1"
POLICY_ID = "FIN-ABS-001B-DIRECT-RELATION-VERIFIER-V1"
PERMUTATION_SEED = "FIN-ABS-001B-PERMUTATION-V1"
SCORE_BEFORE = 423
SCORE_PASS = 431
RELATIVE_TOLERANCE = 0.001
EXACT_ABSOLUTE_TOLERANCE = 1.0
ROUNDED_ABSOLUTE_TOLERANCE = 2.0


def normalize_json(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {str(key): normalize_json(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def canonical(value: Any) -> str:
    return json.dumps(
        normalize_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def tolerance(observed: float, expected: float, variant: str) -> float:
    absolute = ROUNDED_ABSOLUTE_TOLERANCE if variant == "rounded_millions" else EXACT_ABSOLUTE_TOLERANCE
    return max(absolute, RELATIVE_TOLERANCE * max(abs(observed), abs(expected), 1.0))


def variant_value(value: float, variant: str) -> float:
    if variant == "exact":
        return float(value)
    if variant == "rounded_millions":
        return float(round(float(value) / 1_000_000.0))
    raise ValueError(f"unsupported variant: {variant}")


def relation_check(relation: Mapping[str, Any], variant: str) -> dict[str, Any]:
    observed = variant_value(float(relation["observed"]["value"]), variant)
    terms = [
        {
            "coefficient": float(term["coefficient"]),
            "value": variant_value(float(term["value"]), variant),
            "concept": str(term["concept"]),
        }
        for term in relation["terms"]
    ]
    expected = sum(term["coefficient"] * term["value"] for term in terms)
    residual = observed - expected
    allowed = tolerance(observed, expected, variant)
    return {
        "observed": observed,
        "expected": expected,
        "residual": residual,
        "tolerance": allowed,
        "passed": abs(residual) <= allowed,
        "terms": terms,
    }


def predict_relation(relation: Mapping[str, Any], variant: str) -> dict[str, Any]:
    check = relation_check(relation, variant)
    return {
        "policy_id": POLICY_ID,
        "decision": "CLEAN" if check["passed"] else "ERROR",
        "relation_id": relation["relation_id"],
        "family": relation["family"],
        "variant": variant,
        "check": check,
        "boundary": (
            "Only a preregistered, directly reported SEC numerical relation is checked. "
            "No valuation, audit opinion, forecast, legality, fraud or universal Finance claim is implied."
        ),
    }


def _perturb_target(relation: dict[str, Any]) -> tuple[str, int | None]:
    candidates: list[tuple[float, str, int | None]] = []
    observed = float(relation["observed"]["value"])
    if observed != 0:
        candidates.append((abs(observed), "observed", None))
    for index, term in enumerate(relation["terms"]):
        value = float(term["value"])
        if value != 0:
            candidates.append((abs(value), "term", index))
    if not candidates:
        return "observed", None
    candidates.sort(key=lambda item: (-item[0], item[1], -1 if item[2] is None else item[2]))
    window = candidates[: min(3, len(candidates))]
    selector = int(digest(relation["relation_uid"] + "|target")[:8], 16) % len(window)
    _, kind, index = window[selector]
    return kind, index


def inject_error(relation: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(relation))
    kind, index = _perturb_target(result)
    seed = int(digest(result["relation_uid"] + "|magnitude")[:12], 16)
    magnitude = (2.0 + (seed % 31) / 10.0) / 100.0  # 2.0% to 5.0%
    direction = -1.0 if (seed // 31) % 2 else 1.0
    factor = 1.0 + direction * magnitude
    if kind == "observed":
        original = float(result["observed"]["value"])
        modified = original * factor if original != 0 else 1_000_000.0
        result["observed"]["value"] = modified
        path = "observed"
    else:
        assert index is not None
        original = float(result["terms"][index]["value"])
        modified = original * factor if original != 0 else 1_000_000.0
        result["terms"][index]["value"] = modified
        path = f"terms[{index}]"
    result["injection"] = {
        "path": path,
        "original": original,
        "modified": modified,
        "magnitude_fraction": direction * magnitude,
        "method": "deterministic multiplicative perturbation fixed before evaluation",
    }
    return result


def build_benchmark(relations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relation in sorted(relations, key=lambda item: str(item["relation_uid"])):
        clean = copy.deepcopy(dict(relation))
        rows.append(
            {
                "instance_id": f"{clean['relation_uid']}|clean",
                "gold_error": False,
                "relation": clean,
            }
        )
        rows.append(
            {
                "instance_id": f"{clean['relation_uid']}|error",
                "gold_error": True,
                "relation": inject_error(clean),
            }
        )
    return rows


def evaluate_rows(rows: Iterable[Mapping[str, Any]], variant: str) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    for row in rows:
        prediction = predict_relation(row["relation"], variant)
        predictions.append(
            {
                "instance_id": row["instance_id"],
                "company": row["relation"]["company"],
                "cik": row["relation"]["cik"],
                "sic": row["relation"].get("sic"),
                "family": row["relation"]["family"],
                "gold_error": bool(row["gold_error"]),
                "decision": prediction["decision"],
                "variant": variant,
                "prediction_sha256": digest(prediction),
            }
        )
    return predictions


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    clean = [row for row in values if not row["gold_error"]]
    errors = [row for row in values if row["gold_error"]]
    tp = sum(row["decision"] == "ERROR" for row in errors)
    fn = sum(row["decision"] != "ERROR" for row in errors)
    tn = sum(row["decision"] == "CLEAN" for row in clean)
    fp = sum(row["decision"] == "ERROR" for row in clean)
    abstentions = sum(row["decision"] == "ABSTAIN" for row in values)
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    specificity = _safe_div(tn, tn + fp)
    fpr = _safe_div(fp, fp + tn)
    accuracy = _safe_div(tp + tn, len(values))
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    family_totals: Counter[str] = Counter()
    family_hits: Counter[str] = Counter()
    for row in errors:
        family = str(row["family"])
        family_totals[family] += 1
        if row["decision"] == "ERROR":
            family_hits[family] += 1
    return {
        "rows": len(values),
        "clean_rows": len(clean),
        "error_rows": len(errors),
        "true_positive": tp,
        "false_negative": fn,
        "true_negative": tn,
        "false_positive": fp,
        "abstentions": abstentions,
        "coverage": _safe_div(len(values) - abstentions, len(values)),
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": fpr,
        "f1": f1,
        "family_recall": {
            family: _safe_div(family_hits[family], count)
            for family, count in sorted(family_totals.items())
        },
    }


def permutation_control(predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        (dict(row) for row in predictions),
        key=lambda row: digest(str(row["instance_id"]) + "|" + PERMUTATION_SEED),
    )
    decisions = [row["decision"] for row in ordered]
    if decisions:
        decisions = decisions[1:] + decisions[:1]
    permuted = [dict(row, decision=decision) for row, decision in zip(ordered, decisions, strict=True)]
    return {"seed": PERMUTATION_SEED, "metrics": metrics(permuted)}


def provenance_checks(relations: Iterable[Mapping[str, Any]]) -> dict[str, bool]:
    direct = True
    same_accession = True
    same_context = True
    no_adapter = True
    for relation in relations:
        facts = [relation["observed"], *relation["terms"]]
        accessions = {str(fact["provenance"].get("accession", "")) for fact in facts}
        contexts = {canonical(fact["provenance"].get("context")) for fact in facts}
        same_accession &= len(accessions) == 1 and "" not in accessions
        same_context &= len(contexts) == 1
        no_adapter &= relation.get("adapter") is None
        for fact in facts:
            provenance = fact.get("provenance", {})
            direct &= (
                str(provenance.get("source", "")).startswith("https://data.sec.gov/api/xbrl/companyfacts/")
                and bool(provenance.get("concept"))
                and provenance.get("form") in {"10-K", "10-K/A"}
                and bool(provenance.get("filed"))
                and bool(provenance.get("accession"))
            )
    return {
        "all_values_direct_sec_facts": direct,
        "same_accession_within_relation": same_accession,
        "same_context_within_relation": same_context,
        "no_adapter_or_residual_values": no_adapter,
    }


def build_report(
    *,
    relations: list[dict[str, Any]],
    benchmark: list[dict[str, Any]],
    exact_predictions: list[dict[str, Any]],
    rounded_predictions: list[dict[str, Any]],
    acquisition: Mapping[str, Any],
) -> dict[str, Any]:
    exact = metrics(exact_predictions)
    rounded = metrics(rounded_predictions)
    permutation = permutation_control(exact_predictions)
    companies = sorted({str(relation["cik"]) for relation in relations})
    company_relation_counts = Counter(str(relation["cik"]) for relation in relations)
    sic_codes = sorted({str(relation.get("sic")) for relation in relations if relation.get("sic")})
    families = Counter(str(relation["family"]) for relation in relations)
    provenance = provenance_checks(relations)
    checks: dict[str, bool] = {
        "official_sec_endpoint_only": bool(acquisition.get("official_sec_endpoint_only")),
        "frozen_company_universe": bool(acquisition.get("frozen_company_universe")),
        "at_least_40_companies": len(companies) >= 40,
        "at_least_25_companies_with_two_relations": sum(count >= 2 for count in company_relation_counts.values()) >= 25,
        "at_least_80_direct_relations": len(relations) >= 80,
        "at_least_20_sic_codes": len(sic_codes) >= 20,
        **provenance,
        "exact_zero_false_positives": exact.get("false_positive_rate") == 0.0,
        "exact_precision_one": exact.get("precision") == 1.0,
        "exact_recall_at_least_90pct": (exact.get("recall") or 0.0) >= 0.90,
        "exact_full_coverage": exact.get("coverage") == 1.0,
        "rounded_zero_false_positives": rounded.get("false_positive_rate") == 0.0,
        "rounded_recall_at_least_85pct": (rounded.get("recall") or 0.0) >= 0.85,
        "permutation_is_worse": (
            (permutation["metrics"].get("false_positive_rate") or 0.0) > (exact.get("false_positive_rate") or 0.0)
            or (permutation["metrics"].get("recall") or 0.0) < (exact.get("recall") or 0.0)
        ),
    }
    complete_pass = all(checks.values())
    score_after = SCORE_PASS if complete_pass else SCORE_BEFORE
    payload = {
        "schema": SCHEMA,
        "status": "PASS_BOUNDED_EXTERNAL_BREADTH" if complete_pass else "OPEN_EXTERNAL_BREADTH_OR_PERFORMANCE_GATE",
        "policy_id": POLICY_ID,
        "acquisition": dict(acquisition),
        "cohort": {
            "eligible_companies": len(companies),
            "companies_with_two_relations": sum(count >= 2 for count in company_relation_counts.values()),
            "sic_codes": len(sic_codes),
            "direct_relations": len(relations),
            "benchmark_rows": len(benchmark),
            "family_counts": dict(sorted(families.items())),
        },
        "exact_metrics": exact,
        "rounded_metrics": rounded,
        "permutation_control": permutation,
        "gate_checks": checks,
        "score": {
            "before": SCORE_BEFORE,
            "after": score_after,
            "delta": score_after - SCORE_BEFORE,
            "maximum_authorized_delta": 8,
            "credited_dimensions": (
                {"generality": 4, "external_validation": 4}
                if complete_pass
                else {}
            ),
            "forbidden_credit": ["world_sota", "historical_originality", "universal_finance"],
        },
        "maximum_claim": (
            "A frozen direct-SEC numerical-consistency verifier transferred across a preregistered broad public-company cohort."
            if complete_pass
            else "The direct-SEC breadth experiment remains unresolved or failed at least one preregistered gate."
        ),
        "boundary": (
            "This is one accounting-consistency benchmark. It does not establish audited correctness, valuation quality, forecasting power, "
            "investment performance, fraud detection, legal compliance, historical originality, or general Finance SOTA."
        ),
        "next_action": (
            "Proceed to the next frozen external domain only after preserving this exact cohort, code, predictions and hashes."
            if complete_pass
            else "Use only the failed preregistered gates to determine the next experiment; do not tune on hidden outcomes."
        ),
    }
    return {"payload": payload, "sha256": digest(payload)}
