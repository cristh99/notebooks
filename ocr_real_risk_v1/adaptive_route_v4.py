"""Fail-closed OCR routing, exact cache identity, and strict 10x speed gates.

The route is ordered by evidence: validated native text, verified exact cache,
quality-gated fast pixel OCR, Tesseract fallback, then quarantine. The module
contains no network or cloud calls and never treats a projection as a measured
speed certificate.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable, Literal, Mapping, Sequence

Route = Literal[
    "NATIVE",
    "EXACT_CACHE",
    "FAST_PIXEL",
    "TESSERACT",
    "QUARANTINE",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class NativeWord:
    text: str
    bbox: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        text = unicodedata.normalize("NFKC", str(self.text))
        if len(self.bbox) != 4:
            raise ValueError("bbox must contain four coordinates")
        bbox = tuple(float(value) for value in self.bbox)
        if not all(math.isfinite(value) for value in bbox):
            raise ValueError("bbox coordinates must be finite")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox must have positive width and height")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "bbox", bbox)


@dataclass(frozen=True, slots=True)
class NativeTextPolicy:
    min_words: int = 5
    min_chars: int = 40
    min_alnum_chars: int = 20
    min_printable_ratio: float = 0.95
    min_alnum_ratio: float = 0.25
    min_unique_token_ratio: float = 0.12
    max_dominant_token_ratio: float = 0.35
    max_replacement_ratio: float = 0.02
    max_control_ratio: float = 0.0
    max_duplicate_box_ratio: float = 0.35
    min_inside_box_ratio: float = 0.98
    max_words: int = 100_000

    def __post_init__(self) -> None:
        if self.min_words < 1 or self.min_chars < 1 or self.min_alnum_chars < 1:
            raise ValueError("minimum counts must be positive")
        if self.max_words < self.min_words:
            raise ValueError("max_words must be at least min_words")
        for label, value in (
            ("min_printable_ratio", self.min_printable_ratio),
            ("min_alnum_ratio", self.min_alnum_ratio),
            ("min_unique_token_ratio", self.min_unique_token_ratio),
            ("max_dominant_token_ratio", self.max_dominant_token_ratio),
            ("max_replacement_ratio", self.max_replacement_ratio),
            ("max_control_ratio", self.max_control_ratio),
            ("max_duplicate_box_ratio", self.max_duplicate_box_ratio),
            ("min_inside_box_ratio", self.min_inside_box_ratio),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class NativeValidation:
    passed: bool
    reason_codes: tuple[str, ...]
    words: int
    chars: int
    alnum_chars: int
    printable_ratio: float
    alnum_ratio: float
    unique_token_ratio: float
    dominant_token_ratio: float
    replacement_ratio: float
    control_ratio: float
    duplicate_box_ratio: float
    inside_box_ratio: float
    validation_sha256: str


@dataclass(frozen=True, slots=True)
class CacheReceipt:
    key_sha256: str
    object_sha256: str
    output_sha256: str
    verified: bool

    def __post_init__(self) -> None:
        for label, value in (
            ("key_sha256", self.key_sha256),
            ("object_sha256", self.object_sha256),
            ("output_sha256", self.output_sha256),
        ):
            if not _SHA256_RE.fullmatch(str(value)):
                raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class FastPixelEvidence:
    output_sha256: str
    quality_gate_pass: bool
    coverage_gate_pass: bool
    stable_builds: int
    runtime_ms: float

    def __post_init__(self) -> None:
        if not _SHA256_RE.fullmatch(str(self.output_sha256)):
            raise ValueError("output_sha256 must be a lowercase SHA-256 hex digest")
        if self.stable_builds < 0:
            raise ValueError("stable_builds must be non-negative")
        if not math.isfinite(self.runtime_ms) or self.runtime_ms <= 0.0:
            raise ValueError("runtime_ms must be finite and positive")


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: Route
    reason_code: str
    native_validation_sha256: str | None
    output_sha256: str | None
    decision_sha256: str


@dataclass(frozen=True, slots=True)
class CacheRecipe:
    page_pixels_sha256: str
    width: int
    height: int
    mode: str
    engine_sha256: str
    model_sha256: tuple[str, ...]
    language: str
    oem: int
    psm: int
    dpi: int
    preprocessing_sha256: str
    formats: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("page_pixels_sha256", self.page_pixels_sha256),
            ("engine_sha256", self.engine_sha256),
            ("preprocessing_sha256", self.preprocessing_sha256),
        ):
            if not _SHA256_RE.fullmatch(str(value)):
                raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
        if not self.model_sha256:
            raise ValueError("at least one model digest is required")
        if any(not _SHA256_RE.fullmatch(str(value)) for value in self.model_sha256):
            raise ValueError("model_sha256 contains an invalid digest")
        if self.width < 1 or self.height < 1 or self.dpi < 1:
            raise ValueError("dimensions and dpi must be positive")
        if self.oem < 0 or self.psm < 1:
            raise ValueError("OEM/PSM values are invalid")
        mode = str(self.mode).strip()
        language = str(self.language).strip()
        formats = tuple(sorted({str(value).strip().lower() for value in self.formats}))
        if not mode or not language or not formats or any(not value for value in formats):
            raise ValueError("mode, language, and formats must be non-empty")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "formats", formats)
        object.__setattr__(self, "model_sha256", tuple(sorted(self.model_sha256)))


@dataclass(frozen=True, slots=True)
class RouteProfile:
    route: Route
    fraction: float
    relative_latency: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.fraction) or not 0.0 <= self.fraction <= 1.0:
            raise ValueError("fraction must be within [0, 1]")
        if not math.isfinite(self.relative_latency) or self.relative_latency <= 0.0:
            raise ValueError("relative_latency must be finite and positive")


@dataclass(frozen=True, slots=True)
class RouteBudget:
    projected: bool
    required_speedup: float
    weighted_relative_latency: float
    throughput_speedup: float
    pass_projection: bool
    fractions_by_route: tuple[tuple[str, float], ...]
    budget_sha256: str


@dataclass(frozen=True, slots=True)
class PairedLatency:
    page_id: str
    baseline_ms: float
    candidate_ms: float
    route: Route

    def __post_init__(self) -> None:
        page_id = str(self.page_id).strip()
        if not page_id:
            raise ValueError("page_id must be non-empty")
        if not math.isfinite(self.baseline_ms) or self.baseline_ms <= 0.0:
            raise ValueError("baseline_ms must be finite and positive")
        if not math.isfinite(self.candidate_ms) or self.candidate_ms <= 0.0:
            raise ValueError("candidate_ms must be finite and positive")
        object.__setattr__(self, "page_id", page_id)


@dataclass(frozen=True, slots=True)
class MeasuredSpeedGate:
    pass_gate: bool
    reason_codes: tuple[str, ...]
    required_speedup: float
    pairs: int
    throughput_speedup: float
    median_paired_speedup: float
    p95_latency_speedup: float
    bootstrap_lower_95: float
    gate_sha256: str


def _sha256_payload(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_native_text(
    words: Iterable[NativeWord],
    *,
    page_width: float,
    page_height: float,
    policy: NativeTextPolicy | None = None,
) -> NativeValidation:
    """Validate useful native text rather than merely detecting PDF text objects."""

    active = policy or NativeTextPolicy()
    if not math.isfinite(page_width) or not math.isfinite(page_height):
        raise ValueError("page dimensions must be finite")
    if page_width <= 0.0 or page_height <= 0.0:
        raise ValueError("page dimensions must be positive")
    rows = list(words)
    reasons: list[str] = []
    if len(rows) > active.max_words:
        reasons.append("RESOURCE_LIMIT")
        rows = rows[: active.max_words]

    nonempty = [row for row in rows if row.text.strip()]
    text = "\n".join(row.text for row in nonempty)
    chars = len(text)
    alnum_chars = sum(character.isalnum() for character in text)
    printable_chars = sum(character.isprintable() or character in "\n\t" for character in text)
    replacement_chars = text.count("\ufffd")
    control_chars = sum(
        unicodedata.category(character) == "Cc" and character not in "\n\t\r"
        for character in text
    )
    printable_ratio = printable_chars / chars if chars else 0.0
    alnum_ratio = alnum_chars / chars if chars else 0.0
    replacement_ratio = replacement_chars / chars if chars else 0.0
    control_ratio = control_chars / chars if chars else 0.0

    tokens = [token.casefold() for token in _TOKEN_RE.findall(text)]
    counts = Counter(tokens)
    unique_token_ratio = len(counts) / len(tokens) if tokens else 0.0
    dominant_token_ratio = max(counts.values()) / len(tokens) if counts else 0.0

    boxes = [row.bbox for row in nonempty]
    rounded_boxes = [tuple(round(value, 3) for value in bbox) for bbox in boxes]
    duplicate_box_ratio = (
        1.0 - len(set(rounded_boxes)) / len(rounded_boxes) if rounded_boxes else 0.0
    )
    inside = sum(
        bbox[0] >= 0.0
        and bbox[1] >= 0.0
        and bbox[2] <= page_width
        and bbox[3] <= page_height
        for bbox in boxes
    )
    inside_box_ratio = inside / len(boxes) if boxes else 0.0

    checks = (
        (len(nonempty) >= active.min_words, "TOO_FEW_WORDS"),
        (chars >= active.min_chars, "TOO_FEW_CHARS"),
        (alnum_chars >= active.min_alnum_chars, "TOO_FEW_ALNUM_CHARS"),
        (printable_ratio >= active.min_printable_ratio, "LOW_PRINTABLE_RATIO"),
        (alnum_ratio >= active.min_alnum_ratio, "LOW_ALNUM_RATIO"),
        (unique_token_ratio >= active.min_unique_token_ratio, "LOW_TOKEN_DIVERSITY"),
        (dominant_token_ratio <= active.max_dominant_token_ratio, "DOMINANT_TOKEN_REPEAT"),
        (replacement_ratio <= active.max_replacement_ratio, "REPLACEMENT_CHARACTERS"),
        (control_ratio <= active.max_control_ratio, "CONTROL_CHARACTERS"),
        (duplicate_box_ratio <= active.max_duplicate_box_ratio, "DUPLICATE_BOXES"),
        (inside_box_ratio >= active.min_inside_box_ratio, "OUT_OF_PAGE_BOXES"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    reason_codes = tuple(dict.fromkeys(reasons))
    payload = {
        "schema": "ocr-native-validation-v4/1",
        "passed": not reason_codes,
        "reason_codes": reason_codes,
        "page_width": page_width,
        "page_height": page_height,
        "words": len(nonempty),
        "chars": chars,
        "alnum_chars": alnum_chars,
        "printable_ratio": printable_ratio,
        "alnum_ratio": alnum_ratio,
        "unique_token_ratio": unique_token_ratio,
        "dominant_token_ratio": dominant_token_ratio,
        "replacement_ratio": replacement_ratio,
        "control_ratio": control_ratio,
        "duplicate_box_ratio": duplicate_box_ratio,
        "inside_box_ratio": inside_box_ratio,
        "policy": asdict(active),
    }
    return NativeValidation(
        passed=not reason_codes,
        reason_codes=reason_codes,
        words=len(nonempty),
        chars=chars,
        alnum_chars=alnum_chars,
        printable_ratio=printable_ratio,
        alnum_ratio=alnum_ratio,
        unique_token_ratio=unique_token_ratio,
        dominant_token_ratio=dominant_token_ratio,
        replacement_ratio=replacement_ratio,
        control_ratio=control_ratio,
        duplicate_box_ratio=duplicate_box_ratio,
        inside_box_ratio=inside_box_ratio,
        validation_sha256=_sha256_payload(payload),
    )


def canonical_cache_key(recipe: CacheRecipe) -> str:
    """Hash only exact OCR determinants; the PDF container hash is provenance."""

    return _sha256_payload({"schema": "ocr-exact-cache-key-v4/1", **asdict(recipe)})


def route_page(
    *,
    native: NativeValidation | None,
    expected_cache_key: str | None,
    cache: CacheReceipt | None,
    fast_pixel: FastPixelEvidence | None,
    tesseract_available: bool,
    required_stable_builds: int = 2,
) -> RouteDecision:
    """Select the fastest route whose evidence passes every relevant gate."""

    if required_stable_builds < 1:
        raise ValueError("required_stable_builds must be positive")
    if expected_cache_key is not None and not _SHA256_RE.fullmatch(expected_cache_key):
        raise ValueError("expected_cache_key must be a lowercase SHA-256 digest")

    route: Route
    reason: str
    output_sha256: str | None = None
    if native is not None and native.passed:
        route = "NATIVE"
        reason = "NATIVE_TEXT_VALIDATED"
    elif (
        cache is not None
        and expected_cache_key is not None
        and cache.verified
        and cache.key_sha256 == expected_cache_key
    ):
        route = "EXACT_CACHE"
        reason = "EXACT_CACHE_VERIFIED"
        output_sha256 = cache.output_sha256
    elif (
        fast_pixel is not None
        and fast_pixel.quality_gate_pass
        and fast_pixel.coverage_gate_pass
        and fast_pixel.stable_builds >= required_stable_builds
    ):
        route = "FAST_PIXEL"
        reason = "FAST_PIXEL_GATES_PASS"
        output_sha256 = fast_pixel.output_sha256
    elif tesseract_available:
        route = "TESSERACT"
        reason = "SAFE_FALLBACK"
    else:
        route = "QUARANTINE"
        reason = "NO_VERIFIED_ROUTE"

    native_hash = native.validation_sha256 if native is not None else None
    payload = {
        "schema": "ocr-route-decision-v4/1",
        "route": route,
        "reason_code": reason,
        "native_validation_sha256": native_hash,
        "expected_cache_key": expected_cache_key,
        "cache": asdict(cache) if cache is not None else None,
        "fast_pixel": asdict(fast_pixel) if fast_pixel is not None else None,
        "tesseract_available": bool(tesseract_available),
        "required_stable_builds": required_stable_builds,
        "output_sha256": output_sha256,
    }
    return RouteDecision(
        route=route,
        reason_code=reason,
        native_validation_sha256=native_hash,
        output_sha256=output_sha256,
        decision_sha256=_sha256_payload(payload),
    )


def project_route_budget(
    profiles: Iterable[RouteProfile],
    *,
    required_speedup: float = 10.0,
) -> RouteBudget:
    """Project throughput from a route mix; this is never a measured certificate."""

    if not math.isfinite(required_speedup) or required_speedup <= 1.0:
        raise ValueError("required_speedup must be finite and greater than one")
    rows = list(profiles)
    if not rows:
        raise ValueError("at least one route profile is required")
    total_fraction = sum(row.fraction for row in rows)
    if not math.isclose(total_fraction, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("route fractions must sum to exactly one")
    weighted = sum(row.fraction * row.relative_latency for row in rows)
    speedup = 1.0 / weighted
    fractions: dict[str, float] = {}
    for row in rows:
        fractions[row.route] = fractions.get(row.route, 0.0) + row.fraction
    payload = {
        "schema": "ocr-route-budget-v4/1",
        "projected": True,
        "required_speedup": required_speedup,
        "weighted_relative_latency": weighted,
        "throughput_speedup": speedup,
        "pass_projection": speedup >= required_speedup,
        "profiles": [asdict(row) for row in rows],
    }
    return RouteBudget(
        projected=True,
        required_speedup=required_speedup,
        weighted_relative_latency=weighted,
        throughput_speedup=speedup,
        pass_projection=speedup >= required_speedup,
        fractions_by_route=tuple(sorted(fractions.items())),
        budget_sha256=_sha256_payload(payload),
    )


def required_fast_path_speedup(
    *,
    fast_fraction: float,
    fixed_profiles: Iterable[RouteProfile],
    required_total_speedup: float = 10.0,
) -> float:
    """Solve the minimum fast-pixel speedup needed by the remaining route share."""

    if not math.isfinite(fast_fraction) or not 0.0 < fast_fraction <= 1.0:
        raise ValueError("fast_fraction must be within (0, 1]")
    if not math.isfinite(required_total_speedup) or required_total_speedup <= 1.0:
        raise ValueError("required_total_speedup must be greater than one")
    fixed = list(fixed_profiles)
    fixed_fraction = sum(row.fraction for row in fixed)
    if not math.isclose(fixed_fraction + fast_fraction, 1.0, abs_tol=1e-9):
        raise ValueError("fixed fractions plus fast_fraction must sum to one")
    fixed_latency = sum(row.fraction * row.relative_latency for row in fixed)
    remaining_latency_budget = 1.0 / required_total_speedup - fixed_latency
    if remaining_latency_budget <= 0.0:
        return math.inf
    return fast_fraction / remaining_latency_budget


def maximum_tesseract_fraction(
    *,
    native_fraction: float,
    cache_fraction: float,
    native_relative_latency: float,
    cache_relative_latency: float,
    fast_speedup: float,
    required_total_speedup: float = 10.0,
) -> float:
    """Maximum total-page Tesseract fallback share compatible with the target."""

    values = (
        native_fraction,
        cache_fraction,
        native_relative_latency,
        cache_relative_latency,
        fast_speedup,
        required_total_speedup,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("all inputs must be finite")
    if native_fraction < 0.0 or cache_fraction < 0.0:
        raise ValueError("fractions must be non-negative")
    if native_fraction + cache_fraction > 1.0:
        raise ValueError("native and cache fractions cannot exceed one")
    if native_relative_latency <= 0.0 or cache_relative_latency <= 0.0:
        raise ValueError("relative latencies must be positive")
    if fast_speedup <= 1.0 or required_total_speedup <= 1.0:
        raise ValueError("speedups must be greater than one")
    remaining = 1.0 - native_fraction - cache_fraction
    fast_relative = 1.0 / fast_speedup
    base = (
        native_fraction * native_relative_latency
        + cache_fraction * cache_relative_latency
        + remaining * fast_relative
    )
    denominator = 1.0 - fast_relative
    maximum = (1.0 / required_total_speedup - base) / denominator
    return max(0.0, min(remaining, maximum))


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def _bootstrap_lower_speedup(
    rows: Sequence[PairedLatency],
    *,
    samples: int,
    seed: int,
) -> float:
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        selected = [rows[rng.randrange(len(rows))] for _ in rows]
        estimates.append(
            sum(row.baseline_ms for row in selected)
            / sum(row.candidate_ms for row in selected)
        )
    estimates.sort()
    return estimates[max(0, math.floor(0.05 * samples) - 1)]


def evaluate_measured_speed_gate(
    pairs: Iterable[PairedLatency],
    *,
    required_speedup: float = 10.0,
    min_pairs: int = 30,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 0,
) -> MeasuredSpeedGate:
    """Require throughput, median, tail, and bootstrap lower bound to clear 10x."""

    if not math.isfinite(required_speedup) or required_speedup <= 1.0:
        raise ValueError("required_speedup must be greater than one")
    if min_pairs < 5 or bootstrap_samples < 100:
        raise ValueError("sample thresholds are too small")
    rows = list(pairs)
    if not rows:
        raise ValueError("at least one latency pair is required")
    page_ids = [row.page_id for row in rows]
    if len(page_ids) != len(set(page_ids)):
        raise ValueError("page_id values must be unique")
    throughput = sum(row.baseline_ms for row in rows) / sum(
        row.candidate_ms for row in rows
    )
    paired_speedups = [row.baseline_ms / row.candidate_ms for row in rows]
    median_speedup = float(statistics.median(paired_speedups))
    p95_speedup = _nearest_rank(
        [row.baseline_ms for row in rows], 0.95
    ) / _nearest_rank([row.candidate_ms for row in rows], 0.95)
    lower = _bootstrap_lower_speedup(
        rows,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    reasons: list[str] = []
    if len(rows) < min_pairs:
        reasons.append("INSUFFICIENT_PAIRS")
    if throughput < required_speedup:
        reasons.append("THROUGHPUT_BELOW_TARGET")
    if median_speedup < required_speedup:
        reasons.append("MEDIAN_BELOW_TARGET")
    if p95_speedup < required_speedup:
        reasons.append("P95_BELOW_TARGET")
    if lower < required_speedup:
        reasons.append("BOOTSTRAP_LOWER_BELOW_TARGET")
    reason_codes = tuple(reasons)
    payload = {
        "schema": "ocr-measured-speed-gate-v4/1",
        "pass_gate": not reason_codes,
        "reason_codes": reason_codes,
        "required_speedup": required_speedup,
        "pairs": len(rows),
        "throughput_speedup": throughput,
        "median_paired_speedup": median_speedup,
        "p95_latency_speedup": p95_speedup,
        "bootstrap_lower_95": lower,
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": bootstrap_seed,
        "rows": [asdict(row) for row in sorted(rows, key=lambda item: item.page_id)],
    }
    return MeasuredSpeedGate(
        pass_gate=not reason_codes,
        reason_codes=reason_codes,
        required_speedup=required_speedup,
        pairs=len(rows),
        throughput_speedup=throughput,
        median_paired_speedup=median_speedup,
        p95_latency_speedup=p95_speedup,
        bootstrap_lower_95=lower,
        gate_sha256=_sha256_payload(payload),
    )
