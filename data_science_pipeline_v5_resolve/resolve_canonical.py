from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "data-science-pipeline/resolved-canonical-bundle/1"
UPSTREAM_NORMALIZE_ARTIFACT_ID = 8952699633
UPSTREAM_NORMALIZE_ARTIFACT_SHA256 = "3c2aa0e8551b559ab2540f61a13a1aef3d69d6efec64437721d574f1d38be2d8"
SOURCE_PDF_SHA256 = "5f278ec51106212a95a6f8c135cdfb8376724daab1e49b9ca0d3879543d11e85"

MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

ENTITY_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "entity_id": "hn:institution:oncae",
        "entity_type": "public_institution",
        "canonical_name": "Oficina Normativa de Contratación y Adquisiciones del Estado",
        "aliases": (
            "oficina normativa de contratacion y adquisiciones del estado",
            "oncae",
        ),
    },
    {
        "entity_id": "hn:government:republic",
        "entity_type": "government",
        "canonical_name": "Gobierno de la República de Honduras",
        "aliases": ("gobierno de la republica",),
    },
    {
        "entity_id": "hn:organization:cich",
        "entity_type": "professional_association",
        "canonical_name": "Colegio de Ingenieros Civiles de Honduras",
        "aliases": (
            "colegio de ingenieros civiles de honduras",
            "cich",
        ),
    },
    {
        "entity_id": "hn:organization:educredito",
        "entity_type": "organization_or_building",
        "canonical_name": "EDUCREDITO",
        "aliases": ("educredito",),
    },
    {
        "entity_id": "hn:country:honduras",
        "entity_type": "country",
        "canonical_name": "Honduras",
        "aliases": ("honduras",),
    },
)

LEGAL_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "legal_id": "hn:legal:reglamento-ley-contratacion-estado",
        "legal_type": "regulation",
        "canonical_title": "Reglamento de la Ley de Contratación del Estado",
        "aliases": ("reglamento de la ley de contratacion del estado",),
    },
    {
        "legal_id": "hn:legal:presupuesto-general-2024",
        "legal_type": "budget_law",
        "canonical_title": "Presupuesto General de Ingresos y Egresos de la República — Ejercicio Fiscal 2024",
        "aliases": (
            "presupuesto general de ingresos y egresos de la republica",
            "ejercicio fiscal 2024",
        ),
    },
)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm(value))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    payload = b"".join(canonical_json(dict(row)) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.name,
        "rows": payload.count(b"\n"),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def find_single(root: Path, suffix: str) -> Path:
    matches = [path for path in root.rglob(suffix) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {suffix}, got {len(matches)}")
    return matches[0]


def validate_registry(registry: Sequence[Mapping[str, Any]], id_key: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for item in registry:
        item_id = str(item[id_key])
        for alias in item["aliases"]:
            key = norm(str(alias))
            previous = alias_map.get(key)
            if previous and previous != item_id:
                raise RuntimeError(f"alias collision: {alias!r}: {previous} vs {item_id}")
            alias_map[key] = item_id
    return alias_map


def line_windows(lines: Sequence[Mapping[str, Any]], max_size: int = 3) -> Iterable[tuple[list[Mapping[str, Any]], str]]:
    by_page: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for line in lines:
        by_page[int(line["page_number"])].append(line)
    for page in sorted(by_page):
        page_lines = sorted(by_page[page], key=lambda row: (int(row["block_num"]), int(row["paragraph_num"]), int(row["line_num"]), row["line_id"]))
        for start in range(len(page_lines)):
            for size in range(1, max_size + 1):
                window = page_lines[start : start + size]
                if len(window) != size:
                    continue
                yield window, " ".join(str(row["text"]) for row in window)


def weighted_confidence(lines: Sequence[Mapping[str, Any]]) -> float:
    weights = [max(1, int(row.get("word_count", 1))) for row in lines]
    return sum(float(row["mean_confidence"]) * weight for row, weight in zip(lines, weights)) / sum(weights)


def resolve_entities(lines: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    validate_registry(ENTITY_REGISTRY, "entity_id")
    mentions: dict[tuple[str, str, str], dict[str, Any]] = {}
    collisions: list[dict[str, Any]] = []
    for window, text in line_windows(lines, 3):
        normalized = norm(text)
        matched: list[Mapping[str, Any]] = []
        for entity in ENTITY_REGISTRY:
            if any(norm(alias) in normalized for alias in entity["aliases"]):
                matched.append(entity)
        entity_ids = {str(item["entity_id"]) for item in matched}
        # The country token can legitimately appear inside another organization's name.
        non_country = {item_id for item_id in entity_ids if item_id != "hn:country:honduras"}
        if len(non_country) > 1:
            collisions.append({
                "schema": "entity-collision/1",
                "line_ids": [row["line_id"] for row in window],
                "text": text,
                "candidate_entity_ids": sorted(non_country),
                "resolution": "abstain",
            })
            continue
        for entity in matched:
            entity_id = str(entity["entity_id"])
            # Prefer the shortest evidence window that contains the alias.
            aliases_found = [alias for alias in entity["aliases"] if norm(alias) in normalized]
            if not aliases_found:
                continue
            key = (entity_id, str(window[0]["line_id"]), str(window[-1]["line_id"]))
            candidate = {
                "schema": "canonical-entity-mention/1",
                "mention_id": f"{entity_id}:{window[0]['line_id']}:{window[-1]['line_id']}",
                "entity_id": entity_id,
                "entity_type": entity["entity_type"],
                "canonical_name": entity["canonical_name"],
                "surface_text": text,
                "matched_aliases": sorted(set(str(alias) for alias in aliases_found)),
                "page_number": int(window[0]["page_number"]),
                "start_line_id": window[0]["line_id"],
                "end_line_id": window[-1]["line_id"],
                "line_ids": [row["line_id"] for row in window],
                "confidence": weighted_confidence(window),
                "resolution_method": "deterministic_alias_registry",
                "lineage_parent_sha256": window[0]["lineage_parent_sha256"],
            }
            previous = mentions.get(key)
            if previous is None or len(candidate["surface_text"]) < len(previous["surface_text"]):
                mentions[key] = candidate

    # Remove mention windows that strictly contain a shorter mention for the same entity and page.
    compact_mentions = list(mentions.values())
    retained: list[dict[str, Any]] = []
    for mention in compact_mentions:
        own = set(mention["line_ids"])
        dominated = False
        for other in compact_mentions:
            if other is mention or other["entity_id"] != mention["entity_id"] or other["page_number"] != mention["page_number"]:
                continue
            other_set = set(other["line_ids"])
            if other_set < own:
                dominated = True
                break
        if not dominated:
            retained.append(mention)
    retained.sort(key=lambda row: (row["entity_id"], row["page_number"], row["start_line_id"], row["end_line_id"]))

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mention in retained:
        grouped[mention["entity_id"]].append(mention)
    entities: list[dict[str, Any]] = []
    registry_by_id = {str(item["entity_id"]): item for item in ENTITY_REGISTRY}
    for entity_id in sorted(grouped):
        evidence = grouped[entity_id]
        spec = registry_by_id[entity_id]
        entities.append({
            "schema": "canonical-entity/1",
            "entity_id": entity_id,
            "entity_type": spec["entity_type"],
            "canonical_name": spec["canonical_name"],
            "aliases": sorted(set(alias for mention in evidence for alias in mention["matched_aliases"])),
            "mention_count": len(evidence),
            "mean_confidence": sum(item["confidence"] for item in evidence) / len(evidence),
            "evidence_mention_ids": [item["mention_id"] for item in evidence],
            "resolution_status": "resolved",
        })
    return entities, retained, sorted(collisions, key=lambda row: (row["line_ids"], row["candidate_entity_ids"]))


def resolve_dates(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    month_pattern = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b", re.IGNORECASE)
    for line in lines:
        text = str(line["text"])
        normalized = norm(text)
        for match in month_pattern.finditer(normalized):
            month_name = match.group(1).casefold()
            year = int(match.group(2))
            value = f"{year:04d}-{MONTHS[month_name]:02d}"
            key = (str(line["line_id"]), value)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "schema": "canonical-date-mention/1",
                "date_id": f"{line['line_id']}:date:{value}",
                "value": value,
                "precision": "month",
                "surface_text": match.group(0),
                "page_number": int(line["page_number"]),
                "line_id": line["line_id"],
                "confidence": float(line["mean_confidence"]),
                "resolution_method": "month_year_pattern",
                "lineage_parent_sha256": line["lineage_parent_sha256"],
            })
    return sorted(rows, key=lambda row: (row["value"], row["line_id"]))


def resolve_legal(lines: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validate_registry(LEGAL_REGISTRY, "legal_id")
    mentions: list[dict[str, Any]] = []
    for window, text in line_windows(lines, 2):
        normalized = norm(text)
        for legal in LEGAL_REGISTRY:
            aliases = [alias for alias in legal["aliases"] if norm(alias) in normalized]
            if not aliases:
                continue
            mentions.append({
                "schema": "canonical-legal-reference/1",
                "legal_id": legal["legal_id"],
                "legal_type": legal["legal_type"],
                "canonical_title": legal["canonical_title"],
                "surface_text": text,
                "matched_aliases": sorted(set(aliases)),
                "page_number": int(window[0]["page_number"]),
                "line_ids": [row["line_id"] for row in window],
                "confidence": weighted_confidence(window),
                "resolution_status": "resolved",
                "lineage_parent_sha256": window[0]["lineage_parent_sha256"],
            })
    # Explicit decree identifiers are separate legal references.
    decree_pattern = re.compile(r"\b(?:decretos?\s+legislativos?\s+)?(\d{1,4})\s*[-–]\s*(20\d{2})\b", re.IGNORECASE)
    for line in lines:
        normalized = norm(str(line["text"]))
        for match in decree_pattern.finditer(normalized):
            number, year = match.group(1), match.group(2)
            mentions.append({
                "schema": "canonical-legal-reference/1",
                "legal_id": f"hn:decree:{number}-{year}",
                "legal_type": "legislative_decree",
                "canonical_title": f"Decreto Legislativo {number}-{year}",
                "surface_text": match.group(0),
                "matched_aliases": [match.group(0)],
                "page_number": int(line["page_number"]),
                "line_ids": [line["line_id"]],
                "confidence": float(line["mean_confidence"]),
                "resolution_status": "resolved",
                "lineage_parent_sha256": line["lineage_parent_sha256"],
            })
    unique: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for mention in mentions:
        key = (str(mention["legal_id"]), tuple(mention["line_ids"]))
        previous = unique.get(key)
        if previous is None or len(mention["surface_text"]) < len(previous["surface_text"]):
            unique[key] = mention
    resolved = sorted(unique.values(), key=lambda row: (row["legal_id"], row["line_ids"]))
    legal_entities: dict[str, dict[str, Any]] = {}
    for mention in resolved:
        item = legal_entities.setdefault(str(mention["legal_id"]), {
            "schema": "canonical-legal-instrument/1",
            "legal_id": mention["legal_id"],
            "legal_type": mention["legal_type"],
            "canonical_title": mention["canonical_title"],
            "mention_count": 0,
            "evidence_line_ids": [],
            "resolution_status": "resolved",
        })
        item["mention_count"] += 1
        item["evidence_line_ids"].extend(mention["line_ids"])
    for item in legal_entities.values():
        item["evidence_line_ids"] = sorted(set(item["evidence_line_ids"]))
    return sorted(legal_entities.values(), key=lambda row: row["legal_id"]), resolved


def resolve_contacts(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    phone_pattern = re.compile(r"\+?504[\s-]*(\d{4})[\s-]*(\d{4})")
    rows: list[dict[str, Any]] = []
    for line in lines:
        for match in phone_pattern.finditer(str(line["text"])):
            canonical = f"+504-{match.group(1)}-{match.group(2)}"
            rows.append({
                "schema": "canonical-contact/1",
                "contact_id": f"phone:{canonical}",
                "contact_type": "phone",
                "canonical_value": canonical,
                "surface_text": match.group(0),
                "page_number": int(line["page_number"]),
                "line_id": line["line_id"],
                "confidence": float(line["mean_confidence"]),
                "lineage_parent_sha256": line["lineage_parent_sha256"],
            })
    unique = {(row["contact_id"], row["line_id"]): row for row in rows}
    return sorted(unique.values(), key=lambda row: (row["contact_id"], row["line_id"]))


def resolve_amounts(lines: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Fail closed: a number is money only with an explicit currency marker.
    pattern = re.compile(
        r"(?:(?:L|HNL|USD|US\$|\$)\s*[-:]?\s*(\d[\d.,]*))|(?:(\d[\d.,]*)\s*(?:lempiras?|dolares?|dólares?))",
        re.IGNORECASE,
    )
    rows: list[dict[str, Any]] = []
    for line in lines:
        for match in pattern.finditer(str(line["text"])):
            raw_number = match.group(1) or match.group(2)
            cleaned = raw_number.replace(",", "")
            try:
                value = float(cleaned)
            except ValueError:
                continue
            currency = "HNL" if re.search(r"\b(?:L|HNL|lempiras?)\b", match.group(0), re.IGNORECASE) else "USD"
            rows.append({
                "schema": "canonical-amount/1",
                "amount_id": f"{line['line_id']}:amount:{currency}:{value:.2f}",
                "value": value,
                "currency": currency,
                "surface_text": match.group(0),
                "page_number": int(line["page_number"]),
                "line_id": line["line_id"],
                "confidence": float(line["mean_confidence"]),
                "resolution_status": "resolved",
                "lineage_parent_sha256": line["lineage_parent_sha256"],
            })
    abstentions: list[dict[str, Any]] = []
    if not rows:
        abstentions.append({
            "schema": "resolution-abstention/1",
            "field_type": "amount",
            "reason_code": "NO_CURRENCY_QUALIFIED_AMOUNT",
            "detail": "No number had sufficient explicit currency context; years, page numbers, decree numbers and phone digits were not treated as money.",
            "resolution_status": "abstained",
        })
    return sorted(rows, key=lambda row: (row["currency"], row["value"], row["line_id"])), abstentions


def resolve_bundle(bundle_root: Path, output_dir: Path) -> dict[str, Any]:
    repaired_receipt = find_single(bundle_root, "repaired-receipt.json")
    repaired = json.loads(repaired_receipt.read_text(encoding="utf-8"))
    if repaired.get("verdict") != "PASS" or repaired.get("sealed_source_artifact_id") != 8952669318:
        raise RuntimeError("upstream normalization receipt is not the expected PASS")
    lines_path = find_single(bundle_root, "output-a/lines.jsonl")
    words_path = find_single(bundle_root, "output-a/words.jsonl")
    pages_path = find_single(bundle_root, "output-a/pages.jsonl")
    documents_path = find_single(bundle_root, "output-a/documents.jsonl")
    lines = load_jsonl(lines_path)
    words = load_jsonl(words_path)
    pages = load_jsonl(pages_path)
    documents = load_jsonl(documents_path)
    if len(documents) != 1 or len(pages) != 3 or len(lines) != 99 or len(words) != 461:
        raise RuntimeError("upstream canonical cardinality mismatch")
    if documents[0].get("source_sha256") != SOURCE_PDF_SHA256:
        raise RuntimeError("unexpected source PDF")

    entities, entity_mentions, entity_collisions = resolve_entities(lines)
    dates = resolve_dates(lines)
    legal_instruments, legal_mentions = resolve_legal(lines)
    contacts = resolve_contacts(lines)
    amounts, abstentions = resolve_amounts(lines)

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "entities.jsonl": write_jsonl(output_dir / "entities.jsonl", entities),
        "entity_mentions.jsonl": write_jsonl(output_dir / "entity_mentions.jsonl", entity_mentions),
        "entity_collisions.jsonl": write_jsonl(output_dir / "entity_collisions.jsonl", entity_collisions),
        "dates.jsonl": write_jsonl(output_dir / "dates.jsonl", dates),
        "legal_instruments.jsonl": write_jsonl(output_dir / "legal_instruments.jsonl", legal_instruments),
        "legal_mentions.jsonl": write_jsonl(output_dir / "legal_mentions.jsonl", legal_mentions),
        "contacts.jsonl": write_jsonl(output_dir / "contacts.jsonl", contacts),
        "amounts.jsonl": write_jsonl(output_dir / "amounts.jsonl", amounts),
        "abstentions.jsonl": write_jsonl(output_dir / "abstentions.jsonl", abstentions),
    }
    entity_ids = {row["entity_id"] for row in entities}
    legal_ids = {row["legal_id"] for row in legal_instruments}
    checks = {
        "upstream_pass_verified": True,
        "canonical_cardinality_verified": True,
        "oncae_resolved": "hn:institution:oncae" in entity_ids,
        "cich_resolved": "hn:organization:cich" in entity_ids,
        "month_year_resolved": any(row["value"] == "2024-11" for row in dates),
        "regulation_resolved": "hn:legal:reglamento-ley-contratacion-estado" in legal_ids,
        "decree_62_2023_resolved": "hn:decree:62-2023" in legal_ids,
        "phone_resolved": any(row["canonical_value"] == "+504-2209-5355" for row in contacts),
        "no_unqualified_money": not amounts,
        "amount_abstention_present": any(row["reason_code"] == "NO_CURRENCY_QUALIFIED_AMOUNT" for row in abstentions),
        "entity_collisions_zero": not entity_collisions,
        "every_mention_has_lineage": all(row.get("line_ids") and row.get("lineage_parent_sha256") for row in entity_mentions + legal_mentions),
        "external_cost_usd": 0.0,
    }
    manifest = {
        "schema": SCHEMA,
        "upstream": {
            "artifact_id": UPSTREAM_NORMALIZE_ARTIFACT_ID,
            "artifact_zip_sha256": UPSTREAM_NORMALIZE_ARTIFACT_SHA256,
            "repaired_receipt_sha256": sha256_file(repaired_receipt),
            "documents_sha256": sha256_file(documents_path),
            "pages_sha256": sha256_file(pages_path),
            "lines_sha256": sha256_file(lines_path),
            "words_sha256": sha256_file(words_path),
            "source_pdf_sha256": documents[0]["source_sha256"],
        },
        "row_counts": {
            "entities": len(entities),
            "entity_mentions": len(entity_mentions),
            "entity_collisions": len(entity_collisions),
            "dates": len(dates),
            "legal_instruments": len(legal_instruments),
            "legal_mentions": len(legal_mentions),
            "contacts": len(contacts),
            "amounts": len(amounts),
            "abstentions": len(abstentions),
        },
        "checks": checks,
        "outputs": outputs,
    }
    payload = canonical_json(manifest)
    (output_dir / "resolve-manifest.json").write_bytes(payload)
    (output_dir / "resolve-manifest.sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  resolve-manifest.json\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(resolve_bundle(args.bundle, args.output), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
