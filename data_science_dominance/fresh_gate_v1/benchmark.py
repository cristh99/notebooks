"""Deterministic internal benchmark for entity resolution and temporal extraction.

This harness contains no DataAgentBench query, answer, validator, or dataset
value. Its purpose is to measure precision, recall, quarantine, and temporal
semantics before an external candidate is frozen.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
from typing import Iterable

from .entity_resolution import Entity, ResolutionStatus, resolve_entities
from .record_extraction import (
    FundingEntry,
    ProjectRecord,
    select_projects,
)


_OCR = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
_LABELS = (
    "Award No. ",
    "contract:",
    "PIID/",
    "reference=",
    "Document: ",
    "award_id:",
)
_SEPARATORS = ("", "-", "_", ".", " ")


@dataclass(frozen=True, slots=True)
class ResolutionMetrics:
    population: int
    true_positive: int
    false_positive: int
    false_negative: int
    ambiguous: int
    unmatched: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class BenchmarkReceipt:
    schema: str
    clean_resolution: ResolutionMetrics
    adversarial_ambiguities: int
    adversarial_quarantined: int
    adversarial_quarantine_rate: float
    temporal_projects_expected: int
    temporal_projects_selected: int
    temporal_exact: bool
    verdict: str


def _surface(canonical: str, index: int, side: str) -> str:
    text = canonical.translate(_OCR) if side == "right" else canonical
    separator = _SEPARATORS[(index + (1 if side == "right" else 0)) % len(_SEPARATORS)]
    if separator:
        split = [text[:2], text[2:5], text[5:8], text[8:]]
        text = separator.join(part for part in split if part)
    if (index + len(side)) % 3 == 0:
        text = text.lower()
    elif (index + len(side)) % 3 == 1:
        text = text.upper()
    return _LABELS[(index * 3 + len(side)) % len(_LABELS)] + text


def _metrics(expected: dict[str, str], resolutions: Iterable) -> ResolutionMetrics:
    accepted = {
        resolution.left_key: resolution.right_key
        for resolution in resolutions
        if resolution.right_key is not None
        and resolution.status in {ResolutionStatus.EXACT, ResolutionStatus.MATCHED}
    }
    true_positive = sum(accepted.get(left) == right for left, right in expected.items())
    false_positive = sum(
        1 for left, right in accepted.items() if expected.get(left) != right
    )
    false_negative = len(expected) - true_positive
    ambiguous = sum(
        resolution.status == ResolutionStatus.AMBIGUOUS for resolution in resolutions
    )
    unmatched = sum(
        resolution.status == ResolutionStatus.UNMATCHED for resolution in resolutions
    )
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ResolutionMetrics(
        population=len(expected),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        ambiguous=ambiguous,
        unmatched=unmatched,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def run_benchmark(population: int = 2_000) -> BenchmarkReceipt:
    if population < 100:
        raise ValueError("population must be at least 100")

    left: list[Entity] = []
    right: list[Entity] = []
    expected: dict[str, str] = {}
    for index in range(population):
        canonical = f"ZX{index:07d}Q"
        left_key = f"L{index:07d}"
        right_key = f"R{index:07d}"
        left.append(Entity(left_key, _surface(canonical, index, "left")))
        right.append(Entity(right_key, _surface(canonical, index, "right")))
        expected[left_key] = right_key

    clean_batch = resolve_entities(left, right)
    clean_metrics = _metrics(expected, clean_batch.resolutions)

    adversarial_left: list[Entity] = []
    adversarial_right: list[Entity] = []
    ambiguity_count = max(20, population // 50)
    for index in range(ambiguity_count):
        canonical = f"AB{index:04d}1200"
        adversarial_left.append(Entity(f"AL{index:04d}", canonical))
        adversarial_right.extend(
            [
                Entity(f"AR{index:04d}A", canonical[:-1] + "O"),
                Entity(f"AR{index:04d}B", canonical[:-4] + "I200"),
            ]
        )
    adversarial = resolve_entities(adversarial_left, adversarial_right)
    quarantined = sum(
        resolution.status == ResolutionStatus.AMBIGUOUS
        for resolution in adversarial.resolutions
    )

    project_count = max(100, population // 10)
    records: list[ProjectRecord] = []
    funding: list[FundingEntry] = []
    expected_projects: set[str] = set()
    cutoff = date(2023, 1, 1)
    for index in range(project_count):
        name = f"Capital Project {index:05d}"
        expected_projects.add(name.upper())
        records.extend(
            [
                ProjectRecord(name, date(2022, 6, 1), "capital", "not started", "report-a", index * 2),
                ProjectRecord(name, date(2022, 12, 1), "capital", "design", "report-b", index * 2 + 1),
                ProjectRecord(name, date(2023, 2, 1), "capital", "completed", "future", index * 2 + 2),
            ]
        )
        funding.extend(
            [
                FundingEntry(name, date(2022, 4, 1), 300_000.0, "fund-a"),
                FundingEntry(name, date(2022, 11, 1), 250_000.0, "fund-b"),
                FundingEntry(name, date(2023, 3, 1), 9_000_000.0, "future"),
            ]
        )
    selected = select_projects(
        records,
        funding,
        cutoff=cutoff,
        project_type="capital",
        status="design",
        minimum_funding=500_000.0,
    )
    selected_names = {item.canonical_name for item in selected}
    temporal_exact = selected_names == expected_projects and all(
        item.accumulated_funding == 550_000.0 for item in selected
    )

    quarantine_rate = quarantined / ambiguity_count if ambiguity_count else 1.0
    verdict = "PASS" if (
        clean_metrics.precision == 1.0
        and clean_metrics.recall == 1.0
        and clean_metrics.false_positive == 0
        and quarantine_rate == 1.0
        and temporal_exact
    ) else "FAIL"
    return BenchmarkReceipt(
        schema="data-science-dominance/fresh-gate-v1-internal-benchmark/1",
        clean_resolution=clean_metrics,
        adversarial_ambiguities=ambiguity_count,
        adversarial_quarantined=quarantined,
        adversarial_quarantine_rate=quarantine_rate,
        temporal_projects_expected=project_count,
        temporal_projects_selected=len(selected),
        temporal_exact=temporal_exact,
        verdict=verdict,
    )


def write_receipt(path: str | Path, population: int = 2_000) -> BenchmarkReceipt:
    receipt = run_benchmark(population=population)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n")
    return receipt


if __name__ == "__main__":
    receipt = write_receipt("fresh-gate-v1-benchmark.json")
    print(json.dumps(asdict(receipt), indent=2, sort_keys=True))
    raise SystemExit(0 if receipt.verdict == "PASS" else 1)
