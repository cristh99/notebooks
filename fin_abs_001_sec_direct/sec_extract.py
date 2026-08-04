from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from .constants import DURATION_CONCEPTS, INSTANT_CONCEPTS, SEC_BASE
from .policy import freeze_case_relations, is_number, predict


def _date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _facts(
    companyfacts: Mapping[str, Any],
    concept: str,
) -> list[dict[str, Any]]:
    node = companyfacts.get("facts", {}).get("us-gaap", {}).get(concept, {})
    units = node.get("units", {}) if isinstance(node, Mapping) else {}
    values = units.get("USD", []) if isinstance(units, Mapping) else []
    return [
        dict(item)
        for item in values
        if isinstance(item, Mapping)
    ]


def _annual_fact(item: Mapping[str, Any]) -> bool:
    return (
        item.get("form") in {"10-K", "10-K/A"}
        and bool(item.get("accn"))
        and bool(item.get("end"))
        and bool(item.get("filed"))
        and is_number(item.get("val"))
    )


def _candidate_accessions(
    companyfacts: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    candidates: set[tuple[str, str, str]] = set()
    for concept in INSTANT_CONCEPTS["assets"]:
        for item in _facts(companyfacts, concept):
            if _annual_fact(item) and not item.get("start"):
                candidates.add(
                    (
                        str(item["accn"]),
                        str(item["end"]),
                        str(item["filed"]),
                    )
                )
    return sorted(
        candidates,
        key=lambda value: (value[2], value[1], value[0]),
        reverse=True,
    )


def _pick_instant(
    companyfacts: Mapping[str, Any],
    concepts: Sequence[str],
    accn: str,
    end: str,
) -> dict[str, Any] | None:
    for priority, concept in enumerate(concepts):
        candidates = [
            item
            for item in _facts(companyfacts, concept)
            if _annual_fact(item)
            and str(item.get("accn")) == accn
            and str(item.get("end")) == end
            and not item.get("start")
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: str(item.get("filed", "")),
            reverse=True,
        )
        item = candidates[0]
        return {
            "value": float(item["val"]),
            "concept": concept,
            "priority": priority,
            "accn": accn,
            "start": None,
            "end": end,
            "filed": str(item["filed"]),
            "form": str(item["form"]),
        }
    return None


def _pick_prior_instant(
    companyfacts: Mapping[str, Any],
    concepts: Sequence[str],
    accn: str,
    report_end: str,
    required_concept: str | None = None,
) -> dict[str, Any] | None:
    report_date = _date(report_end)
    concept_order = tuple(
        concept
        for concept in concepts
        if required_concept is None or concept == required_concept
    )
    for priority, concept in enumerate(concept_order):
        candidates: list[tuple[int, dict[str, Any]]] = []
        for item in _facts(companyfacts, concept):
            if (
                not _annual_fact(item)
                or item.get("start")
                or str(item.get("accn")) != accn
            ):
                continue
            end = str(item["end"])
            if end == report_end:
                continue
            delta = (report_date - _date(end)).days
            if 300 <= delta <= 430:
                candidates.append((abs(delta - 365), item))
        if not candidates:
            continue
        candidates.sort(
            key=lambda pair: (
                pair[0],
                str(pair[1].get("filed", "")),
            )
        )
        item = candidates[0][1]
        return {
            "value": float(item["val"]),
            "concept": concept,
            "priority": priority,
            "accn": accn,
            "start": None,
            "end": str(item["end"]),
            "filed": str(item["filed"]),
            "form": str(item["form"]),
        }
    return None


def _pick_duration(
    companyfacts: Mapping[str, Any],
    concepts: Sequence[str],
    accn: str,
    end: str,
) -> dict[str, Any] | None:
    for priority, concept in enumerate(concepts):
        candidates: list[tuple[int, dict[str, Any]]] = []
        for item in _facts(companyfacts, concept):
            if (
                not _annual_fact(item)
                or str(item.get("accn")) != accn
                or str(item.get("end")) != end
            ):
                continue
            start = item.get("start")
            if not start:
                continue
            span = (_date(end) - _date(str(start))).days
            if 280 <= span <= 400:
                candidates.append((abs(span - 365), item))
        if not candidates:
            continue
        candidates.sort(
            key=lambda pair: (
                pair[0],
                str(pair[1].get("filed", "")),
            )
        )
        item = candidates[0][1]
        return {
            "value": float(item["val"]),
            "concept": concept,
            "priority": priority,
            "accn": accn,
            "start": str(item["start"]),
            "end": end,
            "filed": str(item["filed"]),
            "form": str(item["form"]),
        }
    return None


def extract_case(
    companyfacts: Mapping[str, Any],
    company: Mapping[str, str],
) -> dict[str, Any] | None:
    best: tuple[int, str, dict[str, Any]] | None = None
    for accn, report_end, filed in _candidate_accessions(companyfacts)[:8]:
        provenance: dict[str, Any] = {}
        values: dict[str, float] = {}

        for key, concepts in INSTANT_CONCEPTS.items():
            fact = _pick_instant(
                companyfacts,
                concepts,
                accn,
                report_end,
            )
            if fact is not None:
                values[key] = fact["value"]
                provenance[key] = fact

        for key, concepts in DURATION_CONCEPTS.items():
            fact = _pick_duration(
                companyfacts,
                concepts,
                accn,
                report_end,
            )
            if fact is not None:
                values[key] = fact["value"]
                provenance[key] = fact

        cash = provenance.get("cash")
        cash_concept = (
            cash.get("concept")
            if isinstance(cash, Mapping)
            else None
        )
        prior_cash = _pick_prior_instant(
            companyfacts,
            INSTANT_CONCEPTS["cash"],
            accn,
            report_end,
            required_concept=(
                str(cash_concept)
                if cash_concept
                else None
            ),
        )
        if prior_cash is not None:
            values["prior_cash"] = prior_cash["value"]
            provenance["prior_cash"] = prior_cash

        case = {
            "schema": "fin-abs-001b/sec-direct-case/1",
            "ticker": company["ticker"],
            "name": companyfacts.get("entityName") or company["name"],
            "cik": company["cik"],
            "sic": str(companyfacts.get("sic", "")),
            "sic_description": str(
                companyfacts.get("sicDescription", "")
            ),
            "accession": accn,
            "filed": filed,
            "report_end": report_end,
            "values": values,
            "provenance": provenance,
            "source_url": SEC_BASE.format(cik=company["cik"]),
        }
        frozen = freeze_case_relations(case)
        if frozen is None:
            continue
        relation_count = predict(frozen)["relation_count"]
        candidate = (relation_count, filed, frozen)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    return best[2] if best is not None else None
