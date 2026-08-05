"""Exact, fail-closed semantic checks for high-risk OCR numbers.

This module does not perform OCR and never proposes a replacement. It only
checks a candidate value against independently identified arithmetic and
repeated-value constraints. A conflict requires at least two failing evidence
families; consistency requires at least two passing families and no failures.
Everything else is INSUFFICIENT.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable

_ASCII_DECIMAL = re.compile(r"^[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?$")
_CURRENCY = re.compile(r"(?i)\b(?:HNL|LPS?|L|USD|US|EUR|GBP|JPY|CNY|RMB|MYR|RM)\b")


class ContextStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    CONFLICT = "CONFLICT"
    INSUFFICIENT = "INSUFFICIENT"


class ConstraintStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class NumericField:
    field_id: str
    value: str
    source_id: str

    def __post_init__(self) -> None:
        field_id = str(self.field_id).strip()
        source_id = str(self.source_id).strip()
        if not field_id or not source_id:
            raise ValueError("field_id and source_id must be non-empty")
        parsed = parse_decimal_token(self.value)
        object.__setattr__(self, "field_id", field_id)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "value", format(parsed, "f"))


@dataclass(frozen=True, slots=True)
class LinearConstraint:
    constraint_id: str
    family: str
    terms: tuple[tuple[str, str], ...]
    tolerance: str = "0.001"

    def __post_init__(self) -> None:
        constraint_id = str(self.constraint_id).strip()
        family = str(self.family).strip()
        if not constraint_id or not family:
            raise ValueError("constraint_id and family must be non-empty")
        if len(self.terms) < 2:
            raise ValueError("linear constraints require at least two terms")
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for field_id, coefficient in self.terms:
            field_id = str(field_id).strip()
            if not field_id or field_id in seen:
                raise ValueError("linear term field IDs must be unique and non-empty")
            seen.add(field_id)
            parsed = parse_decimal_token(str(coefficient), allow_currency=False, allow_parentheses=False)
            normalized.append((field_id, format(parsed, "f")))
        tolerance = parse_tolerance(self.tolerance)
        object.__setattr__(self, "constraint_id", constraint_id)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "terms", tuple(sorted(normalized)))
        object.__setattr__(self, "tolerance", format(tolerance, "f"))


@dataclass(frozen=True, slots=True)
class EqualityConstraint:
    constraint_id: str
    family: str
    left_field_id: str
    right_field_id: str
    tolerance: str = "0.001"

    def __post_init__(self) -> None:
        constraint_id = str(self.constraint_id).strip()
        family = str(self.family).strip()
        left = str(self.left_field_id).strip()
        right = str(self.right_field_id).strip()
        if not constraint_id or not family or not left or not right:
            raise ValueError("constraint and field IDs must be non-empty")
        if left == right:
            raise ValueError("equality constraint requires two distinct fields")
        tolerance = parse_tolerance(self.tolerance)
        object.__setattr__(self, "constraint_id", constraint_id)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "left_field_id", left)
        object.__setattr__(self, "right_field_id", right)
        object.__setattr__(self, "tolerance", format(tolerance, "f"))


Constraint = LinearConstraint | EqualityConstraint


@dataclass(frozen=True, slots=True)
class ConstraintOutcome:
    constraint_id: str
    family: str
    status: ConstraintStatus
    residual: str | None
    tolerance: str
    field_ids: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextDecision:
    status: ContextStatus
    reason_code: str
    target_field_id: str
    target_value: str
    available_constraints: int
    passed_families: tuple[str, ...]
    failed_families: tuple[str, ...]
    outcomes: tuple[ConstraintOutcome, ...]
    replacement_value: None
    decision_sha256: str


def parse_decimal_token(
    value: str,
    *,
    allow_currency: bool = True,
    allow_parentheses: bool = True,
) -> Decimal:
    """Parse one unambiguous ASCII decimal with optional thousands commas."""

    text = str(value or "").strip()
    if allow_currency:
        text = _CURRENCY.sub("", text).strip()
    negative_parentheses = False
    if allow_parentheses and text.startswith("(") and text.endswith(")"):
        negative_parentheses = True
        text = text[1:-1].strip()
    if not text or not _ASCII_DECIMAL.fullmatch(text):
        raise ValueError("value is not an unambiguous ASCII decimal token")
    canonical = text.replace(",", "")
    try:
        parsed = Decimal(canonical)
    except InvalidOperation as exc:  # pragma: no cover
        raise ValueError("invalid decimal token") from exc
    if not parsed.is_finite():
        raise ValueError("decimal must be finite")
    if negative_parentheses:
        parsed = -parsed
    return parsed


def parse_tolerance(value: str) -> Decimal:
    parsed = parse_decimal_token(value, allow_currency=False, allow_parentheses=False)
    if parsed < 0:
        raise ValueError("tolerance must be non-negative")
    return parsed


def _evaluate_constraint(
    constraint: Constraint,
    fields: dict[str, NumericField],
) -> ConstraintOutcome:
    if isinstance(constraint, LinearConstraint):
        field_ids = tuple(field_id for field_id, _ in constraint.terms)
    else:
        field_ids = tuple(sorted((constraint.left_field_id, constraint.right_field_id)))
    if any(field_id not in fields for field_id in field_ids):
        return ConstraintOutcome(
            constraint_id=constraint.constraint_id,
            family=constraint.family,
            status=ConstraintStatus.UNAVAILABLE,
            residual=None,
            tolerance=constraint.tolerance,
            field_ids=field_ids,
            source_ids=tuple(sorted(fields[field_id].source_id for field_id in field_ids if field_id in fields)),
        )

    if isinstance(constraint, LinearConstraint):
        residual = sum(
            (Decimal(coefficient) * Decimal(fields[field_id].value) for field_id, coefficient in constraint.terms),
            Decimal("0"),
        )
    else:
        residual = Decimal(fields[constraint.left_field_id].value) - Decimal(fields[constraint.right_field_id].value)
    tolerance = Decimal(constraint.tolerance)
    status = ConstraintStatus.PASS if abs(residual) <= tolerance else ConstraintStatus.FAIL
    return ConstraintOutcome(
        constraint_id=constraint.constraint_id,
        family=constraint.family,
        status=status,
        residual=format(residual, "f"),
        tolerance=constraint.tolerance,
        field_ids=field_ids,
        source_ids=tuple(sorted({fields[field_id].source_id for field_id in field_ids})),
    )


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_numeric_context(
    target_field_id: str,
    fields: Iterable[NumericField],
    constraints: Iterable[Constraint],
    *,
    minimum_independent_families: int = 2,
) -> ContextDecision:
    """Evaluate context without deriving or returning an automatic replacement."""

    target_field_id = str(target_field_id).strip()
    if not target_field_id:
        raise ValueError("target_field_id must be non-empty")
    if minimum_independent_families < 2:
        raise ValueError("at least two independent families are required")
    field_rows = sorted(list(fields), key=lambda row: row.field_id)
    constraint_rows = sorted(list(constraints), key=lambda row: row.constraint_id)
    field_ids = [row.field_id for row in field_rows]
    constraint_ids = [row.constraint_id for row in constraint_rows]
    if len(field_ids) != len(set(field_ids)):
        raise ValueError("field IDs must be unique")
    if len(constraint_ids) != len(set(constraint_ids)):
        raise ValueError("constraint IDs must be unique")
    field_map = {row.field_id: row for row in field_rows}
    if target_field_id not in field_map:
        raise ValueError("target field is missing")

    relevant = [
        constraint
        for constraint in constraint_rows
        if (
            target_field_id in {field_id for field_id, _ in constraint.terms}
            if isinstance(constraint, LinearConstraint)
            else target_field_id in {constraint.left_field_id, constraint.right_field_id}
        )
    ]
    outcomes = tuple(_evaluate_constraint(constraint, field_map) for constraint in relevant)
    available = tuple(row for row in outcomes if row.status != ConstraintStatus.UNAVAILABLE)
    passed_families = tuple(sorted({row.family for row in available if row.status == ConstraintStatus.PASS}))
    failed_families = tuple(sorted({row.family for row in available if row.status == ConstraintStatus.FAIL}))

    if len(failed_families) >= minimum_independent_families and not passed_families:
        status = ContextStatus.CONFLICT
        reason = "INDEPENDENT_CONTEXT_CONFLICT"
    elif len(passed_families) >= minimum_independent_families and not failed_families:
        status = ContextStatus.CONSISTENT
        reason = "INDEPENDENT_CONTEXT_CONSISTENCY"
    elif passed_families and failed_families:
        status = ContextStatus.INSUFFICIENT
        reason = "MIXED_CONTEXT_EVIDENCE"
    else:
        status = ContextStatus.INSUFFICIENT
        reason = "INSUFFICIENT_INDEPENDENT_FAMILIES"

    payload = {
        "schema": "ocr-numeric-context-v4-decision/1",
        "status": status.value,
        "reason_code": reason,
        "target_field_id": target_field_id,
        "target_value": field_map[target_field_id].value,
        "available_constraints": len(available),
        "passed_families": passed_families,
        "failed_families": failed_families,
        "outcomes": [
            {
                **asdict(row),
                "status": row.status.value,
            }
            for row in outcomes
        ],
        "minimum_independent_families": minimum_independent_families,
    }
    return ContextDecision(
        status=status,
        reason_code=reason,
        target_field_id=target_field_id,
        target_value=field_map[target_field_id].value,
        available_constraints=len(available),
        passed_families=passed_families,
        failed_families=failed_families,
        outcomes=outcomes,
        replacement_value=None,
        decision_sha256=_hash_payload(payload),
    )
