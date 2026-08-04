"""Core utilities for a sealed Honduran numeric OCR risk holdout.

The unit of inference is one unique OCDS procurement record (OCID):
* sample selection never observes OCR output;
* one PDF and one contiguous digit token are accepted per OCID;
* truth comes from character coordinates in digitally generated PDF text;
* pages dominated by a full-page image are excluded from this vector-truth tier;
* every source, token, crop and decision is hash-bound;
* evaluation begins only after the manifest is sealed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlparse

import fitz
from scipy.stats import beta

SCHEMA_MANIFEST = "ocr-hn-numeric-holdout/manifest/2"
SCHEMA_REPORT = "ocr-hn-numeric-holdout/evaluation/2"
NON_DIGIT_RE = re.compile(r"\D+")
PDF_URL_RE = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)

DOCUMENT_TYPE_PRIORITY = {
    "contractSigned": 0,
    "contract": 0,
    "awardNotice": 1,
    "biddingDocuments": 2,
    "technicalSpecifications": 2,
    "tenderNotice": 3,
    "evaluationReports": 3,
    "completionCertificate": 3,
    "physicalProgressReport": 4,
    "financialProgressReport": 4,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    return " ".join(text.split()).strip()


def canonical_digits(value: str) -> str:
    return NON_DIGIT_RE.sub("", unicodedata.normalize("NFKC", value or ""))


def deterministic_key(*parts: object) -> str:
    return sha256_bytes("|".join(str(part) for part in parts).encode("utf-8"))


def one_digit_counterfactual(token: str, salt: str) -> str:
    if not token or not token.isdigit():
        raise ValueError("counterfactual input must be a non-empty digit token")
    index = int(hashlib.sha256(f"{salt}|index".encode()).hexdigest(), 16) % len(token)
    shift = 1 + int(hashlib.sha256(f"{salt}|shift".encode()).hexdigest(), 16) % 9
    replacement = str((int(token[index]) + shift) % 10)
    return token[:index] + replacement + token[index + 1 :]


def clopper_pearson_lower(k: int, n: int, alpha: float = 0.05) -> float:
    if n <= 0 or k < 0 or k > n:
        raise ValueError("invalid binomial counts")
    if k == 0:
        return 0.0
    return float(beta.ppf(alpha, k, n - k + 1))


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    if n <= 0 or k < 0 or k > n:
        raise ValueError("invalid binomial counts")
    if k == n:
        return 1.0
    return float(beta.ppf(1.0 - alpha, k + 1, n - k))


def risk_gate(
    *,
    baseline_false: int,
    baseline_total: int,
    candidate_false: int,
    candidate_total: int,
    eligible_total: int,
    factor: float = 10.0,
    alpha: float = 0.05,
    minimum_accepted: int = 200,
    minimum_coverage: float = 0.30,
) -> dict[str, Any]:
    if factor <= 1:
        raise ValueError("factor must exceed one")
    if eligible_total <= 0:
        raise ValueError("eligible_total must be positive")
    if not 0 <= minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be in [0, 1]")
    baseline_lower = (
        clopper_pearson_lower(baseline_false, baseline_total, alpha)
        if baseline_total
        else 0.0
    )
    candidate_upper = (
        clopper_pearson_upper(candidate_false, candidate_total, alpha)
        if candidate_total
        else 1.0
    )
    coverage = candidate_total / eligible_total
    point_baseline = baseline_false / baseline_total if baseline_total else None
    point_candidate = candidate_false / candidate_total if candidate_total else None
    certified_reduction = baseline_lower / candidate_upper if candidate_upper > 0 else math.inf
    pass_gate = bool(
        baseline_total > 0
        and baseline_false > 0
        and candidate_total >= minimum_accepted
        and coverage >= minimum_coverage
        and candidate_upper <= baseline_lower / factor
    )
    if baseline_total == 0:
        reason = "NO_BASELINE_CLAIMS"
    elif baseline_false == 0:
        reason = "BASELINE_TOO_CLEAN_TO_CERTIFY"
    elif candidate_total < minimum_accepted:
        reason = "INSUFFICIENT_ACCEPTED_COUNT"
    elif coverage < minimum_coverage:
        reason = "INSUFFICIENT_ACCEPTANCE_COVERAGE"
    elif not pass_gate:
        reason = "TENFOLD_RISK_BOUND_NOT_REACHED"
    else:
        reason = "PASS_TENFOLD_RISK_BOUND"
    return {
        "alpha_one_sided": alpha,
        "target_reduction_factor": factor,
        "minimum_accepted": minimum_accepted,
        "minimum_coverage": minimum_coverage,
        "baseline": {
            "false_accepts": baseline_false,
            "claims": baseline_total,
            "point_risk": point_baseline,
            "one_sided_lower_bound": baseline_lower,
        },
        "candidate": {
            "false_accepts": candidate_false,
            "accepts": candidate_total,
            "eligible": eligible_total,
            "point_risk": point_candidate,
            "one_sided_upper_bound": candidate_upper,
            "acceptance_coverage": coverage,
        },
        "certified_reduction_factor": certified_reduction,
        "pass": pass_gate,
        "reason": reason,
    }


def absolute_risk_gate(
    *,
    false_accepts: int,
    total: int,
    maximum_upper_risk: float,
    minimum_total: int,
    alpha: float = 0.05,
) -> dict[str, Any]:
    upper = clopper_pearson_upper(false_accepts, total, alpha) if total else 1.0
    passed = total >= minimum_total and upper <= maximum_upper_risk
    if total < minimum_total:
        reason = "INSUFFICIENT_TOTAL"
    elif not passed:
        reason = "ABSOLUTE_RISK_BOUND_NOT_REACHED"
    else:
        reason = "PASS_ABSOLUTE_RISK_BOUND"
    return {
        "false_accepts": false_accepts,
        "total": total,
        "point_risk": false_accepts / total if total else None,
        "alpha_one_sided": alpha,
        "one_sided_upper_bound": upper,
        "maximum_upper_risk": maximum_upper_risk,
        "minimum_total": minimum_total,
        "pass": passed,
        "reason": reason,
    }


def iter_nested_documents(value: Any, path: str = "") -> Iterator[dict[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "versionedRelease":
                continue
            child_path = f"{path}.{key}" if path else str(key)
            if key == "documents" and isinstance(child, list):
                for item in child:
                    if isinstance(item, Mapping):
                        record = dict(item)
                        record["_path"] = child_path
                        yield record
            else:
                yield from iter_nested_documents(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_nested_documents(child, f"{path}[{index}]")


def parent_institution(compiled_release: Mapping[str, Any]) -> str:
    parties = compiled_release.get("parties") or []
    parents: list[str] = []
    buyers: list[str] = []
    for party in parties:
        if not isinstance(party, Mapping) or "buyer" not in (party.get("roles") or []):
            continue
        name = normalize_name(str(party.get("name") or ""))
        member_of = party.get("memberOf") or []
        if member_of and isinstance(member_of[0], Mapping):
            parent = normalize_name(str(member_of[0].get("name") or ""))
            if parent:
                parents.append(parent)
        elif name:
            buyers.append(name)
    for values in (parents, buyers):
        if values:
            return sorted(values, key=lambda item: (len(item), item.casefold()), reverse=True)[0]
    buyer = compiled_release.get("buyer") or {}
    return normalize_name(str(buyer.get("name") or "UNKNOWN_INSTITUTION")) or "UNKNOWN_INSTITUTION"


def extract_record_documents(record: Mapping[str, Any], api_page: int) -> list[dict[str, Any]]:
    compiled = record.get("compiledRelease") or {}
    if not isinstance(compiled, Mapping):
        return []
    institution = parent_institution(compiled)
    ocid = normalize_name(str(record.get("ocid") or compiled.get("ocid") or ""))
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in iter_nested_documents(compiled):
        url = normalize_name(str(document.get("url") or ""))
        if not url or url in seen or not PDF_URL_RE.search(urlparse(url).path):
            continue
        seen.add(url)
        doc_type = normalize_name(str(document.get("documentType") or "unknown"))
        output.append(
            {
                "url": url,
                "ocid": ocid,
                "institution": institution,
                "document_id": str(document.get("id") or ""),
                "document_type": doc_type,
                "document_type_priority": DOCUMENT_TYPE_PRIORITY.get(doc_type, 9),
                "title": normalize_name(str(document.get("title") or document.get("description") or "")),
                "date_published": str(document.get("datePublished") or ""),
                "ocds_path": str(document.get("_path") or ""),
                "api_page": api_page,
            }
        )
    output.sort(
        key=lambda row: (
            row["document_type_priority"],
            deterministic_key("document", row["ocid"], row["url"]),
        )
    )
    return output


def max_image_coverage(page: fitz.Page) -> float:
    page_area = max(float(page.rect.get_area()), 1.0)
    maximum = 0.0
    try:
        for image in page.get_images(full=True):
            xref = int(image[0])
            for rect in page.get_image_rects(xref):
                maximum = max(maximum, float(rect.get_area()) / page_area)
    except Exception:
        return 1.0
    return maximum


@dataclass(frozen=True)
class DigitRun:
    page_index: int
    bbox: tuple[float, float, float, float]
    truth: str
    font_name: str
    font_size: float
    span_flags: int

    def selector_key(self, document_sha256: str) -> str:
        payload = {
            "document_sha256": document_sha256,
            "page_index": self.page_index,
            "bbox": [round(value, 4) for value in self.bbox],
            "truth": self.truth,
            "font_name": self.font_name,
            "font_size": round(self.font_size, 3),
        }
        return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _flush_digit_run(
    chars: list[Mapping[str, Any]],
    *,
    page_index: int,
    font_name: str,
    font_size: float,
    span_flags: int,
    minimum_length: int,
    maximum_length: int,
    minimum_distinct_digits: int,
    minimum_font_size: float,
) -> DigitRun | None:
    if not chars:
        return None
    truth = "".join(str(char.get("c") or "") for char in chars)
    if not truth.isdigit() or not (minimum_length <= len(truth) <= maximum_length):
        return None
    if len(set(truth)) < minimum_distinct_digits:
        return None
    boxes = [char.get("bbox") for char in chars]
    if any(not isinstance(box, (list, tuple)) or len(box) != 4 for box in boxes):
        return None
    x0 = min(float(box[0]) for box in boxes)
    y0 = min(float(box[1]) for box in boxes)
    x1 = max(float(box[2]) for box in boxes)
    y1 = max(float(box[3]) for box in boxes)
    if x1 <= x0 or y1 <= y0 or font_size < minimum_font_size:
        return None
    return DigitRun(
        page_index=page_index,
        bbox=(x0, y0, x1, y1),
        truth=truth,
        font_name=font_name,
        font_size=font_size,
        span_flags=span_flags,
    )


def extract_digit_runs(
    pdf_bytes: bytes,
    *,
    maximum_pages: int = 15,
    minimum_length: int = 4,
    maximum_length: int = 12,
    minimum_distinct_digits: int = 2,
    minimum_font_size: float = 7.0,
    maximum_full_page_image_coverage: float = 0.55,
) -> tuple[list[DigitRun], dict[str, Any]]:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    if document.needs_pass:
        document.close()
        return [], {"reason": "ENCRYPTED", "pages": 0}
    runs: list[DigitRun] = []
    page_summaries: list[dict[str, Any]] = []
    for page_index in range(min(len(document), maximum_pages)):
        page = document[page_index]
        coverage = max_image_coverage(page)
        if coverage > maximum_full_page_image_coverage:
            page_summaries.append(
                {"page_index": page_index, "image_coverage": coverage, "eligible": False, "runs": 0}
            )
            continue
        raw = page.get_text("rawdict", sort=True)
        page_runs: list[DigitRun] = []
        for block in raw.get("blocks") or []:
            if not isinstance(block, Mapping) or int(block.get("type", 0)) != 0:
                continue
            for line in block.get("lines") or []:
                for span in line.get("spans") or []:
                    chars = span.get("chars") or []
                    current: list[Mapping[str, Any]] = []
                    for char in chars:
                        value = str(char.get("c") or "")
                        if len(value) == 1 and value.isdigit():
                            current.append(char)
                            continue
                        run = _flush_digit_run(
                            current,
                            page_index=page_index,
                            font_name=normalize_name(str(span.get("font") or "")),
                            font_size=float(span.get("size") or 0.0),
                            span_flags=int(span.get("flags") or 0),
                            minimum_length=minimum_length,
                            maximum_length=maximum_length,
                            minimum_distinct_digits=minimum_distinct_digits,
                            minimum_font_size=minimum_font_size,
                        )
                        if run:
                            page_runs.append(run)
                        current = []
                    run = _flush_digit_run(
                        current,
                        page_index=page_index,
                        font_name=normalize_name(str(span.get("font") or "")),
                        font_size=float(span.get("size") or 0.0),
                        span_flags=int(span.get("flags") or 0),
                        minimum_length=minimum_length,
                        maximum_length=maximum_length,
                        minimum_distinct_digits=minimum_distinct_digits,
                        minimum_font_size=minimum_font_size,
                    )
                    if run:
                        page_runs.append(run)
        unique: dict[tuple[Any, ...], DigitRun] = {}
        for run in page_runs:
            key = (run.truth, *(round(value, 2) for value in run.bbox))
            unique[key] = run
        page_runs = list(unique.values())
        runs.extend(page_runs)
        page_summaries.append(
            {"page_index": page_index, "image_coverage": coverage, "eligible": True, "runs": len(page_runs)}
        )
    pages = len(document)
    document.close()
    return runs, {"reason": "OK", "pages": pages, "page_summaries": page_summaries}


def iou_and_cover(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    ax0, ay0, ax1, ay1 = map(float, a)
    bx0, by0, bx1, by1 = map(float, b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1e-9, (bx1 - bx0) * (by1 - by0))
    union = area_a + area_b - intersection
    return intersection / union, intersection / area_a, intersection / area_b


def match_ocr_claim(
    truth_bbox: Sequence[float],
    ocr_tokens: Sequence[Mapping[str, Any]],
    *,
    minimum_truth_coverage: float = 0.35,
) -> Mapping[str, Any] | None:
    tx0, ty0, tx1, ty1 = map(float, truth_bbox)
    truth_center = ((tx0 + tx1) / 2.0, (ty0 + ty1) / 2.0)
    ranked: list[tuple[float, float, Mapping[str, Any], dict[str, float]]] = []
    for token in ocr_tokens:
        bbox = token.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        digits = canonical_digits(str(token.get("text") or ""))
        if not digits:
            continue
        iou, truth_cover, token_cover = iou_and_cover(truth_bbox, bbox)
        bx0, by0, bx1, by1 = map(float, bbox)
        center = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
        center_distance = math.hypot(center[0] - truth_center[0], center[1] - truth_center[1])
        if truth_cover < minimum_truth_coverage and not (
            bx0 <= truth_center[0] <= bx1 and by0 <= truth_center[1] <= by1
        ):
            continue
        score = 3.0 * truth_cover + token_cover + 0.5 * iou - 0.001 * center_distance
        confidence = float(token.get("confidence") or -1)
        ranked.append(
            (
                score,
                confidence,
                token,
                {
                    "iou": iou,
                    "truth_coverage": truth_cover,
                    "token_coverage": token_cover,
                    "center_distance": center_distance,
                    "score": score,
                },
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, token, metrics = ranked[0]
    result = dict(token)
    result["match"] = metrics
    return result


def stable_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def verify_manifest_hash(manifest: Mapping[str, Any]) -> bool:
    expected = str(manifest.get("manifest_sha256") or "")
    rebuilt = dict(manifest)
    rebuilt.pop("manifest_sha256", None)
    observed = sha256_bytes(canonical_json(rebuilt).encode("utf-8"))
    return bool(expected) and expected == observed
