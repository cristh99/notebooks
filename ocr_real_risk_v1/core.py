"""Pure parsing, deterministic sampling, and exact risk bounds."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import unicodedata
import urllib.parse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

SCHEMA = "ocr-real-risk-holdout/2"
FAMILYWISE_ALPHA = 0.05
BOUND_ALPHA = FAMILYWISE_ALPHA / 2.0
TARGET_REDUCTION = 10.0
MAX_FILE_BYTES = 12_000_000
MIN_NATIVE_WORDS = 25
MIN_DIGITS = 4
MAX_DIGITS = 12
RENDER_DPI = 200
MAX_PAGES_PER_DOCUMENT = 2
MIN_ACCEPTED_FOR_CERTIFICATE = 100
MIN_DOCUMENTS_FOR_CERTIFICATE = 200
MIN_INSTITUTIONS_FOR_CERTIFICATE = 10

PDF_URL_RE = re.compile(r"(?i)\.pdf(?:$|[?#])")
URL_INSTITUTION_RE = re.compile(r"(?i)^(?:Lic|Con)(\d{3,5})")
DIGIT_RE = re.compile(r"^\d{%d,%d}$" % (MIN_DIGITS, MAX_DIGITS))
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")

EXCLUDED_PROCESS_FRAGMENTS = (
    "CDE-SIT-063-2024", "CPN-SIT-042-2023", "CDE-SIT-102-2024",
    "CDE-SIT-002-2024", "LPN-SIT-052-2024", "HN-SEDECOAS-371604-CW-RFB",
    "HN-SEDECOAS-407817-CW-RFB", "LPN-SIT-160-2023", "LPN-FHIS-33-2025",
    "CPN-SIT-054-2023",
)
ALLOWED_DOCUMENT_TYPES = frozenset({
    "tenderNotice", "biddingDocuments", "amendment", "clarifications",
    "recordOpeningTendersReceived", "solicitationDocumentAnnexe",
    "awardNotice", "contractSigned", "contractNotice", "completionCertificate",
    "physicalProgressReport", "financialProgressReport",
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


def normalize_identifier(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(x for x in text if not unicodedata.combining(x)).upper()
    return NON_ALNUM_RE.sub("", text)


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
    institution_name: str
    source_year: int
    source_line: int

    @property
    def key(self) -> str:
        return sha256_bytes(self.url.encode("utf-8"))

    @property
    def partition(self) -> int:
        return int(self.key[:8], 16) % 100


def iter_releases(value: object) -> Iterator[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return
    releases = value.get("releases")
    if isinstance(releases, list):
        yield from (x for x in releases if isinstance(x, Mapping)); return
    records = value.get("records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, Mapping): continue
            compiled = record.get("compiledRelease")
            if isinstance(compiled, Mapping): yield compiled; continue
            nested = record.get("releases")
            if isinstance(nested, list):
                yield from (x for x in nested if isinstance(x, Mapping))
        return
    if "ocid" in value or "id" in value:
        yield value


def iter_source_lines(path: Path) -> Iterator[tuple[int, Mapping[str, Any]]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip(): continue
            try: package = json.loads(raw)
            except json.JSONDecodeError: continue
            for release in iter_releases(package):
                yield line_number, release


def buyer_identity(release: Mapping[str, Any], url: str) -> tuple[str, str]:
    nodes: list[Mapping[str, Any]] = []
    for key in ("buyer", "procuringEntity"):
        node = release.get(key)
        if isinstance(node, Mapping): nodes.append(node)
    parties = release.get("parties")
    if isinstance(parties, list):
        for node in parties:
            if not isinstance(node, Mapping): continue
            roles = {str(x).casefold().replace(" ", "") for x in node.get("roles", [])} if isinstance(node.get("roles"), list) else set()
            if roles & {"buyer", "procuringentity"}: nodes.append(node)
    for node in nodes:
        name = str(node.get("name") or "").strip()
        raw_id = str(node.get("id") or "").strip()
        identifier = node.get("identifier")
        if isinstance(identifier, Mapping):
            raw_id = str(identifier.get("id") or raw_id).strip()
            name = str(identifier.get("legalName") or name).strip()
        code = normalize_identifier(raw_id) or normalize_identifier(name)
        if code: return code[:80], name[:200]
    basename = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    match = URL_INSTITUTION_RE.match(basename)
    return (f"URL{match.group(1)}" if match else "UNKNOWN", "")


def document_nodes(release: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    roots: list[Mapping[str, Any]] = [release]
    for key in ("planning", "tender", "implementation"):
        node = release.get(key)
        if isinstance(node, Mapping): roots.append(node)
    for key in ("awards", "contracts"):
        values = release.get(key)
        if isinstance(values, list):
            for node in values:
                if isinstance(node, Mapping):
                    roots.append(node)
                    implementation = node.get("implementation")
                    if isinstance(implementation, Mapping): roots.append(implementation)
    for root in roots:
        documents = root.get("documents")
        if isinstance(documents, list):
            yield from (x for x in documents if isinstance(x, Mapping))


def parse_candidate_sources(paths: Sequence[Path], *, partitions: frozenset[int] | None = None) -> tuple[list[Candidate], dict[str, Any]]:
    dedup: dict[str, Candidate] = {}
    release_count = invalid_urls = excluded_releases = document_refs = 0
    source_hashes = {str(path): sha256_file(path) for path in paths}
    for path in paths:
        year_match = re.search(r"(20\d{2})", path.name)
        source_year = int(year_match.group(1)) if year_match else 0
        for line_number, release in iter_source_lines(path):
            release_count += 1
            ocid = str(release.get("ocid") or "")
            tender = release.get("tender")
            tender_id = str(tender.get("id") or "") if isinstance(tender, Mapping) else ""
            process = tender_id or ocid
            if any(fragment in process or fragment in ocid for fragment in EXCLUDED_PROCESS_FRAGMENTS):
                excluded_releases += 1; continue
            for document in document_nodes(release):
                document_refs += 1
                url = normalized_url(str(document.get("url") or "").strip())
                dtype = str(document.get("documentType") or "").strip()
                if not url or not PDF_URL_RE.search(url):
                    invalid_urls += 1; continue
                institution_code, institution_name = buyer_identity(release, url)
                candidate = Candidate(
                    url=url, document_type=dtype or "unknown", process=process,
                    ocid=ocid, institution_code=institution_code,
                    institution_name=institution_name, source_year=source_year,
                    source_line=line_number,
                )
                if partitions is not None and candidate.partition not in partitions: continue
                prior = dedup.get(url)
                if prior is None or (candidate.source_year, candidate.source_line, candidate.document_type) < (prior.source_year, prior.source_line, prior.document_type):
                    dedup[url] = candidate
    candidates = sorted(dedup.values(), key=lambda x: (x.key, x.url))
    census = {
        "source_files": source_hashes, "releases": release_count,
        "excluded_development_releases": excluded_releases,
        "document_references": document_refs, "invalid_or_non_pdf_references": invalid_urls,
        "unique_pdf_candidates": len(candidates),
        "institution_count": len({x.institution_code for x in candidates}),
        "institution_codes": dict(sorted(Counter(x.institution_code for x in candidates).items())),
        "document_types": dict(sorted(Counter(x.document_type for x in candidates).items())),
        "partitions": sorted(partitions) if partitions is not None else None,
    }
    return candidates, census


def parse_candidates(source_path: Path) -> tuple[list[Candidate], dict[str, Any]]:
    """Compatibility wrapper for one raw OCDS JSONL or JSONL.GZ source."""
    return parse_candidate_sources([source_path])


def round_robin(candidates: Sequence[Candidate]) -> list[Candidate]:
    groups: dict[str, deque[Candidate]] = defaultdict(deque)
    for candidate in candidates: groups[candidate.institution_code].append(candidate)
    codes = sorted(groups, key=lambda c: (len(groups[c]), c), reverse=True)
    result: list[Candidate] = []
    while any(groups.values()):
        for code in codes:
            if groups[code]: result.append(groups[code].popleft())
    return result


def canonical_truth(text: str) -> str | None:
    value = text.strip().replace(" ", "").strip(".,;:()[]{}")
    if not DIGIT_RE.fullmatch(value) or YEAR_RE.fullmatch(value): return None
    if len(set(value)) == 1 and len(value) >= 6: return None
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


def clopper_pearson_upper(k: int, n: int, alpha: float = BOUND_ALPHA) -> float:
    if n <= 0 or k >= n: return 1.0
    low, high = 0.0, 1.0
    for _ in range(90):
        mid = (low + high) / 2.0
        if binomial_cdf(k, n, mid) > alpha: low = mid
        else: high = mid
    return (low + high) / 2.0


def clopper_pearson_lower(k: int, n: int, alpha: float = BOUND_ALPHA) -> float:
    if n <= 0 or k <= 0: return 0.0
    return 1.0 - clopper_pearson_upper(n - k, n, alpha)


def p95(values: Sequence[float]) -> float | None:
    if not values: return None
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]
