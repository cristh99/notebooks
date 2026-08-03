from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from fin_abs_001c_filedfact.run import (
    SOURCE_REPO,
    SOURCE_SELECTION_MANIFEST_SHA256,
    SOURCE_VERSION,
    Relation,
    canonical,
    digest,
    direct_provenance,
    metrics,
    mine_relations,
    permutation_control,
    round_half_away,
    safe_div,
    sha256_file,
    tolerance as exact_tolerance,
)

PINNED_SOURCE_REVISION = "8f7cb7e70be8b4dc6702c24927b355c1a287e4c0"
PINNED_PARQUET_SHA256 = "c04bb39a676be9fbc5dd8a0addf99c2a92d9fcb2281657ba4c2bc5d6bf0b7a77"
PINNED_BASE_RELATION_COUNT = 526
PINNED_BASE_RELATION_ID_SHA256 = "e9c67085421a89f37fe67e292af1d6ab49c846028d60bef6fe7878dbd36e4457"
PINNED_BASE_RELATION_SIGNATURE_SHA256 = "c9596b45f0f29a774eba4a7a0e598acd57363380044dfa112d507227403f72ed"
SCHEMA = "fin-abs-001d/source-precision-robustness/1"
POLICY_ID = "FIN-ABS-001D-SOURCE-PRECISION-V1"
ABSOLUTE_SCORE_BEFORE = 423
ABSOLUTE_SCORE_PASS_DELTA = 6
ERROR_RATE = 0.05
RESOLVABILITY_MULTIPLIER = 2.0
NAIVE_MILLION_DIVISOR = 1_000_000.0
PERMUTATION_SEED = "FIN-ABS-001D-PERMUTATION-V1"


@dataclass(frozen=True)
class Precision:
    fact_id: str
    scale: int
    decimals: str
    format: str
    display_decimals: int
    quantum: float
    displayed_text: str
    source_value: float
    display_consistent: bool

    def data(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "scale": self.scale,
            "decimals": self.decimals,
            "format": self.format,
            "display_decimals": self.display_decimals,
            "quantum": self.quantum,
            "displayed_text": self.displayed_text,
            "source_value": self.source_value,
            "display_consistent": self.display_consistent,
        }


def numeric(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def display_number(value: object) -> tuple[float | None, int]:
    text = str(value or "").strip().replace("\u00a0", " ")
    if text.lower() in {"", "-", "—", "–", "−", "no", "nil", "none"}:
        return 0.0, 0
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = (
        text.replace("$", "")
        .replace(",", "")
        .replace(" ", "")
        .replace("−", "-")
        .replace("–", "-")
    )
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)", text)
    if match is None:
        return None, 0
    token = match.group(1)
    decimals = len(token.split(".", 1)[1]) if "." in token else 0
    result = float(token)
    return (-result if negative else result), decimals


def quantize(value: float, quantum: float) -> float:
    return float(round_half_away(value / quantum) * quantum)


def precision_from_item(item: Mapping[str, Any]) -> Precision | None:
    fact_id = str(item.get("fact_id") or "")
    source_value = numeric(item.get("value"))
    scale_raw = item.get("scale")
    displayed_text = str(item.get("displayed_text") or "")
    parsed, display_decimals = display_number(displayed_text)
    try:
        scale = int(scale_raw)
    except (TypeError, ValueError, OverflowError):
        return None
    exponent = scale - display_decimals
    if (
        not fact_id
        or source_value is None
        or parsed is None
        or exponent < -12
        or exponent > 18
    ):
        return None
    quantum = float(10.0**exponent)
    expected = float(parsed * (10.0**scale))
    consistency_tolerance = max(0.51 * quantum, 1e-9)
    consistent = abs(source_value - expected) <= consistency_tolerance
    if source_value == 0.0 and parsed == 0.0:
        consistent = True
    return Precision(
        fact_id=fact_id,
        scale=scale,
        decimals=str(item.get("decimals") or ""),
        format=str(item.get("format") or ""),
        display_decimals=display_decimals,
        quantum=quantum,
        displayed_text=displayed_text,
        source_value=source_value,
        display_consistent=consistent,
    )


def raw_facts(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = row.get("facts", [])
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def precision_index(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Precision], set[str]]:
    candidates: dict[str, list[Precision]] = defaultdict(list)
    for row in rows:
        for item in raw_facts(row):
            value = precision_from_item(item)
            if value is not None:
                candidates[value.fact_id].append(value)
    index: dict[str, Precision] = {}
    ambiguous: set[str] = set()
    for fact_id, values in candidates.items():
        signatures = {canonical(value.data()) for value in values}
        if len(signatures) == 1:
            index[fact_id] = values[0]
        else:
            ambiguous.add(fact_id)
    return index, ambiguous


def relation_signature(relations: Sequence[Relation]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "relation_id": relation.relation_id,
                "family": relation.family,
                "subtype": relation.subtype,
                "target_fact_id": relation.target.fact_id,
                "terms": [
                    {
                        "absolute": use_abs,
                        "coefficient": coefficient,
                        "fact_id": fact.fact_id,
                    }
                    for fact, coefficient, use_abs in relation.terms
                ],
            }
            for relation in relations
        ),
        key=lambda value: value["relation_id"],
    )


def enrich_relation(
    relation: Relation,
    precision: Mapping[str, Precision],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    facts = (relation.target, *(fact for fact, _, _ in relation.terms))
    missing = [fact.fact_id for fact in facts if fact.fact_id not in precision]
    if missing:
        return None, {"relation_id": relation.relation_id, "status": "MISSING_PRECISION", "fact_ids": missing}
    metadata = {fact.fact_id: precision[fact.fact_id] for fact in facts}
    if not all(value.display_consistent for value in metadata.values()):
        return None, {"relation_id": relation.relation_id, "status": "DISPLAY_INCONSISTENT"}
    if not all(abs(quantize(value.source_value, value.quantum) - value.source_value) <= max(1e-9, value.quantum * 1e-9) for value in metadata.values()):
        return None, {"relation_id": relation.relation_id, "status": "SOURCE_NOT_QUANTIZED"}

    values = relation.source_values()
    target_id = relation.target.fact_id
    original = float(values[target_id])
    if original == 0.0:
        return None, {"relation_id": relation.relation_id, "status": "ZERO_TARGET"}
    expected = relation.expected(values)
    base_tolerance = exact_tolerance(original, expected, len(relation.terms), rounded=False)
    target_quantum = metadata[target_id].quantum
    uncertainty = 0.5 * target_quantum + sum(
        0.5 * abs(coefficient) * metadata[fact.fact_id].quantum
        for fact, coefficient, _ in relation.terms
    )
    direction = -1.0 if int(digest(relation.relation_id)[-1], 16) % 2 else 1.0
    raw_modified = original + direction * ERROR_RATE * abs(original)
    modified = quantize(raw_modified, target_quantum)
    actual_delta = abs(modified - original)
    threshold = RESOLVABILITY_MULTIPLIER * uncertainty + base_tolerance
    if actual_delta <= threshold:
        return None, {
            "relation_id": relation.relation_id,
            "status": "NOT_RESOLVABLE_AT_SOURCE_PRECISION",
            "actual_delta": actual_delta,
            "threshold": threshold,
        }

    relation_data = relation.data()
    relation_data["precision"] = {
        fact_id: value.data() for fact_id, value in sorted(metadata.items())
    }
    relation_data["source_precision"] = {
        "target_quantum": target_quantum,
        "aggregate_half_quantum_uncertainty": uncertainty,
        "base_tolerance": base_tolerance,
        "resolvability_threshold": threshold,
        "error_rate": ERROR_RATE,
        "modified_target_value": modified,
        "actual_delta": actual_delta,
        "eligibility_margin": actual_delta - threshold,
    }
    return relation_data, {"relation_id": relation.relation_id, "status": "ELIGIBLE"}


def build_instances(relations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for relation in relations:
        values = {
            fact_id: float(fact["value"])
            for fact_id, fact in relation["facts"].items()
        }
        instances.append(
            {
                "instance_id": f"{relation['relation_id']}|CLEAN",
                "relation": relation,
                "values": values,
                "ground_truth": {"has_error": False},
            }
        )
        altered = dict(values)
        target_id = relation["target_fact_id"]
        altered[target_id] = float(relation["source_precision"]["modified_target_value"])
        instances.append(
            {
                "instance_id": f"{relation['relation_id']}|ERROR",
                "relation": relation,
                "values": altered,
                "ground_truth": {
                    "has_error": True,
                    "target_fact_id": target_id,
                    "error_rate": ERROR_RATE,
                    "original_value": values[target_id],
                    "modified_value": altered[target_id],
                },
            }
        )
    return instances


def expected(relation: Mapping[str, Any], values: Mapping[str, float]) -> float:
    total = 0.0
    for term in relation["terms"]:
        value = float(values[term["fact_id"]])
        if term["absolute"]:
            value = abs(value)
        total += float(term["coefficient"]) * value
    return total


def evaluate(instance: Mapping[str, Any], variant: str) -> dict[str, Any]:
    relation = instance["relation"]
    values = {key: float(value) for key, value in instance["values"].items()}
    if variant == "source_precision":
        values = {
            key: quantize(value, float(relation["precision"][key]["quantum"]))
            for key, value in values.items()
        }
    elif variant == "naive_million":
        values = {
            key: float(round_half_away(value / NAIVE_MILLION_DIVISOR))
            for key, value in values.items()
        }
    target_id = relation["target_fact_id"]
    observed = values[target_id]
    exp = expected(relation, values)
    if variant == "source_precision":
        tol = max(
            exact_tolerance(observed, exp, len(relation["terms"]), rounded=False),
            float(relation["source_precision"]["aggregate_half_quantum_uncertainty"]),
        )
    elif variant == "naive_million":
        tol = exact_tolerance(observed, exp, len(relation["terms"]), rounded=True)
    else:
        tol = exact_tolerance(observed, exp, len(relation["terms"]), rounded=False)
    residual = observed - exp
    decision = "ERROR" if abs(residual) > tol else "CLEAN"
    return {
        "instance_id": instance["instance_id"],
        "relation_id": relation["relation_id"],
        "family": relation["family"],
        "subtype": relation["subtype"],
        "ticker": relation["passage"]["ticker"],
        "cik": relation["passage"]["cik"],
        "sic_code": relation["passage"]["sic_code"],
        "variant": variant,
        "gold_error": bool(instance["ground_truth"]["has_error"]),
        "decision": decision,
        "observed": observed,
        "expected": exp,
        "residual": residual,
        "tolerance": tol,
        "prediction_sha256": digest(
            {
                "decision": decision,
                "observed": observed,
                "expected": exp,
                "residual": residual,
                "tolerance": tol,
            }
        ),
    }


def resolve_source(cache_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from huggingface_hub import HfApi, hf_hub_download
    import huggingface_hub
    import pyarrow
    import pyarrow.parquet as pq

    api = HfApi()
    info = api.dataset_info(SOURCE_REPO, revision=PINNED_SOURCE_REVISION)
    if str(info.sha) != PINNED_SOURCE_REVISION:
        raise RuntimeError("resolved source revision does not match pinned revision")
    files = api.list_repo_files(SOURCE_REPO, repo_type="dataset", revision=PINNED_SOURCE_REVISION)
    candidates = sorted(
        (path for path in files if path == "validation.parquet" or path.endswith("/validation.parquet")),
        key=lambda path: (path.count("/"), path),
    )
    if not candidates:
        raise RuntimeError("validation parquet not found")
    parquet_name = candidates[0]
    cache_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = Path(
        hf_hub_download(
            repo_id=SOURCE_REPO,
            filename=parquet_name,
            repo_type="dataset",
            revision=PINNED_SOURCE_REVISION,
            cache_dir=cache_dir,
        )
    )
    readme_path = Path(
        hf_hub_download(
            repo_id=SOURCE_REPO,
            filename="README.md",
            repo_type="dataset",
            revision=PINNED_SOURCE_REVISION,
            cache_dir=cache_dir,
        )
    )
    if sha256_file(parquet_path) != PINNED_PARQUET_SHA256:
        raise RuntimeError("validation parquet hash changed")
    table = pq.read_table(parquet_path)
    rows = table.to_pylist()
    source = {
        "repository": SOURCE_REPO,
        "revision": PINNED_SOURCE_REVISION,
        "version": SOURCE_VERSION,
        "selection_manifest_sha256": SOURCE_SELECTION_MANIFEST_SHA256,
        "selection_manifest_present_in_readme": SOURCE_SELECTION_MANIFEST_SHA256 in readme_path.read_text(encoding="utf-8"),
        "parquet_name": parquet_name,
        "parquet_sha256": sha256_file(parquet_path),
        "parquet_bytes": parquet_path.stat().st_size,
        "row_count": len(rows),
        "huggingface_hub_version": huggingface_hub.__version__,
        "pyarrow_version": pyarrow.__version__,
        "python_version": platform.python_version(),
    }
    return rows, source


def build_report(
    source: Mapping[str, Any],
    base_relations: Sequence[Relation],
    eligible_relations: Sequence[Mapping[str, Any]],
    exclusions: Sequence[Mapping[str, Any]],
    instances: Sequence[Mapping[str, Any]],
    exact_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
    naive_rows: Sequence[Mapping[str, Any]],
    relations_sha256: str,
    instances_sha256: str,
) -> dict[str, Any]:
    exact = metrics(exact_rows)
    source_precision = metrics(source_rows)
    naive = metrics(naive_rows)
    permutation = permutation_control(source_rows)
    companies = {relation["passage"]["cik"] for relation in eligible_relations}
    sics = {relation["passage"]["sic_code"] for relation in eligible_relations if relation["passage"].get("sic_code")}
    families = Counter(relation["family"] for relation in eligible_relations)
    subtypes = Counter(relation["subtype"] for relation in eligible_relations)
    base_ids = sorted(relation.relation_id for relation in base_relations)
    base_signature = relation_signature(base_relations)
    exclusion_counts = Counter(str(value["status"]) for value in exclusions)
    checks = {
        "source_revision_exact": source.get("revision") == PINNED_SOURCE_REVISION,
        "source_parquet_hash_exact": source.get("parquet_sha256") == PINNED_PARQUET_SHA256,
        "source_manifest_verified": source.get("selection_manifest_present_in_readme") is True,
        "base_relation_count_exact": len(base_relations) == PINNED_BASE_RELATION_COUNT,
        "base_relation_id_hash_exact": digest(base_ids) == PINNED_BASE_RELATION_ID_SHA256,
        "base_relation_signature_hash_exact": digest(base_signature) == PINNED_BASE_RELATION_SIGNATURE_SHA256,
        "all_eligible_directly_grounded": all(direct_provenance(relation) for relation in eligible_relations),
        "all_eligible_precision_verified": all(
            all(value.get("display_consistent") is True and float(value.get("quantum", 0)) > 0 for value in relation["precision"].values())
            for relation in eligible_relations
        ),
        "all_eligible_resolvable_ex_ante": all(
            float(relation["source_precision"]["actual_delta"])
            > float(relation["source_precision"]["resolvability_threshold"])
            for relation in eligible_relations
        ),
        "eligible_companies_at_least_100": len(companies) >= 100,
        "eligible_relations_at_least_300": len(eligible_relations) >= 300,
        "sic_codes_at_least_70": len(sics) >= 70,
        "dimension_relations_at_least_250": families.get("DIMENSION_TOTAL", 0) >= 250,
        "statement_relations_at_least_50": families.get("STATEMENT_EQUATION", 0) >= 50,
        "exact_precision_one": exact.get("precision") == 1.0,
        "exact_recall_one": exact.get("recall") == 1.0,
        "exact_zero_fpr": exact.get("false_positive_rate") == 0.0,
        "source_precision_one": source_precision.get("precision") == 1.0,
        "source_precision_recall_at_least_99pct": (source_precision.get("recall") or 0.0) >= 0.99,
        "source_precision_zero_fpr": source_precision.get("false_positive_rate") == 0.0,
        "source_precision_full_coverage": source_precision.get("coverage") == 1.0,
        "beats_naive_million_by_25_points": (
            (source_precision.get("recall") or 0.0) - (naive.get("recall") or 0.0) >= 0.25
        ),
        "permutation_worse": (
            (permutation["metrics"].get("false_positive_rate") or 0.0) > (source_precision.get("false_positive_rate") or 0.0)
            or (permutation["metrics"].get("recall") or 0.0) < (source_precision.get("recall") or 0.0)
        ),
    }
    passed = all(checks.values())
    score_after = ABSOLUTE_SCORE_BEFORE + (ABSOLUTE_SCORE_PASS_DELTA if passed else 0)
    payload = {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "status": "PASS_SOURCE_PRECISION_ROBUSTNESS" if passed else "OPEN_SOURCE_PRECISION_ROBUSTNESS",
        "source": dict(source),
        "frozen_parent": {
            "experiment": "FIN-ABS-001C",
            "source_revision": PINNED_SOURCE_REVISION,
            "base_relation_count": len(base_relations),
            "base_relation_id_sha256": digest(base_ids),
            "base_relation_signature_sha256": digest(base_signature),
            "parent_report_sha256": "2b0c105024c1f5701f1e3bee4fe0192a408907c81a717c61e2970ea7cfcf891f",
            "parent_rounded_recall": 0.55893536121673,
        },
        "cohort": {
            "eligible_companies": len(companies),
            "eligible_relations": len(eligible_relations),
            "sic_count": len(sics),
            "family_counts": dict(sorted(families.items())),
            "subtype_counts": dict(sorted(subtypes.items())),
            "exclusion_counts": dict(sorted(exclusion_counts.items())),
            "relations_sha256": relations_sha256,
            "instances_sha256": instances_sha256,
        },
        "exact_metrics": exact,
        "source_precision_metrics": source_precision,
        "naive_million_metrics": naive,
        "permutation_control": permutation,
        "gate_checks": checks,
        "absolute_score": {
            "before": ABSOLUTE_SCORE_BEFORE,
            "after": score_after,
            "delta": score_after - ABSOLUTE_SCORE_BEFORE,
            "allocation_if_pass": {
                "generality": 3,
                "external_validation": 3,
                "world_sota": 0,
                "historical_originality": 0,
            },
            "boundary": (
                "FIN-ABS-001D can close only the independent-dataset transfer and source-presentation robustness gate left open by FIN-ABS-001C. "
                "It cannot add world-SOTA or historical-originality points and cannot establish Finance 1000."
            ),
        },
        "boundary": (
            "Eligibility is decided only from source scale, displayed resolution, exact relation coefficients, and a frozen 5% perturbation before outcomes are evaluated. "
            "The experiment does not certify filings, value firms, predict returns, or establish universal Finance SOTA."
        ),
    }
    payload_canonical = canonical(payload)
    return {"payload": payload, "payload_canonical": payload_canonical, "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir
    cache = args.cache_dir or output / "hf-cache"
    output.mkdir(parents=True, exist_ok=True)

    rows, source = resolve_source(cache)
    base_relations = mine_relations(rows)
    precision, ambiguous = precision_index(rows)
    eligible: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for relation in base_relations:
        value, exclusion = enrich_relation(relation, precision)
        exclusions.append(exclusion)
        if value is not None:
            eligible.append(value)
    eligible.sort(key=lambda value: value["relation_id"])
    instances = build_instances(eligible)
    exact_rows = [evaluate(instance, "exact") for instance in instances]
    source_rows = [evaluate(instance, "source_precision") for instance in instances]
    naive_rows = [evaluate(instance, "naive_million") for instance in instances]

    relations_path = output / "relations.json"
    instances_path = output / "instances.json"
    write_json(relations_path, eligible)
    write_json(instances_path, instances)
    report = build_report(
        source,
        base_relations,
        eligible,
        exclusions,
        instances,
        exact_rows,
        source_rows,
        naive_rows,
        sha256_file(relations_path),
        sha256_file(instances_path),
    )
    source_output = dict(source)
    source_output["precision_index_size"] = len(precision)
    source_output["ambiguous_precision_fact_ids"] = len(ambiguous)
    write_json(output / "source.json", source_output)
    write_json(output / "exclusions.json", exclusions)
    write_json(output / "report.json", report)
    for name, values in (
        ("predictions_exact.jsonl", exact_rows),
        ("predictions_source_precision.jsonl", source_rows),
        ("predictions_naive_million.jsonl", naive_rows),
    ):
        (output / name).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in values),
            encoding="utf-8",
        )
    payload = report["payload"]
    source_metrics = payload["source_precision_metrics"]
    naive_metrics = payload["naive_million_metrics"]
    (output / "report.md").write_text(
        "\n".join(
            [
                "# FIN-ABS-001D — source-precision robustness",
                "",
                f"- Status: **{payload['status']}**",
                f"- Eligible companies / relations: **{payload['cohort']['eligible_companies']} / {payload['cohort']['eligible_relations']}**",
                f"- Source-precision recall / FPR: **{source_metrics['recall']:.4f} / {source_metrics['false_positive_rate']:.4f}**",
                f"- Naive-million recall / FPR: **{naive_metrics['recall']:.4f} / {naive_metrics['false_positive_rate']:.4f}**",
                f"- Absolute score: **{payload['absolute_score']['before']} → {payload['absolute_score']['after']}**",
                f"- Report SHA-256: `{report['sha256']}`",
                "",
                payload["boundary"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "eligible_companies": payload["cohort"]["eligible_companies"],
                "eligible_relations": payload["cohort"]["eligible_relations"],
                "family_counts": payload["cohort"]["family_counts"],
                "source_precision_recall": source_metrics["recall"],
                "source_precision_fpr": source_metrics["false_positive_rate"],
                "naive_million_recall": naive_metrics["recall"],
                "score_after": payload["absolute_score"]["after"],
                "report_sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
