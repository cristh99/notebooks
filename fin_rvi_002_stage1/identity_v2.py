from __future__ import annotations

import re
from typing import Any

from .ocds import ReleaseSummary, adjudicate_object, normalize_name, normalize_text

_FILLER = {
    "SECRETARIA", "ESTADO", "DESPACHOS", "GERENCIA", "ADMINISTRATIVA", "ADMINISTRATIVO",
    "NACIONAL", "INSTITUTO", "DIRECCION", "UNIDAD", "GENERAL", "REPUBLICA", "HONDURAS",
}

_CODE_PATTERNS = (
    re.compile(r"\bSIT\s+[A-Z]{2}\s+\d{3}\s+\d{4}\b"),
    re.compile(r"\bSDO\s+O\s+FHIS\s+\d{1,4}\s+\d{4}\b"),
    re.compile(r"\bENP\s+\d{1,3}\s+\d{2,4}\b"),
)
_PROJECT_CODE = re.compile(
    r"\b(?:CODIGO|PROYECTO|SUBPROYECTO)\s*(?:NO\s*)?[:#-]?\s*(\d{6})\b"
)


def _canonical_code(value: str) -> str:
    text = normalize_text(value).replace(" ", "-")
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def contract_code_keys(summary: ReleaseSummary) -> tuple[str, ...]:
    haystack = " | ".join(
        (*summary.codes, *summary.buyer_ids, *summary.buyer_names, summary.object_text)
    )
    normalized = normalize_text(haystack)
    found: set[str] = set()
    for pattern in _CODE_PATTERNS:
        for match in pattern.findall(normalized):
            found.add(f"CODE:{_canonical_code(match)}")
    if any(token in normalized for token in ("FHIS", "SEDECOAS", "FONDO INVERSION SOCIAL")):
        for match in _PROJECT_CODE.findall(normalized):
            found.add(f"PROJECT:{match}")
    return tuple(sorted(found))


def _buyer_aliases(summary: ReleaseSummary) -> list[tuple[str, str]]:
    text = " ".join((*summary.buyer_ids, *summary.buyer_names))
    normalized = normalize_text(text)
    aliases: list[tuple[str, str]] = []
    if any(marker in normalized for marker in ("HNDENG 411", "HNENG411", " INFRAESTRUCTURA TRANSPORTE", " SIT")):
        aliases.append(("ALIAS:SIT", "ALIAS"))
    if any(marker in normalized for marker in ("HNDENG 22", "HNENG22", " FHIS", "SEDECOAS", "FONDO INVERSION SOCIAL")):
        aliases.append(("ALIAS:FHIS", "ALIAS"))
    if any(marker in normalized for marker in ("HNDENG 803", "HNENG803", "EMPRESA NACIONAL PORTUARIA", " ENP")):
        aliases.append(("ALIAS:ENP", "ALIAS"))

    for name in summary.buyer_names:
        tokens = [
            token for token in normalize_name(name).split()
            if token not in _FILLER and len(token) > 3
        ]
        if tokens:
            aliases.append((f"CORE:{' '.join(tokens)}", "CORE"))
    return list(dict.fromkeys(aliases))


def _numeric_identifier_keys(values: tuple[str, ...]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for value in values:
        output.append((f"ID:{value}", "ID"))
        digits = "".join(re.findall(r"\d", value))
        if len(digits) >= 8:
            output.append((f"IDNUM:{digits}", "IDNUM"))
    return list(dict.fromkeys(output))


def _name_keys(values: tuple[str, ...]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for value in values:
        normalized = normalize_name(value)
        if normalized:
            output.append((f"NAME:{normalized}", "NAME"))
    return list(dict.fromkeys(output))


def compact_identity_pairs_v2(summary: ReleaseSummary) -> list[tuple[str, str]]:
    buyers = _buyer_aliases(summary)
    if not buyers:
        buyers = _numeric_identifier_keys(summary.buyer_ids) + _name_keys(summary.buyer_names)
    codes = contract_code_keys(summary)
    if codes:
        right = [(code, "CODE") for code in codes]
    else:
        right = _numeric_identifier_keys(summary.supplier_ids) + _name_keys(summary.supplier_names)
    pairs: list[tuple[str, str]] = []
    for buyer_key, buyer_basis in buyers[:8]:
        for right_key, right_basis in right[:24]:
            pairs.append((
                f"{buyer_key}\u241f{right_key}",
                f"BUYER_{buyer_basis}_{right_basis}",
            ))
    return list(dict.fromkeys(pairs))


def _supplier_numeric_ids(summary: ReleaseSummary) -> set[str]:
    output: set[str] = set()
    for value in summary.supplier_ids:
        digits = "".join(re.findall(r"\d", value))
        if len(digits) >= 8:
            output.add(digits)
    return output


def _supplier_names(summary: ReleaseSummary) -> set[str]:
    return {normalize_name(value) for value in summary.supplier_names if normalize_name(value)}


def adjudicate_object_v2(left: ReleaseSummary, right: ReleaseSummary) -> dict[str, Any]:
    result = adjudicate_object(left, right)
    left_ids = _supplier_numeric_ids(left)
    right_ids = _supplier_numeric_ids(right)
    left_names = _supplier_names(left)
    right_names = _supplier_names(right)
    exact_id = bool(left_ids & right_ids)
    exact_name = bool(left_names & right_names)
    contained_name = any(
        len(name) >= 8 and (name in other or other in name)
        for name in left_names
        for other in right_names
    )
    supplier_supported = exact_id or exact_name or contained_name
    result["supplier_identity_supported"] = supplier_supported
    result["shared_supplier_numeric_ids"] = sorted(left_ids & right_ids)
    result["shared_supplier_names"] = sorted(left_names & right_names)

    if result["decision"] == "SUPPORTED" and not supplier_supported:
        result["decision"] = "UNRESOLVED"
        result["reason"] = "OBJECT_COMPATIBLE_SUPPLIER_IDENTITY_UNRESOLVED"
    elif result["decision"] == "REJECTED" and supplier_supported:
        result["reason"] = "SUPPLIER_MATCH_BUT_MATERIAL_OBJECT_CONFLICT"
    return result
