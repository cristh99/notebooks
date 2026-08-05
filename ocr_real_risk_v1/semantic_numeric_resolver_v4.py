"""Zero-cost semantic trigger and fail-closed crop resolver for numeric OCR v4.

The module does not use annotations or ground truth at inference time. It first
looks for two narrow internal contradictions in baseline OCR output:

* a singleton decimal amount one digit away from a value repeated on two or
  more distinct lines in the same document;
* a quantity-one item row whose unit price and amount disagree by one digit.

Only the implicated token is re-read from two independently parameterized crop
views. Agreement on the same alternative can resolve the token; any unresolved
semantic contradiction quarantines it. No rule silently guesses from arithmetic,
document frequency, or repeated readings from the same OCR engine alone.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Sequence

from PIL import Image, ImageOps
import pytesseract
from pytesseract import Output

_ASCII_DIGITS = re.compile(r"[0-9]")
_AMOUNT = re.compile(r"^[+-]?[0-9]{1,6}([.,])([0-9]{1,2})$")
_QTY_ONE = re.compile(r"^1(?:[Xx])?$")


class TriggerReason(str, Enum):
    NEAR_DUPLICATE_DOCUMENT_MAJORITY = "NEAR_DUPLICATE_DOCUMENT_MAJORITY"
    QTY1_UNIT_AMOUNT_DISAGREEMENT = "QTY1_UNIT_AMOUNT_DISAGREEMENT"


class ResolutionAction(str, Enum):
    KEEP = "KEEP"
    REPLACE = "REPLACE"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True, slots=True)
class OCRToken:
    index: int
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    block: int
    paragraph: int
    line: int

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
class SemanticFlag:
    token_index: int
    reasons: tuple[TriggerReason, ...]


@dataclass(frozen=True, slots=True)
class CropObservation:
    source_id: str
    view: str
    psm: int
    text: str
    elapsed_seconds: float
    timeout: bool = False

    @property
    def digits(self) -> str:
        return canonical_ascii_digits(self.text)


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    action: ResolutionAction
    reason_code: str
    baseline: str
    output: str
    evidence: tuple[CropObservation, ...]
    decision_sha256: str


def canonical_ascii_digits(value: object) -> str:
    return "".join(_ASCII_DIGITS.findall(str(value or "")))


def decimal_signature(value: object) -> tuple[int, int] | None:
    match = _AMOUNT.fullmatch(str(value or "").strip().strip("*"))
    if match is None:
        return None
    digits = canonical_ascii_digits(match.group(0))
    return len(digits), len(match.group(2))


def _hamming_one(first: str, second: str) -> bool:
    return len(first) == len(second) and sum(a != b for a, b in zip(first, second)) == 1


def detect_semantic_flags(tokens: Sequence[OCRToken]) -> tuple[SemanticFlag, ...]:
    """Return narrow, outcome-blind contradictions in baseline OCR tokens."""

    reasons: dict[int, set[TriggerReason]] = defaultdict(set)
    amount_tokens = [
        token
        for token in tokens
        if decimal_signature(token.text) is not None and 4 <= len(token.digits) <= 8
    ]

    distinct_lines: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
    signatures: dict[str, tuple[int, int]] = {}
    for token in amount_tokens:
        distinct_lines[token.digits].add(token.line_key)
        signature = decimal_signature(token.text)
        assert signature is not None
        signatures[token.digits] = signature
    counts = Counter(token.digits for token in amount_tokens)
    for token in amount_tokens:
        if counts[token.digits] != 1:
            continue
        signature = decimal_signature(token.text)
        rivals = [
            value
            for value, count in counts.items()
            if count >= 2
            and len(distinct_lines[value]) >= 2
            and signatures.get(value) == signature
            and _hamming_one(value, token.digits)
        ]
        if rivals:
            reasons[token.index].add(TriggerReason.NEAR_DUPLICATE_DOCUMENT_MAJORITY)

    lines: dict[tuple[int, int, int], list[OCRToken]] = defaultdict(list)
    for token in tokens:
        lines[token.line_key].append(token)
    for line_tokens in lines.values():
        ordered = sorted(line_tokens, key=lambda token: token.center_x)
        quantity_one = any(_QTY_ONE.fullmatch(token.text.strip()) for token in ordered)
        amounts = [token for token in ordered if decimal_signature(token.text) is not None]
        if not quantity_one or len(amounts) != 2:
            continue
        left, right = amounts
        if decimal_signature(left.text) != decimal_signature(right.text):
            continue
        if not _hamming_one(left.digits, right.digits):
            continue
        implicated = (
            left
            if left.confidence < right.confidence
            else right
            if right.confidence < left.confidence
            else max((left, right), key=lambda token: token.center_x)
        )
        reasons[implicated.index].add(TriggerReason.QTY1_UNIT_AMOUNT_DISAGREEMENT)

    return tuple(
        SemanticFlag(token_index=index, reasons=tuple(sorted(values, key=lambda item: item.value)))
        for index, values in sorted(reasons.items())
    )


def _decision_hash(
    *,
    action: ResolutionAction,
    reason_code: str,
    baseline: str,
    output: str,
    evidence: Sequence[CropObservation],
) -> str:
    payload = {
        "schema": "ocr-semantic-numeric-resolver-v4-decision/1",
        "action": action.value,
        "reason_code": reason_code,
        "baseline": baseline,
        "output": output,
        "evidence": [asdict(item) for item in evidence],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def resolve_flagged_token(
    baseline: str,
    observations: Iterable[CropObservation],
) -> ResolutionDecision:
    """Resolve one semantically flagged token or quarantine it."""

    baseline_digits = canonical_ascii_digits(baseline)
    if not baseline_digits:
        raise ValueError("baseline must contain at least one ASCII digit")
    evidence = tuple(observations)
    source_ids = [item.source_id for item in evidence]
    if len(evidence) != 2 or len(set(source_ids)) != 2:
        action = ResolutionAction.QUARANTINE
        reason = "TWO_INDEPENDENT_CROP_PROBES_REQUIRED"
        output = baseline
    else:
        candidates = [
            item.digits
            for item in evidence
            if not item.timeout and len(item.digits) == len(baseline_digits)
        ]
        if len(candidates) != 2:
            action = ResolutionAction.QUARANTINE
            reason = "INCOMPLETE_EQUAL_LENGTH_CROP_EVIDENCE"
            output = baseline
        elif candidates[0] != candidates[1]:
            action = ResolutionAction.QUARANTINE
            reason = "CROP_PROBES_DISAGREE"
            output = baseline
        elif candidates[0] == baseline_digits:
            # This function is called only after an independent semantic
            # contradiction has flagged the baseline token. Repeating the same
            # reading through two Tesseract crop views does not clear that
            # contradiction because the probes share an engine and can repeat
            # the same systematic glyph error. Fail closed instead of silently
            # restoring the disputed baseline.
            action = ResolutionAction.QUARANTINE
            reason = "SEMANTIC_CONTRADICTION_NOT_CLEARED_BY_SAME_ENGINE_PROBES"
            output = baseline
        else:
            action = ResolutionAction.REPLACE
            reason = "TWO_CROP_PROBES_AGREE_ON_ALTERNATIVE"
            output = _format_like_baseline(baseline, candidates[0])
    return ResolutionDecision(
        action=action,
        reason_code=reason,
        baseline=baseline,
        output=output,
        evidence=evidence,
        decision_sha256=_decision_hash(
            action=action,
            reason_code=reason,
            baseline=baseline,
            output=output,
            evidence=evidence,
        ),
    )


def _format_like_baseline(baseline: str, replacement_digits: str) -> str:
    iterator = iter(replacement_digits)
    output: list[str] = []
    for character in baseline:
        output.append(next(iterator) if "0" <= character <= "9" else character)
    try:
        next(iterator)
    except StopIteration:
        return "".join(output)
    raise ValueError("replacement digit count exceeds baseline digit slots")


def tesseract_page_tokens(image: Image.Image, *, psm: int = 3) -> tuple[tuple[OCRToken, ...], float]:
    """Run one full-page baseline pass and retain line geometry."""

    started = time.perf_counter()
    data = pytesseract.image_to_data(
        image,
        lang="eng",
        config=f"--oem 1 --psm {psm}",
        output_type=Output.DICT,
        timeout=60,
    )
    elapsed = time.perf_counter() - started
    tokens: list[OCRToken] = []
    for index, text in enumerate(data.get("text") or []):
        value = str(text).strip()
        if not value:
            continue
        try:
            left = int(data["left"][index])
            top = int(data["top"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
            confidence = float(data["conf"][index])
            block = int(data["block_num"][index])
            paragraph = int(data["par_num"][index])
            line = int(data["line_num"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0 or not math.isfinite(confidence):
            continue
        tokens.append(
            OCRToken(
                index=index,
                text=value,
                bbox=(left, top, left + width, top + height),
                confidence=confidence,
                block=block,
                paragraph=paragraph,
                line=line,
            )
        )
    return tuple(tokens), elapsed


def _crop_box(image: Image.Image, bbox: Sequence[int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = map(int, bbox)
    margin = max(2, round((bottom - top) * 0.25))
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(image.width, right + margin),
        min(image.height, bottom + margin),
    )


def _crop_ocr(
    image: Image.Image,
    *,
    source_id: str,
    view: str,
    psm: int,
) -> CropObservation:
    started = time.perf_counter()
    try:
        text = pytesseract.image_to_string(
            image,
            lang="eng",
            config=f"--oem 1 --psm {psm} -c tessedit_char_whitelist=0123456789.,/-",
            timeout=15,
        ).strip()
        timeout = False
    except RuntimeError as exc:
        if "timeout" not in str(exc).lower():
            raise
        text = ""
        timeout = True
    return CropObservation(
        source_id=source_id,
        view=view,
        psm=psm,
        text=text,
        elapsed_seconds=time.perf_counter() - started,
        timeout=timeout,
    )


def run_two_probe_crop_resolver(
    page: Image.Image,
    token: OCRToken,
) -> tuple[ResolutionDecision, tuple[int, int, int, int]]:
    """Run the fixed v4 two-probe crop policy for one semantic flag."""

    box = _crop_box(page, token.bbox)
    crop = page.crop(box).convert("L")
    probe_a = _crop_ocr(
        crop,
        source_id="original-gray-psm7",
        view="original_gray",
        psm=7,
    )
    enlarged = ImageOps.autocontrast(crop, cutoff=1).resize(
        (max(2, crop.width * 2), max(2, crop.height * 2)),
        Image.Resampling.LANCZOS,
    )
    probe_b = _crop_ocr(
        enlarged,
        source_id="autocontrast-2x-psm13",
        view="autocontrast_2x",
        psm=13,
    )
    return resolve_flagged_token(token.text, (probe_a, probe_b)), box
