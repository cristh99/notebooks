"""Outcome-blind semantic rival detection for numeric OCR v4.2.

The detector does not read annotations or pixels. It receives the baseline OCR
stream with line geometry and emits at most one same-length, one-digit rival per
flagged token. Multiple incompatible rivals are preserved as an ambiguous flag
so downstream policy can quarantine rather than choose one.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

_ASCII_DIGITS = re.compile(r"[0-9]")
_AMOUNT = re.compile(r"^[+-]?[0-9]{1,6}([.,])([0-9]{1,2})$")
_QTY_ONE = re.compile(r"^1(?:[Xx])?$")


class SemanticRivalReason(str, Enum):
    NEAR_DUPLICATE_DOCUMENT_MAJORITY = "NEAR_DUPLICATE_DOCUMENT_MAJORITY"
    QTY1_UNIT_AMOUNT_DISAGREEMENT = "QTY1_UNIT_AMOUNT_DISAGREEMENT"
    AMBIGUOUS_SEMANTIC_RIVALS = "AMBIGUOUS_SEMANTIC_RIVALS"


@dataclass(frozen=True, slots=True)
class SemanticOCRToken:
    index: int
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    block: int
    paragraph: int
    line: int

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be non-negative")
        if len(self.bbox) != 4 or self.bbox[2] <= self.bbox[0] or self.bbox[3] <= self.bbox[1]:
            raise ValueError("bbox must be non-empty")
        if not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite")

    @property
    def digits(self) -> str:
        return canonical_ascii_digits(self.text)

    @property
    def line_key(self) -> tuple[int, int, int]:
        return self.block, self.paragraph, self.line

    @property
    def center_x(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0


@dataclass(frozen=True, slots=True)
class SemanticRivalFlag:
    token_index: int
    baseline_digits: str
    rival_digits: str | None
    all_rivals: tuple[str, ...]
    reasons: tuple[SemanticRivalReason, ...]

    @property
    def ambiguous(self) -> bool:
        return self.rival_digits is None


def canonical_ascii_digits(value: object) -> str:
    return "".join(_ASCII_DIGITS.findall(str(value or "")))


def decimal_signature(value: object) -> tuple[int, int] | None:
    match = _AMOUNT.fullmatch(str(value or "").strip().strip("*"))
    if match is None:
        return None
    digits = canonical_ascii_digits(match.group(0))
    return len(digits), len(match.group(2))


def hamming_one(first: str, second: str) -> bool:
    return len(first) == len(second) and sum(a != b for a, b in zip(first, second)) == 1


def detect_semantic_rivals(tokens: Sequence[SemanticOCRToken]) -> tuple[SemanticRivalFlag, ...]:
    """Return semantic contradiction flags and their unique one-digit rivals."""

    by_index: dict[int, SemanticOCRToken] = {}
    for token in tokens:
        if token.index in by_index:
            raise ValueError("token indices must be unique")
        by_index[token.index] = token

    candidates: dict[int, dict[str, set[SemanticRivalReason]]] = defaultdict(
        lambda: defaultdict(set)
    )
    amounts = [
        token
        for token in tokens
        if decimal_signature(token.text) is not None and 4 <= len(token.digits) <= 8
    ]
    counts = Counter(token.digits for token in amounts)
    distinct_lines: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
    signatures: dict[str, tuple[int, int]] = {}
    for token in amounts:
        distinct_lines[token.digits].add(token.line_key)
        signature = decimal_signature(token.text)
        assert signature is not None
        signatures[token.digits] = signature

    for token in amounts:
        if counts[token.digits] != 1:
            continue
        signature = decimal_signature(token.text)
        for rival, count in counts.items():
            if (
                count >= 2
                and len(distinct_lines[rival]) >= 2
                and signatures.get(rival) == signature
                and hamming_one(token.digits, rival)
            ):
                candidates[token.index][rival].add(
                    SemanticRivalReason.NEAR_DUPLICATE_DOCUMENT_MAJORITY
                )

    lines: dict[tuple[int, int, int], list[SemanticOCRToken]] = defaultdict(list)
    for token in tokens:
        lines[token.line_key].append(token)
    for line_tokens in lines.values():
        ordered = sorted(line_tokens, key=lambda token: token.center_x)
        quantity_one = any(_QTY_ONE.fullmatch(token.text.strip()) for token in ordered)
        line_amounts = [
            token for token in ordered if decimal_signature(token.text) is not None
        ]
        if not quantity_one or len(line_amounts) != 2:
            continue
        left, right = line_amounts
        if decimal_signature(left.text) != decimal_signature(right.text):
            continue
        if not hamming_one(left.digits, right.digits):
            continue
        implicated, rival = (
            (left, right)
            if left.confidence < right.confidence
            else (right, left)
            if right.confidence < left.confidence
            else (max((left, right), key=lambda token: token.center_x),
                  min((left, right), key=lambda token: token.center_x))
        )
        candidates[implicated.index][rival.digits].add(
            SemanticRivalReason.QTY1_UNIT_AMOUNT_DISAGREEMENT
        )

    output: list[SemanticRivalFlag] = []
    for token_index, rivals in sorted(candidates.items()):
        token = by_index[token_index]
        ordered_rivals = tuple(sorted(rivals))
        reasons = {
            reason for rival_reasons in rivals.values() for reason in rival_reasons
        }
        if len(ordered_rivals) == 1:
            rival_digits: str | None = ordered_rivals[0]
        else:
            rival_digits = None
            reasons.add(SemanticRivalReason.AMBIGUOUS_SEMANTIC_RIVALS)
        output.append(
            SemanticRivalFlag(
                token_index=token_index,
                baseline_digits=token.digits,
                rival_digits=rival_digits,
                all_rivals=ordered_rivals,
                reasons=tuple(sorted(reasons, key=lambda reason: reason.value)),
            )
        )
    return tuple(output)
