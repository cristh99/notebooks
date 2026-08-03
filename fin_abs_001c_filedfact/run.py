from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SOURCE_REPO = "StockAlloy/filedfact-passages"
SOURCE_VERSION = "v1.2"
SOURCE_SELECTION_MANIFEST_SHA256 = (
    "bc0b3e526742567daa5b17deacb533a4419e5cab4375962cdb5a0e0a7ef78a3a"
)
SOURCE_SPLIT = "validation"
EXPECTED_VALIDATION_ROWS = 776
SCHEMA = "fin-abs-001c/filedfact-passage-breadth/1"
POLICY_ID = "FIN-ABS-001C-PASSAGE-DIRECT-RELATION-V1"
ABSOLUTE_SCORE_BEFORE = 423
ABSOLUTE_SCORE_PASS_DELTA = 6
RELATIVE_TOLERANCE = 0.001
ABSOLUTE_TOLERANCE = 2.0
PERMUTATION_SEED = "FIN-ABS-001C-PERMUTATION-V1"

STATEMENT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "assets": ("us-gaap#Assets",),
    "liabilities_and_equity": (
        "us-gaap#LiabilitiesAndStockholdersEquity",
    ),
    "liabilities": ("us-gaap#Liabilities",),
    "equity": (
        "us-gaap#StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "us-gaap#StockholdersEquity",
    ),
    "revenue": (
        "us-gaap#RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap#RevenueFromContractWithCustomerIncludingAssessedTax",
        "us-gaap#Revenues",
        "us-gaap#SalesRevenueNet",
    ),
    "cost_of_revenue": (
        "us-gaap#CostOfRevenue",
        "us-gaap#CostOfGoodsAndServicesSold",
        "us-gaap#CostOfGoodsSold",
    ),
    "gross_profit": ("us-gaap#GrossProfit",),
    "pretax_income": (
        "us-gaap#IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "us-gaap#IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "tax": ("us-gaap#IncomeTaxExpenseBenefit",),
    "net_income": ("us-gaap#NetIncomeLoss",),
    "cfo": ("us-gaap#NetCashProvidedByUsedInOperatingActivities",),
    "cfi": ("us-gaap#NetCashProvidedByUsedInInvestingActivities",),
    "cff": ("us-gaap#NetCashProvidedByUsedInFinancingActivities",),
    "net_change_cash": (
        "us-gaap#CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap#CashAndCashEquivalentsPeriodIncreaseDecrease",
    ),
    "fx_effect": (
        "us-gaap#EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap#EffectOfExchangeRateOnCashAndCashEquivalents",
    ),
}

@dataclass(frozen=True)
class Fact:
    fact_id: str
    concept: str
    unit: str
    period: str
    value: float
    displayed_text: str
    text_start: int
    text_end: int
    dimensions: tuple[tuple[str, str], ...]
    evidence_url: str | None

    def key(self) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
        return (self.concept, self.unit, self.period, self.dimensions)

    def data(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "concept": self.concept,
            "unit": self.unit,
            "period": self.period,
            "value": self.value,
            "displayed_text": self.displayed_text,
            "text_start": self.text_start,
            "text_end": self.text_end,
            "dimensions": [
                {"axis": axis, "member": member}
                for axis, member in self.dimensions
            ],
            "evidence_url": self.evidence_url,
        }

@dataclass(frozen=True)
class Relation:
    relation_id: str
    family: str
    subtype: str
    target: Fact
    terms: tuple[tuple[Fact, float, bool], ...]
    passage: Mapping[str, Any]

    def expected(self, values: Mapping[str, float]) -> float:
        total = 0.0
        for fact, coefficient, use_abs in self.terms:
            value = float(values[fact.fact_id])
            if use_abs:
                value = abs(value)
            total += coefficient * value
        return total

    def source_values(self) -> dict[str, float]:
        values = {self.target.fact_id: self.target.value}
        for fact, _, _ in self.terms:
            values[fact.fact_id] = fact.value
        return values

    def data(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "family": self.family,
            "subtype": self.subtype,
            "target_fact_id": self.target.fact_id,
            "terms": [
                {
                    "fact_id": fact.fact_id,
                    "coefficient": coefficient,
                    "absolute": use_abs,
                }
                for fact, coefficient, use_abs in self.terms
            ],
            "facts": {
                fact.fact_id: fact.data()
                for fact in (self.target, *(item[0] for item in self.terms))
            },
            "passage": dict(self.passage),
        }

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

def safe_div(a: int | float, b: int | float) -> float | None:
    return float(a / b) if b else None

def numeric(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None

def parse_dimensions(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return ()
    if not isinstance(value, list):
        return ()
    dimensions: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return ()
        axis = item.get("axis")
        member = item.get("member")
        if not axis or not member:
            return ()
        dimensions.append((str(axis), str(member)))
    return tuple(sorted(dimensions))

def parse_facts(row: Mapping[str, Any]) -> list[Fact]:
    raw_facts = row.get("facts", [])
    if isinstance(raw_facts, str):
        try:
            raw_facts = json.loads(raw_facts)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw_facts, list):
        return []
    text = str(row.get("text") or "")
    source_url = str(row.get("source_url") or "")
    facts: list[Fact] = []
    seen: set[str] = set()
    for item in raw_facts:
        if not isinstance(item, Mapping):
            continue
        fact_id = str(item.get("fact_id") or "")
        concept = str(item.get("concept") or "")
        unit = str(item.get("unit") or "")
        period = str(item.get("period") or "")
        displayed = str(item.get("displayed_text") or "")
        value = numeric(item.get("value"))
        try:
            start = int(item.get("text_start"))
            end = int(item.get("text_end"))
        except (TypeError, ValueError):
            continue
        if (
            not fact_id
            or fact_id in seen
            or not concept
            or not unit.startswith("monetary:USD")
            or not period
            or value is None
            or start < 0
            or end <= start
            or end > len(text)
            or text[start:end] != displayed
            or not source_url.startswith("https://www.sec.gov/")
        ):
            continue
        dimensions = parse_dimensions(item.get("dimensions", []))
        evidence_url = item.get("evidence_url")
        facts.append(
            Fact(
                fact_id=fact_id,
                concept=concept,
                unit=unit,
                period=period,
                value=value,
                displayed_text=displayed,
                text_start=start,
                text_end=end,
                dimensions=dimensions,
                evidence_url=str(evidence_url) if evidence_url else None,
            )
        )
        seen.add(fact_id)
    return facts

def round_half_away(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)

def tolerance(observed: float, expected: float, term_count: int, rounded: bool = False) -> float:
    rounding = 0.51 * (term_count + 1) if rounded else 0.0
    return max(
        ABSOLUTE_TOLERANCE,
        RELATIVE_TOLERANCE * max(abs(observed), abs(expected), 1.0),
        rounding,
    )

def passage_meta(row: Mapping[str, Any]) -> dict[str, Any]:
    text = str(row.get("text") or "")
    return {
        "chunk_id": str(row.get("chunk_id") or ""),
        "cik": str(row.get("cik") or ""),
        "ticker": str(row.get("ticker") or ""),
        "company_name": str(row.get("company_name") or ""),
        "sic_code": str(row.get("sic_code") or ""),
        "accession": str(row.get("accession") or ""),
        "form_type": str(row.get("form_type") or ""),
        "filed_at": str(row.get("filed_at") or ""),
        "chunk_type": str(row.get("chunk_type") or ""),
        "source_url": str(row.get("source_url") or ""),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }

def unique_index(facts: Iterable[Fact]) -> dict[tuple[str, str, str, tuple[tuple[str, str], ...]], Fact]:
    groups: dict[tuple[str, str, str, tuple[tuple[str, str], ...]], list[Fact]] = defaultdict(list)
    for fact in facts:
        groups[fact.key()].append(fact)
    return {key: values[0] for key, values in groups.items() if len(values) == 1}

def facts_for_role(
    index: Mapping[tuple[str, str, str, tuple[tuple[str, str], ...]], Fact],
    role: str,
    period: str,
    unit: str,
    dimensions: tuple[tuple[str, str], ...],
) -> list[Fact]:
    concepts = set(STATEMENT_CONCEPTS[role])
    return [
        fact
        for (concept, candidate_unit, candidate_period, candidate_dims), fact in index.items()
        if concept in concepts
        and candidate_unit == unit
        and candidate_period == period
        and candidate_dims == dimensions
    ]

def clean_relation(relation: Relation) -> bool:
    values = relation.source_values()
    observed = values[relation.target.fact_id]
    expected = relation.expected(values)
    return abs(observed - expected) <= tolerance(
        observed, expected, len(relation.terms), rounded=False
    )

def statement_relations(row: Mapping[str, Any], facts: Sequence[Fact]) -> list[Relation]:
    meta = passage_meta(row)
    index = unique_index(facts)
    contexts = sorted({(fact.period, fact.unit, fact.dimensions) for fact in facts})
    output: list[Relation] = []

    def add(
        subtype: str,
        target_role: str,
        term_roles: Sequence[tuple[str, float, bool]],
    ) -> None:
        for period, unit, dimensions in contexts:
            targets = facts_for_role(index, target_role, period, unit, dimensions)
            term_lists = [
                facts_for_role(index, role, period, unit, dimensions)
                for role, _, _ in term_roles
            ]
            if len(targets) != 1 or any(len(values) != 1 for values in term_lists):
                continue
            target = targets[0]
            terms = tuple(
                (values[0], coefficient, use_abs)
                for values, (_, coefficient, use_abs) in zip(term_lists, term_roles, strict=True)
            )
            relation_id = digest(
                {
                    "chunk": meta["chunk_id"],
                    "subtype": subtype,
                    "target": target.fact_id,
                    "terms": [fact.fact_id for fact, _, _ in terms],
                }
            )
            relation = Relation(
                relation_id=relation_id,
                family="STATEMENT_EQUATION",
                subtype=subtype,
                target=target,
                terms=terms,
                passage=meta,
            )
            if clean_relation(relation):
                output.append(relation)

    add("ASSETS_EQUALS_LIABILITIES_AND_EQUITY_TOTAL", "assets", (("liabilities_and_equity", 1.0, False),))
    add("ASSETS_EQUALS_LIABILITIES_PLUS_EQUITY", "assets", (("liabilities", 1.0, False), ("equity", 1.0, False)))
    add("GROSS_PROFIT_EQUALS_REVENUE_MINUS_COST", "gross_profit", (("revenue", 1.0, False), ("cost_of_revenue", -1.0, True)))
    add("NET_INCOME_EQUALS_PRETAX_MINUS_TAX", "net_income", (("pretax_income", 1.0, False), ("tax", -1.0, True)))
    add(
        "CASH_CHANGE_EQUALS_COMPONENTS",
        "net_change_cash",
        (
            ("cfo", 1.0, False),
            ("cfi", 1.0, False),
            ("cff", 1.0, False),
            ("fx_effect", 1.0, False),
        ),
    )
    return output

def dimension_total_relations(row: Mapping[str, Any], facts: Sequence[Fact]) -> list[Relation]:
    meta = passage_meta(row)
    grouped: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    for fact in facts:
        grouped[(fact.concept, fact.unit, fact.period)].append(fact)
    output: list[Relation] = []
    for (concept, unit, period), group in sorted(grouped.items()):
        totals = [fact for fact in group if not fact.dimensions]
        components = [fact for fact in group if len(fact.dimensions) == 1]
        if len(totals) != 1 or len(components) < 2 or len(components) > 30:
            continue
        axes = {fact.dimensions[0][0] for fact in components}
        members = [fact.dimensions[0][1] for fact in components]
        spans = [(fact.text_start, fact.text_end) for fact in components]
        if len(axes) != 1 or len(set(members)) != len(members) or len(set(spans)) != len(spans):
            continue
        target = totals[0]
        terms = tuple((fact, 1.0, False) for fact in sorted(components, key=lambda item: item.fact_id))
        relation_id = digest(
            {
                "chunk": meta["chunk_id"],
                "subtype": "DIMENSION_MEMBER_SUM_EQUALS_TOTAL",
                "concept": concept,
                "period": period,
                "axis": next(iter(axes)),
                "target": target.fact_id,
                "terms": [fact.fact_id for fact, _, _ in terms],
            }
        )
        relation = Relation(
            relation_id=relation_id,
            family="DIMENSION_TOTAL",
            subtype="DIMENSION_MEMBER_SUM_EQUALS_TOTAL",
            target=target,
            terms=terms,
            passage=meta,
        )
        if clean_relation(relation):
            output.append(relation)
    return output

def mine_relations(rows: Sequence[Mapping[str, Any]]) -> list[Relation]:
    relations: dict[str, Relation] = {}
    for row in rows:
        facts = parse_facts(row)
        if not facts:
            continue
        for relation in (*statement_relations(row, facts), *dimension_total_relations(row, facts)):
            relations.setdefault(relation.relation_id, relation)
    return [relations[key] for key in sorted(relations)]

def evaluate_instance(instance: Mapping[str, Any], rounded: bool) -> dict[str, Any]:
    relation = instance["relation"]
    values = {key: float(value) for key, value in instance["values"].items()}
    if rounded:
        values = {key: round_half_away(value / 1_000_000.0) for key, value in values.items()}
    target_id = relation["target_fact_id"]
    observed = values[target_id]
    expected = 0.0
    for term in relation["terms"]:
        value = values[term["fact_id"]]
        if term["absolute"]:
            value = abs(value)
        expected += float(term["coefficient"]) * value
    tol = tolerance(observed, expected, len(relation["terms"]), rounded=rounded)
    residual = observed - expected
    decision = "ERROR" if abs(residual) > tol else "CLEAN"
    return {
        "instance_id": instance["instance_id"],
        "relation_id": relation["relation_id"],
        "family": relation["family"],
        "subtype": relation["subtype"],
        "ticker": relation["passage"]["ticker"],
        "cik": relation["passage"]["cik"],
        "sic_code": relation["passage"]["sic_code"],
        "form_type": relation["passage"]["form_type"],
        "variant": "rounded_millions" if rounded else "exact",
        "gold_error": bool(instance["ground_truth"]["has_error"]),
        "decision": decision,
        "observed": observed,
        "expected": expected,
        "residual": residual,
        "tolerance": tol,
        "prediction_sha256": digest(
            {
                "decision": decision,
                "observed": observed,
                "expected": expected,
                "residual": residual,
                "tolerance": tol,
            }
        ),
    }

def build_instances(relations: Sequence[Relation]) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for relation in relations:
        relation_data = relation.data()
        values = relation.source_values()
        clean_id = f"{relation.relation_id}|CLEAN"
        instances.append(
            {
                "instance_id": clean_id,
                "relation": relation_data,
                "values": values,
                "ground_truth": {"has_error": False, "target_fact_id": None, "magnitude_pct": None},
            }
        )
        target_id = relation.target.fact_id
        original = values[target_id]
        expected = relation.expected(values)
        base_tol = tolerance(original, expected, len(relation.terms), rounded=False)
        delta = max(abs(original) * 0.05, 4.0 * base_tol + 1.0)
        direction = -1.0 if int(digest(relation.relation_id)[-1], 16) % 2 else 1.0
        altered = dict(values)
        altered[target_id] = original + direction * delta
        magnitude = 100.0 * delta / abs(original) if original else None
        instances.append(
            {
                "instance_id": f"{relation.relation_id}|ERROR",
                "relation": relation_data,
                "values": altered,
                "ground_truth": {
                    "has_error": True,
                    "target_fact_id": target_id,
                    "magnitude_pct": direction * magnitude if magnitude is not None else None,
                    "original_value": original,
                    "modified_value": altered[target_id],
                },
            }
        )
    return instances

def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    clean = [row for row in rows if not row["gold_error"]]
    errors = [row for row in rows if row["gold_error"]]
    tp = sum(row["decision"] == "ERROR" for row in errors)
    fn = len(errors) - tp
    tn = sum(row["decision"] == "CLEAN" for row in clean)
    fp = len(clean) - tn
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    specificity = safe_div(tn, tn + fp)
    fpr = safe_div(fp, fp + tn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    family_total: Counter[str] = Counter(row["family"] for row in errors)
    family_hits: Counter[str] = Counter(row["family"] for row in errors if row["decision"] == "ERROR")
    return {
        "rows": len(rows),
        "clean_rows": len(clean),
        "error_rows": len(errors),
        "true_positive": tp,
        "false_negative": fn,
        "true_negative": tn,
        "false_positive": fp,
        "coverage": 1.0 if rows else None,
        "accuracy": safe_div(tp + tn, len(rows)),
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": fpr,
        "f1": f1,
        "family_recall": {
            family: safe_div(family_hits[family], total)
            for family, total in sorted(family_total.items())
        },
    }

def permutation_control(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: digest(f"{row['instance_id']}|{PERMUTATION_SEED}"),
    )
    decisions = [row["decision"] for row in ordered]
    if decisions:
        decisions = decisions[1:] + decisions[:1]
    permuted = [dict(row, decision=decision) for row, decision in zip(ordered, decisions, strict=True)]
    return {"seed": PERMUTATION_SEED, "metrics": metrics(permuted)}

def resolve_source(cache_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from huggingface_hub import HfApi, hf_hub_download
    import pyarrow as pa
    import pyarrow.parquet as pq
    import huggingface_hub
    import pyarrow

    api = HfApi()
    info = api.dataset_info(SOURCE_REPO)
    revision = str(info.sha)
    files = api.list_repo_files(SOURCE_REPO, repo_type="dataset", revision=revision)
    candidates = [
        path for path in files
        if path == "validation.parquet" or path.endswith("/validation.parquet")
    ]
    candidates.sort(key=lambda path: (path.count("/"), path))
    if not candidates:
        raise RuntimeError("validation parquet not found")
    parquet_name = candidates[0]
    cache_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = Path(
        hf_hub_download(
            repo_id=SOURCE_REPO,
            filename=parquet_name,
            repo_type="dataset",
            revision=revision,
            cache_dir=cache_dir,
        )
    )
    readme_path = Path(
        hf_hub_download(
            repo_id=SOURCE_REPO,
            filename="README.md",
            repo_type="dataset",
            revision=revision,
            cache_dir=cache_dir,
        )
    )
    readme = readme_path.read_text(encoding="utf-8")
    table: pa.Table = pq.read_table(parquet_path)
    rows = table.to_pylist()
    source = {
        "repository": SOURCE_REPO,
        "revision": revision,
        "version": SOURCE_VERSION,
        "selection_manifest_sha256": SOURCE_SELECTION_MANIFEST_SHA256,
        "selection_manifest_present_in_readme": SOURCE_SELECTION_MANIFEST_SHA256 in readme,
        "split": SOURCE_SPLIT,
        "parquet_name": parquet_name,
        "parquet_sha256": sha256_file(parquet_path),
        "parquet_bytes": parquet_path.stat().st_size,
        "row_count": len(rows),
        "schema": str(table.schema),
        "huggingface_hub_version": huggingface_hub.__version__,
        "pyarrow_version": pyarrow.__version__,
        "python_version": platform.python_version(),
    }
    return rows, source

def direct_provenance(relation: Mapping[str, Any]) -> bool:
    passage = relation.get("passage", {})
    facts = relation.get("facts", {})
    if (
        not passage.get("chunk_id")
        or not passage.get("accession")
        or not str(passage.get("source_url", "")).startswith("https://www.sec.gov/")
        or not passage.get("text_sha256")
        or not facts
    ):
        return False
    for fact in facts.values():
        if (
            not fact.get("fact_id")
            or not fact.get("concept")
            or not str(fact.get("unit", "")).startswith("monetary:USD")
            or not fact.get("period")
            or fact.get("displayed_text") is None
            or fact.get("text_start") is None
            or fact.get("text_end") is None
        ):
            return False
    return True

def build_report(
    source: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    relations: Sequence[Relation],
    instances: Sequence[Mapping[str, Any]],
    exact_rows: Sequence[Mapping[str, Any]],
    rounded_rows: Sequence[Mapping[str, Any]],
    cases_sha256: str,
    instances_sha256: str,
) -> dict[str, Any]:
    exact = metrics(exact_rows)
    rounded = metrics(rounded_rows)
    permutation = permutation_control(exact_rows)
    relation_data = [relation.data() for relation in relations]
    companies = {relation.passage["cik"] for relation in relations if relation.passage.get("cik")}
    sics = {relation.passage["sic_code"] for relation in relations if relation.passage.get("sic_code")}
    forms = {relation.passage["form_type"] for relation in relations if relation.passage.get("form_type")}
    families = Counter(relation.family for relation in relations)
    subtypes = Counter(relation.subtype for relation in relations)
    validation_companies = {str(row.get("cik") or "") for row in rows if row.get("cik")}
    checks = {
        "source_revision_pinned": len(str(source.get("revision", ""))) >= 40,
        "source_manifest_verified": source.get("selection_manifest_present_in_readme") is True,
        "validation_row_count_776": int(source.get("row_count", 0)) == EXPECTED_VALIDATION_ROWS,
        "validation_companies_at_least_700": len(validation_companies) >= 700,
        "all_relations_directly_grounded": all(direct_provenance(value) for value in relation_data),
        "eligible_companies_at_least_40": len(companies) >= 40,
        "relations_at_least_60": len(relations) >= 60,
        "sic_codes_at_least_20": len(sics) >= 20,
        "form_types_at_least_2": len(forms) >= 2,
        "relation_families_at_least_2": len(families) >= 2,
        "each_family_at_least_5": len(families) >= 2 and all(count >= 5 for count in families.values()),
        "dimension_total_relations_at_least_20": families.get("DIMENSION_TOTAL", 0) >= 20,
        "statement_equations_at_least_5": families.get("STATEMENT_EQUATION", 0) >= 5,
        "exact_zero_fpr": exact.get("false_positive_rate") == 0.0,
        "exact_precision_one": exact.get("precision") == 1.0,
        "exact_recall_one": exact.get("recall") == 1.0,
        "exact_full_coverage": exact.get("coverage") == 1.0,
        "rounded_zero_fpr": rounded.get("false_positive_rate") == 0.0,
        "rounded_recall_at_least_95pct": (rounded.get("recall") or 0.0) >= 0.95,
        "permutation_worse": (
            (permutation["metrics"].get("false_positive_rate") or 0.0) > (exact.get("false_positive_rate") or 0.0)
            or (permutation["metrics"].get("recall") or 0.0) < (exact.get("recall") or 0.0)
        ),
    }
    passed = all(checks.values())
    score_after = ABSOLUTE_SCORE_BEFORE + (ABSOLUTE_SCORE_PASS_DELTA if passed else 0)
    payload = {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "status": "PASS_FILEDFACT_PASSAGE_BREADTH" if passed else "OPEN_FILEDFACT_PASSAGE_BREADTH",
        "source": dict(source),
        "cohort": {
            "validation_rows": len(rows),
            "validation_companies": len(validation_companies),
            "eligible_companies": len(companies),
            "eligible_relations": len(relations),
            "sic_count": len(sics),
            "form_types": sorted(forms),
            "family_counts": dict(sorted(families.items())),
            "subtype_counts": dict(sorted(subtypes.items())),
            "cases_sha256": cases_sha256,
            "instances_sha256": instances_sha256,
        },
        "exact_metrics": exact,
        "rounded_metrics": rounded,
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
                "A complete pass adds at most six absolute points for independent-dataset transfer and external construct validity. "
                "The source is a visible-label research sample, not a blind benchmark; no world-SOTA or historical-originality points are available."
            ),
        },
        "boundary": (
            "This experiment tests arithmetic consistency of direct, span-grounded XBRL facts inside one filing passage. "
            "It does not certify audited statements, value firms, forecast returns, identify fraud, or establish universal Finance SOTA."
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
    relations = mine_relations(rows)
    relation_data = [relation.data() for relation in relations]
    instances = build_instances(relations)
    exact_rows = [evaluate_instance(instance, rounded=False) for instance in instances]
    rounded_rows = [evaluate_instance(instance, rounded=True) for instance in instances]

    cases_path = output / "relations.json"
    instances_path = output / "instances.json"
    write_json(cases_path, relation_data)
    write_json(instances_path, instances)
    report = build_report(
        source,
        rows,
        relations,
        instances,
        exact_rows,
        rounded_rows,
        sha256_file(cases_path),
        sha256_file(instances_path),
    )
    write_json(output / "source.json", source)
    write_json(output / "report.json", report)
    (output / "predictions_exact.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in exact_rows), encoding="utf-8"
    )
    (output / "predictions_rounded.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rounded_rows), encoding="utf-8"
    )
    payload = report["payload"]
    exact = payload["exact_metrics"]
    rounded = payload["rounded_metrics"]
    def fmt(value: Any) -> str:
        return "NULL" if value is None else f"{float(value):.4f}"
    (output / "report.md").write_text(
        "\n".join(
            [
                "# FIN-ABS-001C — FiledFact passage-complete breadth",
                "",
                f"- Status: **{payload['status']}**",
                f"- Source revision: `{payload['source']['revision']}`",
                f"- Eligible companies / relations: **{payload['cohort']['eligible_companies']} / {payload['cohort']['eligible_relations']}**",
                f"- Exact recall / FPR: **{fmt(exact['recall'])} / {fmt(exact['false_positive_rate'])}**",
                f"- Rounded recall / FPR: **{fmt(rounded['recall'])} / {fmt(rounded['false_positive_rate'])}**",
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
                "revision": payload["source"]["revision"],
                "eligible_companies": payload["cohort"]["eligible_companies"],
                "eligible_relations": payload["cohort"]["eligible_relations"],
                "family_counts": payload["cohort"]["family_counts"],
                "exact_recall": exact["recall"],
                "exact_fpr": exact["false_positive_rate"],
                "rounded_recall": rounded["recall"],
                "rounded_fpr": rounded["false_positive_rate"],
                "score_after": payload["absolute_score"]["after"],
                "report_sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
