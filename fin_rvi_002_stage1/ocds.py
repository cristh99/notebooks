from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Iterator, Mapping, Sequence

_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_TOKEN_RE = re.compile(r"[A-Z0-9]{2,}")

_NAME_STOPWORDS = {
    "DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "E", "EN", "PARA", "POR",
    "S", "R", "L", "SA", "SAS", "SRL", "RL", "LTDA", "CIA", "COMPANIA", "SOCIEDAD",
    "ANONIMA", "LIMITADA", "HONDURAS", "HONDURENA", "HONDURENO",
}

_OBJECT_STOPWORDS = {
    "DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "E", "EN", "PARA", "POR",
    "CON", "SIN", "UN", "UNA", "UNOS", "UNAS", "AL", "A", "O", "U", "QUE",
    "SE", "SU", "SUS", "COMPRA", "ADQUISICION", "CONTRATACION", "SERVICIO",
    "SERVICIOS", "SUMINISTRO", "SUMINISTROS", "PROCESO", "CONTRATO", "PAGO",
    "ORDEN", "PROYECTO", "PROGRAMA", "ACTIVIDAD", "GASTO", "PUBLICO", "PUBLICA",
    "SECRETARIA", "DIRECCION", "UNIDAD", "HONDURAS", "HONDURENA", "HONDURENO",
}

_CATEGORY_LEXICONS: dict[str, set[str]] = {
    "TECH_HARDWARE": {
        "IMPRESORA", "IMPRESORAS", "TABLETA", "TABLETAS", "COMPUTADORA", "COMPUTADORAS",
        "LAPTOP", "LAPTOPS", "MONITOR", "MONITORES", "TECLADO", "TECLADOS",
        "EQUIPO", "INFORMATICO", "INFORMATICA", "HARDWARE", "ESCANER", "SERVIDOR",
    },
    "SOFTWARE": {
        "ADOBE", "LICENCIA", "LICENCIAS", "SOFTWARE", "SUSCRIPCION", "SUSCRIPCIONES",
        "CLOUD", "ACROBAT", "PHOTOSHOP", "OFFICE", "ANTIVIRUS", "SISTEMA",
    },
    "FURNITURE": {
        "SILLA", "SILLAS", "MESA", "MESAS", "ESCRITORIO", "ESCRITORIOS", "MUEBLE",
        "MUEBLES", "ARCHIVADOR", "ESTANTE", "BUTACA",
    },
    "TOOLS": {
        "HERRAMIENTA", "HERRAMIENTAS", "TALADRO", "MARTILLO", "LLAVE", "SIERRA",
        "EQUIPO", "FERRETERIA", "MATERIAL", "CONSTRUCCION",
    },
    "DENTAL": {
        "CEPILLO", "CEPILLOS", "DENTAL", "DENTALES", "PASTA", "ODONTOLOGICO",
        "ODONTOLOGIA", "HIGIENE", "BUCAL",
    },
    "FOOD": {
        "ALIMENTO", "ALIMENTOS", "COMIDA", "ARROZ", "FRIJOL", "FRIJOLES", "LECHE",
        "ACEITE", "HARINA", "AZUCAR", "RACION", "RACIONES", "MERIENDA", "CANASTA",
    },
    "CONSTRUCTION": {
        "OBRA", "OBRAS", "CONSTRUCCION", "REHABILITACION", "REPOSICION", "PAVIMENTO",
        "CARRETERA", "PUENTE", "AGUA", "POTABLE", "ALCANTARILLADO", "EDIFICIO",
        "INFRAESTRUCTURA", "MEJORAMIENTO", "MANTENIMIENTO",
    },
    "CONSULTING": {
        "CONSULTORIA", "CONSULTOR", "SUPERVISION", "ESTUDIO", "DISENO", "ASESORIA",
        "ASISTENCIA", "TECNICA", "AUDITORIA", "CAPACITACION",
    },
    "PUBLICATION": {
        "PUBLICACION", "PUBLICAR", "PERIODICO", "DIARIO", "AVISO", "PRENSA",
        "LICITACION", "ANUNCIO",
    },
    "TRAVEL": {
        "VIATICO", "VIATICOS", "VIAJE", "VIAJES", "COMBUSTIBLE", "GIRA", "VISITA",
        "TRANSPORTE", "ALOJAMIENTO", "ALIMENTACION",
    },
}

_GENERIC_CATEGORIES = {"TOOLS"}


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = strip_accents(str(value)).upper().strip()
    text = _NON_ALNUM_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def normalize_name(value: object) -> str:
    tokens = [token for token in normalize_text(value).split() if token not in _NAME_STOPWORDS]
    return " ".join(tokens)


def normalize_identifier(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_payload(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def iter_releases(package: object) -> Iterator[Mapping[str, Any]]:
    """Yield OCDS releases from release packages, record packages, or bare releases."""
    if not isinstance(package, Mapping):
        return
    releases = package.get("releases")
    if isinstance(releases, list):
        for release in releases:
            if isinstance(release, Mapping):
                yield release
        return
    records = package.get("records")
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, Mapping):
                continue
            compiled = record.get("compiledRelease")
            if isinstance(compiled, Mapping):
                yield compiled
                continue
            record_releases = record.get("releases")
            if isinstance(record_releases, list):
                for release in record_releases:
                    if isinstance(release, Mapping):
                        yield release
        return
    if "ocid" in package or "id" in package:
        yield package


def _identifier_keys(entity: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    names: set[str] = set()
    raw_id = entity.get("id")
    if raw_id:
        normalized = normalize_identifier(raw_id)
        if len(normalized) >= 5:
            ids.add(f"RAW:{normalized}")
    raw_name = entity.get("name")
    if raw_name:
        normalized_name = normalize_name(raw_name)
        if normalized_name:
            names.add(normalized_name)
    identifier_nodes: list[Mapping[str, Any]] = []
    identifier = entity.get("identifier")
    if isinstance(identifier, Mapping):
        identifier_nodes.append(identifier)
    additional = entity.get("additionalIdentifiers")
    if isinstance(additional, list):
        identifier_nodes.extend(node for node in additional if isinstance(node, Mapping))
    for node in identifier_nodes:
        scheme = normalize_identifier(node.get("scheme")) or "UNKNOWN"
        identifier_id = normalize_identifier(node.get("id"))
        if identifier_id:
            ids.add(f"{scheme}:{identifier_id}")
        legal_name = normalize_name(node.get("legalName"))
        if legal_name:
            names.add(legal_name)
    return ids, names


def _add_party(entity: object, ids: set[str], names: set[str]) -> None:
    if not isinstance(entity, Mapping):
        return
    entity_ids, entity_names = _identifier_keys(entity)
    ids.update(entity_ids)
    names.update(entity_names)


def _roles(party: Mapping[str, Any]) -> set[str]:
    roles = party.get("roles")
    if isinstance(roles, list):
        return {normalize_text(role).lower() for role in roles}
    if isinstance(roles, str):
        return {normalize_text(roles).lower()}
    return set()


def _add_value(values: list[float], node: object) -> None:
    if not isinstance(node, Mapping):
        return
    amount = node.get("amount")
    if isinstance(amount, (int, float)) and amount >= 0:
        values.append(float(amount))
    elif isinstance(amount, str):
        try:
            parsed = float(amount.replace(",", ""))
        except ValueError:
            return
        if parsed >= 0:
            values.append(parsed)


def _add_date(dates: set[str], value: object) -> None:
    parsed = parse_date(value)
    if parsed is not None:
        dates.add(parsed.isoformat())


def _append_text(parts: list[str], value: object) -> None:
    if isinstance(value, str) and value.strip():
        parts.append(value.strip())


def _extract_documents(node: Mapping[str, Any], documents: list[dict[str, str]], text_parts: list[str]) -> None:
    raw_documents = node.get("documents")
    if not isinstance(raw_documents, list):
        return
    for document in raw_documents:
        if not isinstance(document, Mapping):
            continue
        url = str(document.get("url") or "").strip()
        title = str(document.get("title") or "").strip()
        description = str(document.get("description") or "").strip()
        document_type = str(document.get("documentType") or "").strip()
        if url:
            documents.append({
                "url": url,
                "title": title,
                "description": description,
                "documentType": document_type,
            })
        _append_text(text_parts, title)
        _append_text(text_parts, description)
        _append_text(text_parts, document_type)


def _extract_items(node: Mapping[str, Any], text_parts: list[str], classifications: set[str]) -> None:
    items = node.get("items")
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, Mapping):
            continue
        _append_text(text_parts, item.get("description"))
        classification_nodes: list[Mapping[str, Any]] = []
        classification = item.get("classification")
        if isinstance(classification, Mapping):
            classification_nodes.append(classification)
        additional = item.get("additionalClassifications")
        if isinstance(additional, list):
            classification_nodes.extend(node for node in additional if isinstance(node, Mapping))
        for classification_node in classification_nodes:
            scheme = normalize_text(classification_node.get("scheme")) or "UNKNOWN"
            code = normalize_identifier(classification_node.get("id"))
            if code:
                classifications.add(f"{scheme}:{code}")
            _append_text(text_parts, classification_node.get("description"))


@dataclass(frozen=True)
class ReleaseSummary:
    source: str
    source_year: int
    ocid: str
    release_id: str
    buyer_ids: tuple[str, ...]
    buyer_names: tuple[str, ...]
    supplier_ids: tuple[str, ...]
    supplier_names: tuple[str, ...]
    amounts: tuple[float, ...]
    dates: tuple[str, ...]
    object_text: str
    classifications: tuple[str, ...]
    documents: tuple[dict[str, str], ...]
    codes: tuple[str, ...]

    def to_data(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def release_key(self) -> str:
        return f"{self.source}:{self.source_year}:{self.ocid}:{self.release_id}"


def summarize_release(release: Mapping[str, Any], source: str, source_year: int) -> ReleaseSummary:
    buyer_ids: set[str] = set()
    buyer_names: set[str] = set()
    supplier_ids: set[str] = set()
    supplier_names: set[str] = set()
    amounts: list[float] = []
    dates: set[str] = set()
    text_parts: list[str] = []
    classifications: set[str] = set()
    documents: list[dict[str, str]] = []
    codes: set[str] = set()

    _add_party(release.get("buyer"), buyer_ids, buyer_names)
    _add_party(release.get("procuringEntity"), buyer_ids, buyer_names)

    parties = release.get("parties")
    if isinstance(parties, list):
        for party in parties:
            if not isinstance(party, Mapping):
                continue
            roles = _roles(party)
            if roles & {"buyer", "procuringentity", "procuring entity", "payer"}:
                _add_party(party, buyer_ids, buyer_names)
            if roles & {"supplier", "payee", "tenderer", "vendor"}:
                _add_party(party, supplier_ids, supplier_names)

    _add_date(dates, release.get("date"))
    _append_text(text_parts, release.get("title"))
    _append_text(text_parts, release.get("description"))
    _extract_documents(release, documents, text_parts)
    _extract_items(release, text_parts, classifications)

    planning = release.get("planning")
    if isinstance(planning, Mapping):
        _append_text(text_parts, planning.get("rationale"))
        _extract_documents(planning, documents, text_parts)
        budget = planning.get("budget")
        if isinstance(budget, Mapping):
            _append_text(text_parts, budget.get("description"))

    tender = release.get("tender")
    if isinstance(tender, Mapping):
        _append_text(text_parts, tender.get("title"))
        _append_text(text_parts, tender.get("description"))
        _add_value(amounts, tender.get("value"))
        tender_period = tender.get("tenderPeriod")
        if isinstance(tender_period, Mapping):
            _add_date(dates, tender_period.get("startDate"))
            _add_date(dates, tender_period.get("endDate"))
        _extract_documents(tender, documents, text_parts)
        _extract_items(tender, text_parts, classifications)
        tender_id = tender.get("id")
        if tender_id:
            codes.add(str(tender_id))

    awards = release.get("awards")
    if isinstance(awards, list):
        for award in awards:
            if not isinstance(award, Mapping):
                continue
            award_id = award.get("id")
            if award_id:
                codes.add(str(award_id))
            _append_text(text_parts, award.get("title"))
            _append_text(text_parts, award.get("description"))
            _add_value(amounts, award.get("value"))
            _add_date(dates, award.get("date"))
            suppliers = award.get("suppliers")
            if isinstance(suppliers, list):
                for supplier in suppliers:
                    _add_party(supplier, supplier_ids, supplier_names)
            _extract_documents(award, documents, text_parts)
            _extract_items(award, text_parts, classifications)

    contracts = release.get("contracts")
    if isinstance(contracts, list):
        for contract in contracts:
            if not isinstance(contract, Mapping):
                continue
            contract_id = contract.get("id")
            if contract_id:
                codes.add(str(contract_id))
            _append_text(text_parts, contract.get("title"))
            _append_text(text_parts, contract.get("description"))
            _add_value(amounts, contract.get("value"))
            _add_date(dates, contract.get("dateSigned"))
            period = contract.get("period")
            if isinstance(period, Mapping):
                _add_date(dates, period.get("startDate"))
                _add_date(dates, period.get("endDate"))
            _extract_documents(contract, documents, text_parts)
            _extract_items(contract, text_parts, classifications)
            implementation = contract.get("implementation")
            if isinstance(implementation, Mapping):
                _extract_documents(implementation, documents, text_parts)
                transactions = implementation.get("transactions")
                if isinstance(transactions, list):
                    for transaction in transactions:
                        if not isinstance(transaction, Mapping):
                            continue
                        transaction_id = transaction.get("id")
                        if transaction_id:
                            codes.add(str(transaction_id))
                        _add_value(amounts, transaction.get("value"))
                        _add_date(dates, transaction.get("date"))
                        _append_text(text_parts, transaction.get("description"))
                        _add_party(transaction.get("payee"), supplier_ids, supplier_names)

    implementation = release.get("implementation")
    if isinstance(implementation, Mapping):
        _extract_documents(implementation, documents, text_parts)
        transactions = implementation.get("transactions")
        if isinstance(transactions, list):
            for transaction in transactions:
                if not isinstance(transaction, Mapping):
                    continue
                transaction_id = transaction.get("id")
                if transaction_id:
                    codes.add(str(transaction_id))
                _add_value(amounts, transaction.get("value"))
                _add_date(dates, transaction.get("date"))
                _append_text(text_parts, transaction.get("description"))
                _add_party(transaction.get("payee"), supplier_ids, supplier_names)

    ocid = str(release.get("ocid") or "").strip()
    release_id = str(release.get("id") or ocid or sha256_payload(release)[:20]).strip()
    if ocid:
        codes.add(ocid)
    object_text = " | ".join(dict.fromkeys(part for part in text_parts if part))
    return ReleaseSummary(
        source=source,
        source_year=source_year,
        ocid=ocid,
        release_id=release_id,
        buyer_ids=tuple(sorted(buyer_ids)),
        buyer_names=tuple(sorted(buyer_names)),
        supplier_ids=tuple(sorted(supplier_ids)),
        supplier_names=tuple(sorted(supplier_names)),
        amounts=tuple(sorted(set(round(value, 4) for value in amounts if value >= 0))),
        dates=tuple(sorted(dates)),
        object_text=object_text,
        classifications=tuple(sorted(classifications)),
        documents=tuple(documents),
        codes=tuple(sorted(codes)),
    )


def best_identity_keys(summary: ReleaseSummary, role: str) -> tuple[tuple[str, ...], str]:
    if role == "buyer":
        identifiers = summary.buyer_ids
        names = summary.buyer_names
    elif role == "supplier":
        identifiers = summary.supplier_ids
        names = summary.supplier_names
    else:
        raise ValueError("role must be buyer or supplier")
    if identifiers:
        return tuple(f"ID:{value}" for value in identifiers), "ID"
    return tuple(f"NAME:{value}" for value in names if value), "NAME"


def closest_amount(left: Sequence[float], right: Sequence[float]) -> tuple[float, float, float] | None:
    best: tuple[float, float, float] | None = None
    for left_value in left:
        if left_value <= 0:
            continue
        for right_value in right:
            if right_value <= 0:
                continue
            relative = abs(left_value - right_value) / max(left_value, right_value)
            candidate = (relative, left_value, right_value)
            if best is None or candidate < best:
                best = candidate
    return best


def closest_days(left: Sequence[str], right: Sequence[str]) -> int | None:
    left_dates = [parse_date(value) for value in left]
    right_dates = [parse_date(value) for value in right]
    best: int | None = None
    for left_date in left_dates:
        if left_date is None:
            continue
        for right_date in right_dates:
            if right_date is None:
                continue
            days = abs((left_date - right_date).days)
            if best is None or days < best:
                best = days
    return best


def object_tokens(summary: ReleaseSummary) -> set[str]:
    exclusions: set[str] = set()
    for value in (
        *summary.buyer_names,
        *summary.supplier_names,
        *summary.codes,
        summary.ocid,
        summary.release_id,
    ):
        exclusions.update(_TOKEN_RE.findall(normalize_text(value)))
    tokens = set(_TOKEN_RE.findall(normalize_text(summary.object_text)))
    return {
        token
        for token in tokens
        if token not in _OBJECT_STOPWORDS
        and token not in exclusions
        and not (token.isdigit() and len(token) < 4)
    }


def object_categories(tokens: set[str]) -> set[str]:
    return {
        category
        for category, vocabulary in _CATEGORY_LEXICONS.items()
        if tokens & vocabulary
    }


def adjudicate_object(left: ReleaseSummary, right: ReleaseSummary) -> dict[str, Any]:
    left_tokens = object_tokens(left)
    right_tokens = object_tokens(right)
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(shared) / len(union) if union else 0.0
    left_categories = object_categories(left_tokens)
    right_categories = object_categories(right_tokens)
    shared_classifications = set(left.classifications) & set(right.classifications)

    non_generic_left = left_categories - _GENERIC_CATEGORIES
    non_generic_right = right_categories - _GENERIC_CATEGORIES
    category_conflict = bool(
        non_generic_left
        and non_generic_right
        and non_generic_left.isdisjoint(non_generic_right)
    )

    if shared_classifications:
        decision = "SUPPORTED"
        reason = "SHARED_CLASSIFICATION"
    elif category_conflict:
        decision = "REJECTED"
        reason = "MATERIAL_OBJECT_CATEGORY_CONFLICT"
    elif len(shared) >= 2 and jaccard >= 0.08:
        decision = "SUPPORTED"
        reason = "OBJECT_TEXT_COMPATIBLE"
    elif len(left_tokens) >= 4 and len(right_tokens) >= 4 and not shared:
        decision = "REJECTED"
        reason = "NO_OBJECT_TOKEN_SUPPORT"
    else:
        decision = "UNRESOLVED"
        reason = "INSUFFICIENT_OBJECT_EVIDENCE"

    return {
        "decision": decision,
        "reason": reason,
        "jaccard": round(jaccard, 6),
        "shared_tokens": sorted(shared)[:50],
        "left_categories": sorted(left_categories),
        "right_categories": sorted(right_categories),
        "shared_classifications": sorted(shared_classifications),
        "left_token_count": len(left_tokens),
        "right_token_count": len(right_tokens),
    }
