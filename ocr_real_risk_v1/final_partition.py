"""Process-level partitioning for an untouched final OCR holdout.

Document-level hashing is insufficient because multiple PDFs from one
procurement process can share templates, identifiers and image characteristics.
This module assigns the *entire process* to one partition and chooses at most
one document from each process before any OCR result is observed.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

from .core import Candidate, sha256_bytes


SCHEMA = "ocr-real-risk-process-partition/1"
CANARY_PARTITIONS = frozenset(range(0, 10))
FINAL_PARTITIONS = frozenset(range(10, 100))


@dataclass(frozen=True)
class FrozenCandidate:
    url: str
    document_type: str
    process: str
    ocid: str
    institution_code: str
    source_line: int
    document_key: str
    process_key: str
    partition: int


def process_identity(candidate: Candidate) -> str:
    value = candidate.ocid.strip() or candidate.process.strip() or candidate.url
    return value


def process_key(candidate: Candidate) -> str:
    return hashlib.sha256(process_identity(candidate).encode("utf-8")).hexdigest()


def process_partition(candidate: Candidate) -> int:
    return int(process_key(candidate)[:16], 16) % 100


def choose_one_document_per_process(
    candidates: Sequence[Candidate],
) -> list[Candidate]:
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        groups[process_key(candidate)].append(candidate)
    selected: list[Candidate] = []
    for key in sorted(groups):
        # The chosen document is fixed only by declared metadata and URL hash;
        # neither OCR output nor native truth participates.
        selected.append(
            min(
                groups[key],
                key=lambda item: (
                    sha256_bytes(item.url.encode("utf-8")),
                    item.document_type,
                    item.url,
                ),
            )
        )
    return selected


def _round_robin_by_institution(
    candidates: Iterable[Candidate],
) -> list[Candidate]:
    groups: dict[str, deque[Candidate]] = defaultdict(deque)
    for candidate in sorted(
        candidates,
        key=lambda item: (
            process_key(item),
            sha256_bytes(item.url.encode("utf-8")),
        ),
    ):
        groups[candidate.institution_code].append(candidate)
    institutions = sorted(groups, key=lambda key: (len(groups[key]), key), reverse=True)
    ordered: list[Candidate] = []
    while any(groups.values()):
        for institution in institutions:
            if groups[institution]:
                ordered.append(groups[institution].popleft())
    return ordered


def freeze_partition(
    candidates: Sequence[Candidate],
    *,
    partitions: frozenset[int],
    limit: int | None = None,
) -> dict[str, object]:
    if not partitions or any(value < 0 or value > 99 for value in partitions):
        raise ValueError("partitions must be a non-empty subset of 0..99")
    one_per_process = choose_one_document_per_process(candidates)
    eligible = [
        candidate
        for candidate in one_per_process
        if process_partition(candidate) in partitions
    ]
    ordered = _round_robin_by_institution(eligible)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        ordered = ordered[:limit]
    frozen = [
        FrozenCandidate(
            url=candidate.url,
            document_type=candidate.document_type,
            process=candidate.process,
            ocid=candidate.ocid,
            institution_code=candidate.institution_code,
            source_line=candidate.source_line,
            document_key=candidate.key,
            process_key=process_key(candidate),
            partition=process_partition(candidate),
        )
        for candidate in ordered
    ]
    process_keys = [item.process_key for item in frozen]
    if len(process_keys) != len(set(process_keys)):
        raise AssertionError("process identity leaked within frozen partition")
    return {
        "schema": SCHEMA,
        "partitions": sorted(partitions),
        "selection_before_ocr": True,
        "unit": "one deterministically chosen document per procurement process",
        "candidate_processes": len(one_per_process),
        "eligible_processes": len(eligible),
        "selected_processes": len(frozen),
        "institution_counts": dict(
            sorted(Counter(item.institution_code for item in frozen).items())
        ),
        "document_type_counts": dict(
            sorted(Counter(item.document_type for item in frozen).items())
        ),
        "records": [asdict(item) for item in frozen],
    }


def assert_disjoint(
    first: dict[str, object],
    second: dict[str, object],
) -> None:
    first_records = first.get("records") or []
    second_records = second.get("records") or []
    first_keys = {str(record["process_key"]) for record in first_records}
    second_keys = {str(record["process_key"]) for record in second_records}
    overlap = sorted(first_keys & second_keys)
    if overlap:
        raise AssertionError(f"process leakage across partitions: {overlap[:5]}")
