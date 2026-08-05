from __future__ import annotations

import importlib.util
import math
import re
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

_BASE_PATH = Path(__file__).with_name("usaspending_v2_engine.py")
if not _BASE_PATH.is_file():
    raise RuntimeError(f"missing frozen V2 base engine: {_BASE_PATH}")
_spec = importlib.util.spec_from_file_location("frozen_usaspending_v2", _BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("cannot load frozen V2 base engine")
_base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _base
_spec.loader.exec_module(_base)

for _name in dir(_base):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(_base, _name))

_V3_RECIPIENTS: tuple[Any, ...] = ()


def load_domain(dab_root: Path, needs_descriptions: bool = False):
    domain = _base.load_domain(dab_root, needs_descriptions=needs_descriptions)
    dataset = Path(dab_root) / "query_usaspending" / "query_dataset"
    _, _, recipients = _base._load_references(dataset)
    global _V3_RECIPIENTS
    _V3_RECIPIENTS = tuple(recipients)
    return domain


def plan_query(query: str, agency_catalog: Mapping[str, str], naics_sectors: Sequence[Any], recipient_names: Sequence[str]):
    return _base.plan_query(query, agency_catalog, naics_sectors, recipient_names)


def _query_text(plan: Any) -> str:
    return _base.fold_text(getattr(plan, "raw_query", "")).lower()


def _without_spurious_naics(plan: Any):
    try:
        return replace(plan, naics_prefix=None)
    except TypeError:
        return plan


def _naics_width(query: str) -> int | None:
    match = re.search(r"\b([2-6])\s*[- ]?digit\s+naics\s+(?:sector|code)s?\b", query)
    return int(match.group(1)) if match else None


def _sector_rows(plan: Any, awards: Sequence[Any]) -> list[Any]:
    return list(_base.filter_awards(_without_spurious_naics(plan), awards))


def _sector_code(award: Any, width: int) -> str | None:
    code = _base.canonical_naics(getattr(award, "naics_code", ""))
    return code[:width] if len(code) >= width else None


def _sector_groups(plan: Any, awards: Sequence[Any], width: int) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = {}
    for award in _sector_rows(plan, awards):
        code = _sector_code(award, width)
        if code:
            groups.setdefault(code, []).append(award)
    return groups


def _metric_for_group(query: str, rows: Sequence[Any]) -> float:
    amounts = [float(row.amount) for row in rows if getattr(row, "amount", None) is not None and math.isfinite(float(row.amount))]
    if re.search(r"\b(?:average|mean)\b", query):
        return float(statistics.fmean(amounts)) if amounts else 0.0
    if re.search(r"\b(?:total amount|total value|total spending|sum|dollars?|funding)\b", query):
        return float(sum(amounts))
    if re.search(r"\b(?:distinct|unique)\s+(?:recipients?|vendors?|contractors?)\b", query):
        return float(len({
            _base.canonical_recipient_name(getattr(row, "recipient_name", "")) or getattr(row, "recipient_key", "")
            for row in rows
            if getattr(row, "recipient_name", "") or getattr(row, "recipient_key", "")
        }))
    return float(len({getattr(row, "entity_id", id(row)) for row in rows}))


def _naics_answer(plan: Any, awards: Sequence[Any], width: int):
    query = _query_text(plan)
    groups = _sector_groups(plan, awards, width)
    if re.search(r"\bhow many\b", query) and re.search(r"\b(?:distinct|unique)\b", query):
        return len(groups)
    if re.search(r"\b(?:list|show|identify)\b", query) and not re.search(r"\b(?:most|highest|largest|least|lowest|smallest|top)\b", query):
        return sorted(groups)
    scored = [(code, _metric_for_group(query, rows)) for code, rows in groups.items()]
    if not scored:
        return ""
    minimize = bool(re.search(r"\b(?:fewest|least|lowest|smallest|minimum)\b", query))
    target = min(value for _, value in scored) if minimize else max(value for _, value in scored)
    tied = sorted(code for code, value in scored if math.isclose(value, target, rel_tol=1e-12, abs_tol=1e-9))
    top_match = re.search(r"\btop\s+(\d+)\b", query)
    if top_match:
        count = int(top_match.group(1))
        ordered = sorted(scored, key=lambda item: (item[1], item[0]) if minimize else (-item[1], item[0]))[:count]
        return [_base.RankedAnswer(code, value, True) for code, value in ordered]
    return tied[0] if len(tied) == 1 else tuple(tied)


def _recipient_registry_groups() -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = {}
    for row in _V3_RECIPIENTS:
        name = _base.canonical_recipient_name(getattr(row, "name", ""))
        if name:
            groups.setdefault(name, []).append(row)
    return groups


def _recipient_multi_uei_answer(plan: Any):
    query = _query_text(plan)
    qualifying: list[tuple[str, int]] = []
    for _, rows in _recipient_registry_groups().items():
        ueis = {
            _base.identifier_key(getattr(row, "raw_uei", "")) or getattr(row, "entity_id", "")
            for row in rows
        }
        ueis.discard("")
        if len(ueis) > 1:
            display = max((_base.fold_text(getattr(row, "name", "")) for row in rows), key=lambda value: (len(value), value))
            qualifying.append((display, len(ueis)))
    qualifying.sort(key=lambda item: item[0].casefold())
    if re.search(r"\bhow many\b", query):
        return len(qualifying)
    if re.search(r"\b(?:which|who)\b", query) and re.search(r"\b(?:most|highest|largest)\b", query):
        if not qualifying:
            return ""
        target = max(count for _, count in qualifying)
        tied = sorted(name for name, count in qualifying if count == target)
        return tied[0] if len(tied) == 1 else tuple(tied)
    return [name for name, _ in qualifying]


def evaluate(plan: Any, awards: Sequence[Any]):
    query = _query_text(plan)
    width = _naics_width(query)
    if width is not None:
        return _naics_answer(plan, awards, width)
    if re.search(r"\bmore than one\s+uei\b|\bmultiple\s+ueis?\b", query):
        return _recipient_multi_uei_answer(plan)
    return _base.evaluate(plan, awards)


read_query = _base.read_query
write_outputs = _base.write_outputs
render_answer = _base.render_answer
