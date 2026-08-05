"""Frozen, fail-closed archive adapter for CORU OCR image/transcription pairs.

The adapter is intentionally generic but deterministic. It accepts only an
explicit same-stem label file, an explicit manifest mapping, or a near-complete
filename-label convention. Conflicting mappings, unsafe ZIP members, ambiguous
schemas, duplicate members, invalid Unicode, and missing labels fail closed.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
TEXT_EXTENSIONS = {".txt", ".gt.txt", ".csv", ".tsv", ".json", ".jsonl"}
MAX_TEXT_MEMBER_BYTES = 50_000_000
MAX_UNCOMPRESSED_BYTES = 4_000_000_000
IMAGE_KEYS = (
    "image",
    "image_path",
    "image_name",
    "file",
    "file_name",
    "filename",
    "path",
)
LABEL_KEYS = (
    "label",
    "labels",
    "text",
    "transcription",
    "transcript",
    "ground_truth",
    "gt",
    "target",
)
_FILENAME_LABEL = re.compile(r"^(?P<index>\d{1,10})__(?P<label>.+)$")
_YEAR_MIN = 1900
_YEAR_MAX = 2099


def normalized_member_name(value: object) -> str:
    raw = str(value or "")
    if not raw or "\\" in raw or "\x00" in raw:
        raise RuntimeError("unsafe or empty ZIP member name")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"unsafe ZIP member path: {raw!r}")
    return path.as_posix()


def safe_zip_members(path: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
    names: set[str] = set()
    total = 0
    retained: list[zipfile.ZipInfo] = []
    for info in infos:
        name = normalized_member_name(info.filename)
        if name in names:
            raise RuntimeError(f"duplicate ZIP member: {name}")
        names.add(name)
        if info.flag_bits & 0x1:
            raise RuntimeError(f"encrypted ZIP member is unsupported: {name}")
        if info.is_dir():
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise RuntimeError(f"symbolic-link ZIP member is unsupported: {name}")
        if info.file_size < 0 or info.compress_size < 0:
            raise RuntimeError(f"invalid ZIP size: {name}")
        total += int(info.file_size)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise RuntimeError("ZIP uncompressed bytes exceed the frozen safety limit")
        retained.append(info)
    if not retained:
        raise RuntimeError("ZIP archive contains no files")
    return retained


def _lower_suffix(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".gt.txt"):
        return ".gt.txt"
    return PurePosixPath(lower).suffix


def _is_image(name: str) -> bool:
    return _lower_suffix(name) in IMAGE_EXTENSIONS


def _decode_text(raw: bytes, member: str) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"label text is not valid UTF-8: {member}")


def normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return " ".join(text.split())


def canonical_numeric_label(value: object) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return None
    digits: list[str] = []
    for character in text:
        if character.isdigit():
            try:
                digits.append(str(unicodedata.digit(character)))
            except (TypeError, ValueError):
                return None
            continue
        category = unicodedata.category(character)
        if character.isspace() or character in ",.:'’`/-_()[]{}+" or category in {
            "Sc",
            "Pd",
            "Po",
            "Ps",
            "Pe",
        }:
            continue
        return None
    canonical = "".join(digits)
    if not 4 <= len(canonical) <= 12:
        return None
    if len(set(canonical)) == 1:
        return None
    if len(canonical) == 4 and _YEAR_MIN <= int(canonical) <= _YEAR_MAX:
        return None
    return canonical


def _stem_without_label_suffix(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".gt.txt"):
        return name[: -len(".gt.txt")]
    return str(PurePosixPath(name).with_suffix(""))


def _image_aliases(name: str) -> set[str]:
    path = PurePosixPath(name)
    stem = str(path.with_suffix(""))
    aliases = {name, stem, path.name, path.stem}
    parts = list(path.parts)
    for index, part in enumerate(parts):
        if part.lower() in {"images", "image", "imgs", "img"}:
            replaced = parts.copy()
            replaced[index] = "labels"
            aliases.add(PurePosixPath(*replaced).as_posix())
            aliases.add(str(PurePosixPath(*replaced).with_suffix("")))
    return {alias.lower() for alias in aliases}


def _label_aliases(name: str) -> set[str]:
    stem = _stem_without_label_suffix(name)
    path = PurePosixPath(stem)
    aliases = {name, stem, path.name, path.stem}
    parts = list(path.parts)
    for index, part in enumerate(parts):
        if part.lower() in {"labels", "label", "gt", "ground_truth"}:
            replaced = parts.copy()
            replaced[index] = "images"
            aliases.add(PurePosixPath(*replaced).as_posix())
            aliases.add(str(PurePosixPath(*replaced).with_suffix("")))
    return {alias.lower() for alias in aliases}


def _record_mapping(
    mapping: dict[str, list[dict[str, str]]],
    image_reference: object,
    label: object,
    source_member: str,
    source_kind: str,
) -> None:
    reference = normalize_label(image_reference)
    text = normalize_label(label)
    if not reference or not text:
        return
    mapping[reference.lower()].append(
        {
            "label": text,
            "source_member": source_member,
            "source_kind": source_kind,
        }
    )


def _iter_json_records(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                yield item
            else:
                yield from _iter_json_records(item)
        return
    if not isinstance(value, Mapping):
        return
    if any(key in value for key in IMAGE_KEYS) and any(key in value for key in LABEL_KEYS):
        yield value
    for key in ("data", "records", "annotations", "samples", "items", "examples"):
        if key in value:
            yield from _iter_json_records(value[key])


def _parse_json_mapping(text: str, member: str) -> dict[str, list[dict[str, str]]]:
    mapping: dict[str, list[dict[str, str]]] = defaultdict(list)
    if member.lower().endswith(".jsonl"):
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = [json.loads(text)]
    for value in values:
        if isinstance(value, Mapping) and value and all(
            isinstance(key, str) and isinstance(label, str)
            for key, label in value.items()
        ):
            for key, label in value.items():
                _record_mapping(mapping, key, label, member, "json_dictionary")
        for record in _iter_json_records(value):
            image = next((record[key] for key in IMAGE_KEYS if key in record), None)
            label = next((record[key] for key in LABEL_KEYS if key in record), None)
            _record_mapping(mapping, image, label, member, "json_record")
    return mapping


def _parse_delimited_mapping(text: str, member: str) -> dict[str, list[dict[str, str]]]:
    mapping: dict[str, list[dict[str, str]]] = defaultdict(list)
    sample = text[:65536]
    delimiter = "\t" if "\t" in sample else ","
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        fieldnames = [str(name or "").strip().lower() for name in reader.fieldnames or []]
        image_field = next((name for name in IMAGE_KEYS if name in fieldnames), None)
        label_field = next((name for name in LABEL_KEYS if name in fieldnames), None)
        if image_field and label_field:
            original_names = {
                str(name or "").strip().lower(): name for name in reader.fieldnames or []
            }
            for row in reader:
                _record_mapping(
                    mapping,
                    row.get(original_names[image_field]),
                    row.get(original_names[label_field]),
                    member,
                    "delimited_header",
                )
            return mapping
    except csv.Error:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            reference, label = line.split("\t", 1)
        else:
            parts = line.split(maxsplit=1)
            if len(parts) != 2 or not _is_image(parts[0]):
                continue
            reference, label = parts
        _record_mapping(mapping, reference, label, member, "delimited_line")
    return mapping


def _merge_mappings(
    destination: dict[str, list[dict[str, str]]],
    source: Mapping[str, Sequence[Mapping[str, str]]],
) -> None:
    for key, rows in source.items():
        destination[key].extend(dict(row) for row in rows)


def discover_pairs(zip_path: Path) -> dict[str, Any]:
    infos = safe_zip_members(zip_path)
    info_by_name = {normalized_member_name(info.filename): info for info in infos}
    image_names = sorted(name for name in info_by_name if _is_image(name))
    if not image_names:
        raise RuntimeError("CORU OCR archive contains no supported images")
    explicit_mapping: dict[str, list[dict[str, str]]] = defaultdict(list)
    label_members = sorted(
        name
        for name, info in info_by_name.items()
        if _lower_suffix(name) in TEXT_EXTENSIONS
        and not _is_image(name)
        and int(info.file_size) <= MAX_TEXT_MEMBER_BYTES
    )
    label_member_set = set(label_members)
    with zipfile.ZipFile(zip_path) as archive:
        for member in label_members:
            raw = archive.read(member)
            text = _decode_text(raw, member)
            suffix = _lower_suffix(member)
            if suffix in {".json", ".jsonl"}:
                try:
                    _merge_mappings(
                        explicit_mapping,
                        _parse_json_mapping(text, member),
                    )
                except json.JSONDecodeError:
                    if suffix == ".json":
                        raise RuntimeError(f"invalid JSON label manifest: {member}")
            if suffix in {".csv", ".tsv"} or "\t" in text[:65536]:
                _merge_mappings(
                    explicit_mapping,
                    _parse_delimited_mapping(text, member),
                )

        label_alias_index: dict[str, list[str]] = defaultdict(list)
        for member in label_members:
            for alias in _label_aliases(member):
                label_alias_index[alias].append(member)

        pairs: list[dict[str, Any]] = []
        unresolved: list[str] = []
        source_counter: Counter[str] = Counter()
        for image in image_names:
            candidates: list[dict[str, str]] = []
            aliases = _image_aliases(image)
            matching_label_members = {
                member
                for alias in aliases
                for member in label_alias_index.get(alias, [])
            }
            for member in sorted(matching_label_members):
                text = normalize_label(_decode_text(archive.read(member), member))
                if text:
                    candidates.append(
                        {
                            "label": text,
                            "source_member": member,
                            "source_kind": "same_stem_label_file",
                        }
                    )
            for alias in aliases:
                candidates.extend(explicit_mapping.get(alias, []))
            unique = {
                (row["label"], row["source_member"], row["source_kind"]): row
                for row in candidates
            }
            labels = {row[0] for row in unique}
            if len(labels) > 1:
                raise RuntimeError(f"conflicting explicit labels for {image}: {sorted(labels)!r}")
            if labels:
                selected = sorted(unique.values(), key=lambda row: (
                    row["source_kind"], row["source_member"], row["label"]
                ))[0]
                source_counter[selected["source_kind"]] += 1
                pairs.append({"image_member": image, **selected})
            else:
                unresolved.append(image)

        if unresolved:
            filename_rows = []
            for image in unresolved:
                match = _FILENAME_LABEL.fullmatch(PurePosixPath(image).stem)
                if match:
                    filename_rows.append((image, normalize_label(match.group("label"))))
            coverage = len(filename_rows) / len(unresolved)
            if coverage >= 0.99:
                by_image = dict(filename_rows)
                still_unresolved = []
                for image in unresolved:
                    label = by_image.get(image)
                    if not label:
                        still_unresolved.append(image)
                        continue
                    pairs.append(
                        {
                            "image_member": image,
                            "label": label,
                            "source_member": image,
                            "source_kind": "double_underscore_filename_label",
                        }
                    )
                    source_counter["double_underscore_filename_label"] += 1
                unresolved = still_unresolved

    if unresolved:
        raise RuntimeError(
            f"unresolved image labels: {len(unresolved)}/{len(image_names)}; "
            f"first={unresolved[:5]!r}"
        )
    if len(pairs) != len(image_names):
        raise RuntimeError("archive pairing is not one-to-one")
    pairs.sort(key=lambda row: row["image_member"])
    if len({row["image_member"] for row in pairs}) != len(pairs):
        raise RuntimeError("duplicate image pairing")
    numeric_pairs = [
        {
            **row,
            "canonical_numeric_label": canonical,
        }
        for row in pairs
        if (canonical := canonical_numeric_label(row["label"])) is not None
    ]
    return {
        "schema": "ocr-coru-ocr-archive-pairs/1",
        "archive": str(zip_path),
        "archive_member_count": len(infos),
        "image_count": len(image_names),
        "label_member_count": len(label_member_set),
        "pair_count": len(pairs),
        "numeric_pair_count": len(numeric_pairs),
        "label_sources": dict(sorted(source_counter.items())),
        "member_name_set_sha256": __import__("hashlib").sha256(
            json.dumps(sorted(info_by_name), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "pair_set_sha256": __import__("hashlib").sha256(
            json.dumps(pairs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "numeric_pair_set_sha256": __import__("hashlib").sha256(
            json.dumps(numeric_pairs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "pairs": pairs,
        "numeric_pairs": numeric_pairs,
    }
