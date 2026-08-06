from __future__ import annotations

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from facts_contract import canonical_json_bytes, normalize_ascii, normalize_space, sha256_file


class AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []
        self.page_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() == "a":
            attributes = {str(key).casefold(): str(value) for key, value in attrs if value is not None}
            self._href = attributes.get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        self.page_parts.append(data)
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            self.anchors.append({"href": self._href, "text": normalize_space(" ".join(self._parts))})
            self._href = None
            self._parts = []


def _normalized_tokens(text: str) -> str:
    return normalize_space(normalize_ascii(text).upper().replace("-", " "))


def discover(
    html_path: Path,
    landing_url: str,
    visible_title: str,
    visible_date: str,
    allowed_hosts: tuple[str, ...],
    output: Path,
) -> dict[str, object]:
    html = html_path.read_text(encoding="utf-8", errors="strict")
    parser = AnchorCollector()
    parser.feed(html)
    page_text = _normalized_tokens(" ".join(parser.page_parts))
    title_tokens = _normalized_tokens(visible_title)
    date_year, date_month, date_day = visible_date.split("-")
    date_variants = {
        _normalized_tokens(f"Jul {int(date_day)}, {date_year}") if date_month == "07" else "",
        _normalized_tokens(f"{date_day}/{date_month}/{date_year}"),
        _normalized_tokens(f"{date_day}-{date_month}-{date_year}"),
        _normalized_tokens(f"{date_year}-{date_month}-{date_day}"),
    }
    allowed = {host.rstrip(".").casefold() for host in allowed_hosts}
    candidates: dict[str, list[str]] = {}
    for anchor in parser.anchors:
        absolute = urljoin(landing_url, anchor["href"])
        parsed = urlparse(absolute)
        normalized_text = _normalized_tokens(anchor["text"])
        is_relevant = "DESCARGA" in normalized_text or title_tokens in normalized_text
        if not is_relevant:
            continue
        if parsed.scheme.casefold() != "https" or (parsed.hostname or "").rstrip(".").casefold() not in allowed:
            continue
        if not parsed.path.casefold().endswith(".pdf"):
            continue
        candidates.setdefault(absolute, []).append(anchor["text"])
    checks = {
        "visible_title_present": title_tokens in page_text,
        "visible_date_present": any(variant and variant in page_text for variant in date_variants),
        "exactly_one_pdf_binding": len(candidates) == 1,
        "landing_host_allowlisted": (urlparse(landing_url).hostname or "").rstrip(".").casefold() in allowed,
    }
    if not all(checks.values()):
        raise RuntimeError(f"landing-page authority gate failed: {checks}; candidates={sorted(candidates)}")
    pdf_url = next(iter(candidates))
    result = {
        "schema": "data-science-pipeline/source-document-binding/1",
        "verdict": "PASS",
        "landing_url": landing_url,
        "landing_sha256": sha256_file(html_path),
        "visible_title": visible_title,
        "visible_publication_date": visible_date,
        "pdf_url": pdf_url,
        "pdf_host": (urlparse(pdf_url).hostname or "").rstrip(".").casefold(),
        "anchor_texts": sorted(set(candidates[pdf_url])),
        "checks": checks,
        "metadata_injected_as_document_facts": False,
    }
    payload = canonical_json_bytes(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--landing-url", required=True)
    parser.add_argument("--visible-title", required=True)
    parser.add_argument("--visible-date", required=True)
    parser.add_argument("--allowed-host", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = discover(
        args.html,
        args.landing_url,
        args.visible_title,
        args.visible_date,
        tuple(args.allowed_host),
        args.output,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
