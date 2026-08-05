"""Auditable entity resolution for noisy cross-database identifiers.

The module is deliberately deterministic and domain-agnostic. It never reads
benchmark validators, ground truth, network resources, or process state.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
import math
import re
import unicodedata
from typing import Iterable, Mapping, Sequence


# Characters within one set may be OCR confusions. The canonical representative
# is used only in the tolerant signature; the conservative signature keeps them
# distinct to reduce false merges.
_OCR_GROUPS = (
    frozenset("0OQ"),
    frozenset("1IL"),
    frozenset("2Z"),
    frozenset("5S"),
    frozenset("6G"),
    frozenset("8B"),
)
_OCR_CANONICAL = {
    character: representative
    for representative, group in zip("012568", _OCR_GROUPS, strict=True)
    for character in group
}

_LABEL_RE = re.compile(
    r"^\s*(?:(?:award|contract|order|document|reference|record|transaction|"
    r"obligation|solicitation|procurement|purchase|agreement|instrument|"
    r"requisition|authorization|modification|delivery|task|grant|cooperative|"
    r"piid|piin|acq|ref|id|no|doc|file|rec|txn|obl|oblig|po|to|do|mod|sol|"
    r"proc|purch|inst|agr|grt|acrn|clin|slin|pr|wbs|cage|uei)"
    r"(?:[_\s-]*(?:id|no|number))?\s*(?:[:=#/._-]|no\.?\s*)+)+",
    re.IGNORECASE,
)
_SUPERSEDED_RE = re.compile(r"(?:[_\s.-]+OLD)\s*$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_TOKEN_RE = re.compile(r"[A-Z]+|\d+")


def _ascii_upper(value: object) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    return text.upper().strip()


def strip_surface_label(value: object) -> str:
    """Remove repeated metadata labels while preserving the identifier body."""
    text = _ascii_upper(value)
    previous = None
    while text and text != previous:
        previous = text
        text = _LABEL_RE.sub("", text).strip()
    return text


def is_superseded(value: object) -> bool:
    return bool(_SUPERSEDED_RE.search(strip_surface_label(value)))


def conservative_signature(value: object, *, drop_superseded_suffix: bool = False) -> str:
    """Loss-minimizing signature: labels/separators/case are removed, OCR is not."""
    text = strip_surface_label(value)
    if drop_superseded_suffix:
        text = _SUPERSEDED_RE.sub("", text)
    return _NON_ALNUM_RE.sub("", text)


def ocr_signature(value: object, *, drop_superseded_suffix: bool = False) -> str:
    """Recall-oriented signature with visual OCR equivalents folded together."""
    conservative = conservative_signature(
        value, drop_superseded_suffix=drop_superseded_suffix
    )
    return "".join(_OCR_CANONICAL.get(character, character) for character in conservative)


def token_signature(value: object) -> tuple[str, ...]:
    """Ordered alpha/numeric runs after label removal."""
    return tuple(_TOKEN_RE.findall(strip_surface_label(value)))


def digit_signature(value: object) -> str:
    """Digits after OCR folding, useful as a high-recall blocking signal."""
    return "".join(character for character in ocr_signature(value) if character.isdigit())


def _same_ocr_group(left: str, right: str) -> bool:
    return any(left in group and right in group for group in _OCR_GROUPS)


def weighted_damerau_levenshtein(left: str, right: str) -> float:
    """Edit distance with low-cost OCR substitutions and adjacent transposition."""
    if left == right:
        return 0.0
    if not left:
        return float(len(right))
    if not right:
        return float(len(left))

    previous_previous: list[float] | None = None
    previous = [float(index) for index in range(len(right) + 1)]
    for left_index, left_character in enumerate(left, start=1):
        current = [float(left_index)]
        for right_index, right_character in enumerate(right, start=1):
            substitution_cost = (
                0.0
                if left_character == right_character
                else 0.18
                if _same_ocr_group(left_character, right_character)
                else 1.0
            )
            value = min(
                previous[right_index] + 1.0,
                current[right_index - 1] + 1.0,
                previous[right_index - 1] + substitution_cost,
            )
            if (
                previous_previous is not None
                and left_index > 1
                and right_index > 1
                and left[left_index - 1] == right[right_index - 2]
                and left[left_index - 2] == right[right_index - 1]
            ):
                value = min(value, previous_previous[right_index - 2] + 0.65)
            current.append(value)
        previous_previous, previous = previous, current
    return previous[-1]


def normalized_similarity(left: object, right: object) -> float:
    left_signature = conservative_signature(left)
    right_signature = conservative_signature(right)
    denominator = max(len(left_signature), len(right_signature), 1)
    distance = weighted_damerau_levenshtein(left_signature, right_signature)
    return max(0.0, 1.0 - distance / denominator)


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 0.0


def _prefix_suffix_agreement(left: str, right: str, width: int = 4) -> float:
    if not left or not right:
        return 0.0
    effective = min(width, len(left), len(right))
    prefix = sum(a == b for a, b in zip(left[:effective], right[:effective], strict=True))
    suffix = sum(a == b for a, b in zip(left[-effective:], right[-effective:], strict=True))
    return (prefix + suffix) / (2 * effective)


def pair_score(left: object, right: object) -> float:
    """Return a calibrated deterministic score in [0, 1]."""
    if is_superseded(left) or is_superseded(right):
        return 0.0

    left_conservative = conservative_signature(left)
    right_conservative = conservative_signature(right)
    if not left_conservative or not right_conservative:
        return 0.0
    if left_conservative == right_conservative:
        return 1.0

    left_ocr = ocr_signature(left)
    right_ocr = ocr_signature(right)
    edit_similarity = normalized_similarity(left, right)
    token_similarity = _jaccard(token_signature(left), token_signature(right))
    boundary_similarity = _prefix_suffix_agreement(left_ocr, right_ocr)

    left_digits, right_digits = digit_signature(left), digit_signature(right)
    digit_similarity = (
        1.0
        if left_digits == right_digits and left_digits
        else normalized_similarity(left_digits, right_digits)
        if left_digits and right_digits
        else 0.0
    )

    if left_ocr == right_ocr:
        base = 0.965
    else:
        base = (
            0.55 * edit_similarity
            + 0.18 * digit_similarity
            + 0.17 * boundary_similarity
            + 0.10 * token_similarity
        )

    # Strong contradiction guard: identifiers with materially different digit
    # payloads should not merge merely because their prefixes look similar.
    if left_digits and right_digits:
        length_gap = abs(len(left_digits) - len(right_digits))
        if length_gap >= 3:
            base -= 0.18
        if digit_similarity < 0.55:
            base -= 0.20

    length_ratio = min(len(left_conservative), len(right_conservative)) / max(
        len(left_conservative), len(right_conservative)
    )
    if length_ratio < 0.65:
        base -= 0.18

    return min(1.0, max(0.0, base))


@dataclass(frozen=True, slots=True)
class Entity:
    key: str
    surface: str
    attributes: Mapping[str, object] | None = None


class ResolutionStatus(str, Enum):
    EXACT = "exact"
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class Resolution:
    left_key: str
    right_key: str | None
    status: ResolutionStatus
    score: float
    second_score: float
    margin: float
    candidates_considered: int
    reason: str


@dataclass(frozen=True, slots=True)
class ResolutionAudit:
    total_left: int
    exact: int
    matched: int
    ambiguous: int
    unmatched: int
    superseded: int

    @property
    def accepted(self) -> int:
        return self.exact + self.matched

    @property
    def coverage(self) -> float:
        eligible = self.total_left - self.superseded
        return self.accepted / eligible if eligible else 1.0


@dataclass(frozen=True, slots=True)
class ResolutionBatch:
    resolutions: tuple[Resolution, ...]
    audit: ResolutionAudit

    def accepted_map(self) -> dict[str, str]:
        return {
            resolution.left_key: resolution.right_key
            for resolution in self.resolutions
            if resolution.right_key is not None
            and resolution.status in {ResolutionStatus.EXACT, ResolutionStatus.MATCHED}
        }


def _blocking_keys(value: object) -> set[tuple[object, ...]]:
    conservative = conservative_signature(value)
    tolerant = ocr_signature(value)
    digits = digit_signature(value)
    length = len(conservative)
    keys: set[tuple[object, ...]] = {
        ("C", conservative),
        ("O", tolerant),
        ("L", length // 2),
    }
    if tolerant:
        keys.add(("B", tolerant[:4], tolerant[-4:], length // 3))
        keys.add(("P", tolerant[:6], length // 3))
        keys.add(("S", tolerant[-6:], length // 3))
    if digits:
        keys.add(("D", digits[:5], digits[-5:], len(digits) // 2))
    return keys


def _candidate_indices(
    left: Entity,
    right: Sequence[Entity],
    index: Mapping[tuple[object, ...], set[int]],
    *,
    full_scan_limit: int,
) -> set[int]:
    candidates: set[int] = set()
    for key in _blocking_keys(left.surface):
        candidates.update(index.get(key, ()))
    if not candidates and len(right) <= full_scan_limit:
        candidates.update(range(len(right)))
    return candidates


def resolve_entities(
    left: Iterable[Entity],
    right: Iterable[Entity],
    *,
    threshold: float = 0.84,
    margin_threshold: float = 0.055,
    full_scan_limit: int = 1_500,
) -> ResolutionBatch:
    """Resolve two identifier collections with mutual-best and margin gates.

    Accepted matches are one-to-one. Anything below threshold, tied, or without
    sufficient separation from the second candidate is quarantined rather than
    silently merged.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    if not 0.0 <= margin_threshold <= 1.0:
        raise ValueError("margin_threshold must be in [0, 1]")

    left_rows = tuple(left)
    right_rows = tuple(right)
    if len({row.key for row in left_rows}) != len(left_rows):
        raise ValueError("left entity keys must be unique")
    if len({row.key for row in right_rows}) != len(right_rows):
        raise ValueError("right entity keys must be unique")

    block_index: dict[tuple[object, ...], set[int]] = defaultdict(set)
    for right_index, row in enumerate(right_rows):
        if is_superseded(row.surface):
            continue
        for key in _blocking_keys(row.surface):
            block_index[key].add(right_index)

    ranked_by_left: dict[int, list[tuple[float, int]]] = {}
    right_best: dict[int, tuple[float, int]] = {}
    for left_index, left_row in enumerate(left_rows):
        if is_superseded(left_row.surface):
            continue
        candidates = _candidate_indices(
            left_row, right_rows, block_index, full_scan_limit=full_scan_limit
        )
        ranked = sorted(
            (
                (pair_score(left_row.surface, right_rows[right_index].surface), right_index)
                for right_index in candidates
                if not is_superseded(right_rows[right_index].surface)
            ),
            key=lambda item: (-item[0], right_rows[item[1]].key),
        )
        ranked_by_left[left_index] = ranked
        if ranked:
            score, right_index = ranked[0]
            incumbent = right_best.get(right_index)
            if incumbent is None or score > incumbent[0] or (
                math.isclose(score, incumbent[0])
                and left_rows[left_index].key < left_rows[incumbent[1]].key
            ):
                right_best[right_index] = (score, left_index)

    resolutions: list[Resolution] = []
    for left_index, left_row in enumerate(left_rows):
        if is_superseded(left_row.surface):
            resolutions.append(
                Resolution(
                    left_key=left_row.key,
                    right_key=None,
                    status=ResolutionStatus.SUPERSEDED,
                    score=0.0,
                    second_score=0.0,
                    margin=0.0,
                    candidates_considered=0,
                    reason="surface has an explicit superseded suffix",
                )
            )
            continue

        ranked = ranked_by_left.get(left_index, [])
        if not ranked:
            resolutions.append(
                Resolution(
                    left_key=left_row.key,
                    right_key=None,
                    status=ResolutionStatus.UNMATCHED,
                    score=0.0,
                    second_score=0.0,
                    margin=0.0,
                    candidates_considered=0,
                    reason="no candidate survived blocking",
                )
            )
            continue

        best_score, best_right_index = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best_score - second_score
        mutual = right_best.get(best_right_index, (None, None))[1] == left_index
        best_right = right_rows[best_right_index]

        if best_score < threshold:
            status = ResolutionStatus.UNMATCHED
            right_key = None
            reason = "best score below acceptance threshold"
        elif margin < margin_threshold:
            status = ResolutionStatus.AMBIGUOUS
            right_key = None
            reason = "insufficient margin over second candidate"
        elif not mutual:
            status = ResolutionStatus.AMBIGUOUS
            right_key = None
            reason = "candidate is not a mutual best match"
        else:
            exact = conservative_signature(left_row.surface) == conservative_signature(
                best_right.surface
            )
            status = ResolutionStatus.EXACT if exact else ResolutionStatus.MATCHED
            right_key = best_right.key
            reason = "accepted by threshold, margin, and mutual-best gates"

        resolutions.append(
            Resolution(
                left_key=left_row.key,
                right_key=right_key,
                status=status,
                score=best_score,
                second_score=second_score,
                margin=margin,
                candidates_considered=len(ranked),
                reason=reason,
            )
        )

    counts = {status: 0 for status in ResolutionStatus}
    for resolution in resolutions:
        counts[resolution.status] += 1
    audit = ResolutionAudit(
        total_left=len(left_rows),
        exact=counts[ResolutionStatus.EXACT],
        matched=counts[ResolutionStatus.MATCHED],
        ambiguous=counts[ResolutionStatus.AMBIGUOUS],
        unmatched=counts[ResolutionStatus.UNMATCHED],
        superseded=counts[ResolutionStatus.SUPERSEDED],
    )
    return ResolutionBatch(tuple(resolutions), audit)
