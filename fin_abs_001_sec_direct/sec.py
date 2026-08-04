from __future__ import annotations

import itertools
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from .core import digest, relation_check

SEC_ENDPOINT = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "cristh99 finance-research 87334928+cristh99@users.noreply.github.com",
)

# Frozen before the run. This is the same 50-company universe used by the
# pinned public FinVerBench acquisition script.
UNIVERSE: tuple[tuple[str, str, str], ...] = (
    ("AAPL", "0000320193", "Apple Inc."),
    ("MSFT", "0000789019", "Microsoft Corporation"),
    ("AMZN", "0001018724", "Amazon.com Inc."),
    ("GOOGL", "0001652044", "Alphabet Inc."),
    ("META", "0001326801", "Meta Platforms Inc."),
    ("BRK.B", "0001067983", "Berkshire Hathaway Inc."),
    ("JNJ", "0000200406", "Johnson & Johnson"),
    ("V", "0001403161", "Visa Inc."),
    ("JPM", "0000019617", "JPMorgan Chase & Co."),
    ("PG", "0000080424", "Procter & Gamble Company"),
    ("UNH", "0000731766", "UnitedHealth Group Inc."),
    ("HD", "0000354950", "The Home Depot Inc."),
    ("MA", "0001141391", "Mastercard Inc."),
    ("NVDA", "0001045810", "NVIDIA Corporation"),
    ("DIS", "0001744489", "The Walt Disney Company"),
    ("BAC", "0000070858", "Bank of America Corporation"),
    ("XOM", "0000034088", "Exxon Mobil Corporation"),
    ("PFE", "0000078003", "Pfizer Inc."),
    ("CSCO", "0000858877", "Cisco Systems Inc."),
    ("KO", "0000021344", "The Coca-Cola Company"),
    ("PEP", "0000077476", "PepsiCo Inc."),
    ("TMO", "0000097745", "Thermo Fisher Scientific Inc."),
    ("COST", "0000909832", "Costco Wholesale Corporation"),
    ("ABT", "0000001800", "Abbott Laboratories"),
    ("CRM", "0001108524", "Salesforce Inc."),
    ("AVGO", "0001649338", "Broadcom Inc."),
    ("NKE", "0000320187", "NIKE Inc."),
    ("MRK", "0000310158", "Merck & Co. Inc."),
    ("WMT", "0000104169", "Walmart Inc."),
    ("CVX", "0000093410", "Chevron Corporation"),
    ("LLY", "0000059478", "Eli Lilly and Company"),
    ("ADBE", "0000796343", "Adobe Inc."),
    ("ORCL", "0001341439", "Oracle Corporation"),
    ("CMCSA", "0001166691", "Comcast Corporation"),
    ("ACN", "0001281761", "Accenture plc"),
    ("INTC", "0000050863", "Intel Corporation"),
    ("VZ", "0000732712", "Verizon Communications Inc."),
    ("T", "0000732717", "AT&T Inc."),
    ("MCD", "0000063908", "McDonald's Corporation"),
    ("TXN", "0000097476", "Texas Instruments Inc."),
    ("HON", "0000773840", "Honeywell International Inc."),
    ("NEE", "0000753308", "NextEra Energy Inc."),
    ("UPS", "0001090727", "United Parcel Service Inc."),
    ("PM", "0001413329", "Philip Morris International Inc."),
    ("LOW", "0000060667", "Lowe's Companies Inc."),
    ("GS", "0000886982", "The Goldman Sachs Group Inc."),
    ("CAT", "0000018230", "Caterpillar Inc."),
    ("BA", "0000012927", "The Boeing Company"),
    ("AMGN", "0000318154", "Amgen Inc."),
    ("GE", "0000040554", "General Electric Company"),
)

EQUITY = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "PartnersCapital",
)
REVENUE = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
COST = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
PRETAX = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
)
CASH_CHANGE = (
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
    "CashAndCashEquivalentsPeriodIncreaseDecrease",
)
FX_EFFECT = (
    "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "EffectOfExchangeRateOnCashAndCashEquivalents",
)

RELATION_SPECS: tuple[dict[str, Any], ...] = (
    {
        "relation_id": "ASSETS_EQUALS_LIABILITIES_AND_EQUITY",
        "family": "BALANCE_IDENTITY",
        "period_type": "instant",
        "observed": ("Assets",),
        "terms": ((1.0, ("LiabilitiesAndStockholdersEquity",)),),
    },
    {
        "relation_id": "LIABILITIES_AND_EQUITY_COMPONENTS",
        "family": "BALANCE_COMPONENTS",
        "period_type": "instant",
        "observed": ("LiabilitiesAndStockholdersEquity",),
        "terms": ((1.0, ("Liabilities",)), (1.0, EQUITY)),
    },
    {
        "relation_id": "ASSETS_CURRENT_PLUS_NONCURRENT",
        "family": "BALANCE_COMPONENTS",
        "period_type": "instant",
        "observed": ("Assets",),
        "terms": ((1.0, ("AssetsCurrent",)), (1.0, ("AssetsNoncurrent",))),
    },
    {
        "relation_id": "LIABILITIES_CURRENT_PLUS_NONCURRENT",
        "family": "BALANCE_COMPONENTS",
        "period_type": "instant",
        "observed": ("Liabilities",),
        "terms": ((1.0, ("LiabilitiesCurrent",)), (1.0, ("LiabilitiesNoncurrent",))),
    },
    {
        "relation_id": "GROSS_PROFIT_RECONCILIATION",
        "family": "INCOME_STATEMENT",
        "period_type": "duration",
        "observed": ("GrossProfit",),
        "terms": ((1.0, REVENUE), (-1.0, COST)),
    },
    {
        "relation_id": "OPERATING_INCOME_RECONCILIATION",
        "family": "INCOME_STATEMENT",
        "period_type": "duration",
        "observed": ("OperatingIncomeLoss",),
        "terms": ((1.0, ("GrossProfit",)), (-1.0, ("OperatingExpenses",))),
    },
    {
        "relation_id": "NET_INCOME_TAX_RECONCILIATION",
        "family": "INCOME_STATEMENT",
        "period_type": "duration",
        "observed": ("NetIncomeLoss",),
        "terms": ((1.0, PRETAX), (-1.0, ("IncomeTaxExpenseBenefit",))),
    },
    {
        "relation_id": "CASH_CHANGE_WITH_FX",
        "family": "CASH_FLOW",
        "period_type": "duration",
        "observed": (CASH_CHANGE[0],),
        "terms": (
            (1.0, ("NetCashProvidedByUsedInOperatingActivities",)),
            (1.0, ("NetCashProvidedByUsedInInvestingActivities",)),
            (1.0, ("NetCashProvidedByUsedInFinancingActivities",)),
            (1.0, FX_EFFECT),
        ),
    },
    {
        "relation_id": "CASH_CHANGE_WITHOUT_FX",
        "family": "CASH_FLOW",
        "period_type": "duration",
        "observed": (CASH_CHANGE[1],),
        "terms": (
            (1.0, ("NetCashProvidedByUsedInOperatingActivities",)),
            (1.0, ("NetCashProvidedByUsedInInvestingActivities",)),
            (1.0, ("NetCashProvidedByUsedInFinancingActivities",)),
        ),
    },
)


def fetch_companyfacts(cik: str, cache_dir: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"CIK{cik}.json"
    url = SEC_ENDPOINT.format(cik=cik)
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8")), {
                "url": url,
                "cache": "hit",
                "bytes": target.stat().st_size,
            }
        except (OSError, json.JSONDecodeError):
            target.unlink(missing_ok=True)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "identity",
            "Accept": "application/json",
        },
    )
    last_error = "unknown"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
            value = json.loads(raw.decode("utf-8"))
            target.write_bytes(raw)
            time.sleep(0.12)
            return value, {"url": url, "cache": "miss", "bytes": len(raw)}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 + attempt)
    return None, {"url": url, "cache": "miss", "error": last_error}


def _duration_days(start: str, end: str) -> int:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return -1


def _facts(data: Mapping[str, Any], concept: str, accession: str, period_type: str) -> list[dict[str, Any]]:
    concept_node = data.get("facts", {}).get("us-gaap", {}).get(concept, {})
    units = concept_node.get("units", {}) if isinstance(concept_node, Mapping) else {}
    values = units.get("USD", []) if isinstance(units, Mapping) else []
    result: list[dict[str, Any]] = []
    for fact in values if isinstance(values, list) else []:
        if not isinstance(fact, Mapping):
            continue
        if fact.get("accn") != accession or fact.get("form") not in {"10-K", "10-K/A"}:
            continue
        if fact.get("segment"):
            continue
        value = fact.get("val")
        if not isinstance(value, (int, float)):
            continue
        start = str(fact.get("start", ""))
        end = str(fact.get("end", ""))
        if not end:
            continue
        if period_type == "instant":
            if start:
                continue
            context = {"period_type": "instant", "end": end}
        else:
            if not start or _duration_days(start, end) < 250:
                continue
            context = {"period_type": "duration", "start": start, "end": end}
        result.append(
            {
                "concept": concept,
                "value": float(value),
                "context": context,
                "filed": str(fact.get("filed", "")),
                "form": str(fact.get("form", "")),
                "accession": accession,
                "frame": fact.get("frame"),
            }
        )
    return result


def _best_by_context(facts: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for fact in facts:
        key = json.dumps(fact["context"], sort_keys=True, separators=(",", ":"))
        existing = result.get(key)
        rank = (str(fact.get("filed", "")), str(fact.get("form", "")), str(fact.get("frame", "")))
        old_rank = (
            str(existing.get("filed", "")),
            str(existing.get("form", "")),
            str(existing.get("frame", "")),
        ) if existing else ("", "", "")
        if existing is None or rank > old_rank:
            result[key] = dict(fact)
    return result


def _accessions(data: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    found: dict[str, tuple[str, str]] = {}
    us_gaap = data.get("facts", {}).get("us-gaap", {})
    if not isinstance(us_gaap, Mapping):
        return []
    for concept_node in us_gaap.values():
        if not isinstance(concept_node, Mapping):
            continue
        units = concept_node.get("units", {})
        if not isinstance(units, Mapping):
            continue
        for facts in units.values():
            if not isinstance(facts, list):
                continue
            for fact in facts:
                if not isinstance(fact, Mapping) or fact.get("form") not in {"10-K", "10-K/A"}:
                    continue
                accession = str(fact.get("accn", ""))
                if not accession:
                    continue
                candidate = (str(fact.get("filed", "")), str(fact.get("form", "")))
                if candidate > found.get(accession, ("", "")):
                    found[accession] = candidate
    return sorted(
        ((accession, filed, form) for accession, (filed, form) in found.items()),
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )


def _relation_for_spec(
    data: Mapping[str, Any],
    *,
    accession: str,
    spec: Mapping[str, Any],
    company: str,
    ticker: str,
    cik: str,
    sic: str | None,
) -> dict[str, Any] | None:
    option_sets = [tuple(spec["observed"]), *[tuple(options) for _, options in spec["terms"]]]
    source = SEC_ENDPOINT.format(cik=cik)
    for concepts in itertools.product(*option_sets):
        fact_maps = [
            _best_by_context(_facts(data, concept, accession, str(spec["period_type"])))
            for concept in concepts
        ]
        if any(not mapping for mapping in fact_maps):
            continue
        common = set(fact_maps[0])
        for mapping in fact_maps[1:]:
            common &= set(mapping)
        if not common:
            continue
        context_key = max(common, key=lambda key: json.loads(key).get("end", ""))
        chosen = [mapping[context_key] for mapping in fact_maps]

        def wrap(fact: Mapping[str, Any], coefficient: float | None = None) -> dict[str, Any]:
            value = {
                "concept": fact["concept"],
                "value": fact["value"],
                "provenance": {
                    "source": source,
                    "cik": cik,
                    "sic": sic,
                    "concept": fact["concept"],
                    "unit": "USD",
                    "accession": fact["accession"],
                    "filed": fact["filed"],
                    "form": fact["form"],
                    "context": fact["context"],
                    "frame": fact.get("frame"),
                },
            }
            if coefficient is not None:
                value["coefficient"] = coefficient
            return value

        relation = {
            "relation_id": spec["relation_id"],
            "family": spec["family"],
            "company": company,
            "ticker": ticker,
            "cik": cik,
            "sic": sic,
            "accession": accession,
            "context": chosen[0]["context"],
            "observed": wrap(chosen[0]),
            "terms": [
                wrap(fact, float(coefficient))
                for fact, (coefficient, _) in zip(chosen[1:], spec["terms"], strict=True)
            ],
            "adapter": None,
            "selection_rule": "latest accession with at least two valid direct relations; otherwise latest with one",
        }
        relation["relation_uid"] = digest(
            {
                "cik": cik,
                "accession": accession,
                "relation_id": spec["relation_id"],
                "context": relation["context"],
                "concepts": concepts,
            }
        )
        if relation_check(relation, "exact")["passed"]:
            return relation
    return None


def extract_company_relations(
    data: Mapping[str, Any],
    *,
    ticker: str,
    cik: str,
    fallback_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    company = str(data.get("entityName") or fallback_name)
    sic_value = data.get("sic")
    sic = str(sic_value) if sic_value not in (None, "") else None
    candidates: list[tuple[str, str, str, list[dict[str, Any]]]] = []
    for accession, filed, form in _accessions(data)[:8]:
        relations = [
            relation
            for spec in RELATION_SPECS
            if (relation := _relation_for_spec(
                data,
                accession=accession,
                spec=spec,
                company=company,
                ticker=ticker,
                cik=cik,
                sic=sic,
            )) is not None
        ]
        candidates.append((accession, filed, form, relations))
        if len(relations) >= 2:
            break
    selected = next((candidate for candidate in candidates if len(candidate[3]) >= 2), None)
    if selected is None:
        selected = next((candidate for candidate in candidates if candidate[3]), None)
    if selected is None:
        return [], {
            "ticker": ticker,
            "cik": cik,
            "company": company,
            "sic": sic,
            "status": "EXCLUDED_NO_VALID_DIRECT_RELATION",
            "accessions_examined": len(candidates),
        }
    accession, filed, form, relations = selected
    return relations, {
        "ticker": ticker,
        "cik": cik,
        "company": company,
        "sic": sic,
        "status": "ELIGIBLE",
        "accession": accession,
        "filed": filed,
        "form": form,
        "relations": len(relations),
        "relation_ids": sorted(relation["relation_id"] for relation in relations),
    }


def acquire_relations(cache_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    companies: list[dict[str, Any]] = []
    fetches: list[dict[str, Any]] = []
    for ticker, cik, name in UNIVERSE:
        data, fetch = fetch_companyfacts(cik, cache_dir)
        fetches.append({"ticker": ticker, "cik": cik, **fetch})
        if data is None:
            companies.append({
                "ticker": ticker,
                "cik": cik,
                "company": name,
                "status": "FETCH_FAILED",
                "error": fetch.get("error"),
            })
            continue
        company_relations, status = extract_company_relations(
            data,
            ticker=ticker,
            cik=cik,
            fallback_name=name,
        )
        relations.extend(company_relations)
        companies.append(status)
    manifest = {
        "schema": "fin-abs-001b/acquisition/1",
        "official_sec_endpoint_only": True,
        "frozen_company_universe": True,
        "endpoint_template": SEC_ENDPOINT,
        "company_universe_size": len(UNIVERSE),
        "selection_rule": "latest 10-K/10-K/A accession with at least two valid direct relations; otherwise latest with one",
        "relation_specs_frozen": [spec["relation_id"] for spec in RELATION_SPECS],
        "companies": companies,
        "fetches": fetches,
        "raw_cache_in_artifact": False,
        "boundary": (
            "All evaluated monetary values come directly from SEC Company Facts. Raw downloads remain runner-local; "
            "the artifact contains only provenance, relations, benchmark rows, predictions, gates and hashes."
        ),
    }
    return relations, manifest
