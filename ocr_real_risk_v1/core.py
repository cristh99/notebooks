"""Pure parsing, sampling and exact-risk helpers."""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "ocr-real-risk-holdout/1"
ALPHA = 0.05
TARGET_REDUCTION = 10.0
MAX_FILE_BYTES = 12_000_000
MIN_NATIVE_WORDS = 25
MIN_DIGITS = 4
MAX_DIGITS = 12
RENDER_DPI = 200
MAX_PAGES_PER_DOCUMENT = 2

PDF_URL_RE = re.compile(r"(?i)\.pdf(?:$|[?#])")
INSTITUTION_RE = re.compile(r"(?i)^(?:Lic|Con)(\d{3,5})")
DIGIT_RE = re.compile(r"^\d{%d,%d}$" % (MIN_DIGITS, MAX_DIGITS))
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")

EXCLUDED_PROCESS_FRAGMENTS = (
    "CDE-SIT-063-2024", "CPN-SIT-042-2023", "CDE-SIT-102-2024",
    "CDE-SIT-002-2024", "LPN-SIT-052-2024", "HN-SEDECOAS-371604-CW-RFB",
    "HN-SEDECOAS-407817-CW-RFB", "LPN-SIT-160-2023", "LPN-FHIS-33-2025",
    "CPN-SIT-054-2023",
)
ALLOWED_DOCUMENT_TYPES = frozenset({
    "tenderNotice", "biddingDocuments", "amendment", "clarifications",
    "recordOpeningTendersReceived", "solicitationDocumentAnnexe",
    "awardNotice", "contractSigned",
})


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


def normalized_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%._-()")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


@dataclass(frozen=True)
class Candidate:
    url: str
    document_type: str
    process: str
    ocid: str
    institution_code: str
    source_line: int
    object_text_sha256: str

    @property
    def key(self) -> str:
        return sha256_bytes(self.url.encode("utf-8"))


def parse_candidates(source_path: Path) -> tuple[list[Candidate], dict[str, Any]]:
    dedup: dict[str, Candidate] = {}
    records = invalid = excluded_count = 0
    for line_number, raw_line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        records += 1
        process = str(record.get("shared_code") or record.get("ocid_oncae") or "")
        ocid = str(record.get("ocid_oncae") or "")
        object_text = str(record.get("oncae_object_text") or "")
        if any(x in process or x in ocid or x in object_text for x in EXCLUDED_PROCESS_FRAGMENTS):
            excluded_count += 1
            continue
        for document in record.get("oncae_documents") or []:
            url = normalized_url(str(document.get("url") or ""))
            dtype = str(document.get("documentType") or "")
            if dtype not in ALLOWED_DOCUMENT_TYPES or not PDF_URL_RE.search(url):
                continue
            basename = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
            match = INSTITUTION_RE.match(basename)
            candidate = Candidate(
                url=url, document_type=dtype, process=process, ocid=ocid,
                institution_code=match.group(1) if match else "UNKNOWN",
                source_line=line_number,
                object_text_sha256=sha256_bytes(object_text.encode("utf-8")),
            )
            prior = dedup.get(url)
            if prior is None or (candidate.source_line, dtype) < (prior.source_line, prior.document_type):
                dedup[url] = candidate
    candidates = sorted(dedup.values(), key=lambda x: (x.key, x.url))
    census = {
        "source_records": records,
        "invalid_json_lines": invalid,
        "excluded_development_records": excluded_count,
        "unique_pdf_candidates": len(candidates),
        "institution_codes": dict(sorted(Counter(x.institution_code for x in candidates).items())),
        "document_types": dict(sorted(Counter(x.document_type for x in candidates).items())),
    }
    return candidates, census


def round_robin(candidates: Sequence[Candidate]) -> list[Candidate]:
    groups: dict[str, deque[Candidate]] = defaultdict(deque)
    for candidate in candidates:
        groups[candidate.institution_code].append(candidate)
    codes = sorted(groups, key=lambda c: (len(groups[c]), c), reverse=True)
    result: list[Candidate] = []
    while any(groups.values()):
        for code in codes:
            if groups[code]:
                result.append(groups[code].popleft())
    return result


def canonical_truth(text: str) -> str | None:
    value = text.strip().replace(" ", "").strip(".,;:()[]{}")
    if not DIGIT_RE.fullmatch(value) or YEAR_RE.fullmatch(value):
        return None
    if len(set(value)) == 1 and len(value) >= 6:
        return None
    return value


def mutate_one_digit(value: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    index = digest[0] % len(value)
    replacement = str((int(value[index]) + 1 + digest[1] % 9) % 10)
    return value[:index] + replacement + value[index + 1:]


def binomial_cdf(k: int, n: int, p: float) -> float:
    if k < 0: return 0.0
    if k >= n: return 1.0
    if p <= 0.0: return 1.0
    if p >= 1.0: return 0.0
    probability = (1.0 - p) ** n
    total, ratio = probability, p / (1.0 - p)
    for x in range(k):
        probability *= (n - x) / (x + 1) * ratio
        total += probability
    return min(1.0, max(0.0, total))


def clopper_pearson_upper(k: int, n: int, alpha: float = ALPHA) -> float:
    if n <= 0 or k >= n: return 1.0
    low, high = 0.0, 1.0
    for _ in range(90):
        mid = (low + high) / 2.0
        if binomial_cdf(k, n, mid) > alpha: low = mid
        else: high = mid
    return (low + high) / 2.0


def clopper_pearson_lower(k: int, n: int, alpha: float = ALPHA) -> float:
    if n <= 0 or k <= 0: return 0.0
    return 1.0 - clopper_pearson_upper(n - k, n, alpha)


def p95(values: Sequence[float]) -> float | None:
    if not values: return None
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]
