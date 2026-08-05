from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import duckdb
except ImportError:  # Synthetic tests do not require DuckDB.
    duckdb = None


COUNTRIES = ("USA", "UK", "Canada", "Germany", "France")
STORES = ("iTunes", "Spotify", "Apple Music", "Amazon Music", "Google Play")
LANGUAGE_ALIASES = {
    "english": "English", "en": "English",
    "spanish": "Spanish", "es": "Spanish",
    "french": "French", "fr": "French",
    "german": "German", "de": "German",
    "italian": "Italian", "it": "Italian",
    "portuguese": "Portuguese", "pt": "Portuguese",
    "japanese": "Japanese", "ja": "Japanese",
    "korean": "Korean", "ko": "Korean",
    "chinese": "Chinese", "zh": "Chinese",
    "instrumental": "Instrumental",
}


def space(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", space(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"\bfeat(?:uring)?\.?\b", " featuring ", text)
    text = re.sub(r"\bft\.?\b", " featuring ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(value))


_EDITION_NOISE = re.compile(
    r"\s*[\(\[]\s*(?:"
    r"remaster(?:ed)?(?:\s+\d{2,4})?|"
    r"radio edit|single version|album version|original version|"
    r"bonus track|explicit|clean|mono|stereo|deluxe(?: edition)?|"
    r"live(?: at| from)?[^)\]]*|"
    r"version"
    r")\s*[\)\]]\s*",
    re.IGNORECASE,
)


def title_key(value: Any) -> str:
    text = _EDITION_NOISE.sub(" ", space(value))
    return key(text)


def artist_key(value: Any) -> str:
    text = fold(value)
    text = re.sub(r"\b(?:the)\b", " ", text)
    text = re.split(r"\bfeaturing\b|\bwith\b", text, maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]+", "", text)


def album_key(value: Any) -> str:
    text = _EDITION_NOISE.sub(" ", space(value))
    return key(text)


def parse_year(value: Any) -> int | None:
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", space(value))
    if not match:
        return None
    year = int(match.group(1))
    return year if 1800 <= year <= 2099 else None


def parse_length_seconds(value: Any) -> float | None:
    text = space(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        number = float(text)
        return number if 0 < number < 86400 else None
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", text)
    if match:
        hours = int(match.group(1) or 0)
        return float(hours * 3600 + int(match.group(2)) * 60 + int(match.group(3)))
    match = re.fullmatch(r"(\d+):(\d{2})", text)
    if match:
        return float(int(match.group(1)) * 60 + int(match.group(2)))
    match = re.search(
        r"(?:(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h))?\s*"
        r"(?:(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m))?\s*"
        r"(?:(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s))?",
        text.casefold(),
    )
    if match and any(match.groups()):
        return (
            float(match.group(1) or 0) * 3600
            + float(match.group(2) or 0) * 60
            + float(match.group(3) or 0)
        )
    return None


@dataclass(frozen=True)
class Track:
    track_id: int
    source_id: int | None
    source_track_id: str
    title: str
    artist: str
    album: str
    year: int | None
    length_seconds: float | None
    language: str


@dataclass(frozen=True)
class Sale:
    sale_id: int
    track_id: int
    country: str
    store: str
    units_sold: float
    revenue_usd: float


@dataclass
class Entity:
    entity_id: int
    track_ids: set[int]
    title: str
    artist: str
    album: str
    year: int | None
    length_seconds: float | None
    language: str


class UnionFind:
    def __init__(self, values: Iterable[int]):
        materialized = list(values)
        self.parent = {value: value for value in materialized}
        self.rank = {value: 0 for value in materialized}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        if self.rank[a] < self.rank[b]:
            a, b = b, a
        self.parent[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _compatible_years(left: Track, right: Track) -> bool:
    return left.year is None or right.year is None or abs(left.year - right.year) <= 1


def _compatible_lengths(left: Track, right: Track) -> bool:
    if left.length_seconds is None or right.length_seconds is None:
        return True
    return abs(left.length_seconds - right.length_seconds) <= max(
        5.0, 0.03 * min(left.length_seconds, right.length_seconds)
    )


def _same_entity(left: Track, right: Track) -> bool:
    lt, rt = title_key(left.title), title_key(right.title)
    la, ra = artist_key(left.artist), artist_key(right.artist)
    lal, ral = album_key(left.album), album_key(right.album)

    if not lt or not rt or not la or not ra:
        return False

    if (
        left.source_track_id
        and right.source_track_id
        and key(left.source_track_id) == key(right.source_track_id)
        and _ratio(lt, rt) >= 0.88
        and _ratio(la, ra) >= 0.88
    ):
        return True

    if lt == rt and la == ra:
        return _compatible_years(left, right) and _compatible_lengths(left, right)

    title_similarity = _ratio(lt, rt)
    artist_similarity = _ratio(la, ra)
    album_similarity = _ratio(lal, ral) if lal and ral else 1.0

    if (
        artist_similarity >= 0.97
        and title_similarity >= 0.93
        and album_similarity >= 0.74
        and _compatible_years(left, right)
        and _compatible_lengths(left, right)
    ):
        return True
    if (
        title_similarity >= 0.98
        and artist_similarity >= 0.92
        and album_similarity >= 0.80
        and _compatible_years(left, right)
        and _compatible_lengths(left, right)
    ):
        return True
    return False


def _representative(
    values: Sequence[str],
    normalizer=fold,
    prefer_shortest: bool = False,
) -> str:
    clean = [space(value) for value in values if space(value)]
    if not clean:
        return ""
    counts = Counter(normalizer(value) for value in clean)
    winning_key = min(
        counts,
        key=lambda item: (-counts[item], item),
    )
    candidates = [value for value in clean if normalizer(value) == winning_key]
    non_ascii = lambda value: sum(ord(ch) > 127 for ch in value)
    if prefer_shortest:
        return min(candidates, key=lambda value: (len(value), -non_ascii(value), value.casefold()))
    return min(candidates, key=lambda value: (-non_ascii(value), -len(value), value.casefold()))


def resolve_entities(tracks: Sequence[Track]) -> tuple[list[Entity], dict[int, int]]:
    uf = UnionFind(track.track_id for track in tracks)
    by_id = {track.track_id: track for track in tracks}

    features = {
        track.track_id: (
            title_key(track.title),
            artist_key(track.artist),
            album_key(track.album),
            key(track.source_track_id),
        )
        for track in tracks
    }

    exact: dict[tuple[str, str], list[int]] = defaultdict(list)
    source_ids: dict[str, list[int]] = defaultdict(list)
    for track in tracks:
        tk, ak, _, source_key = features[track.track_id]
        exact[(tk, ak)].append(track.track_id)
        if source_key:
            source_ids[source_key].append(track.track_id)
    for ids in exact.values():
        if not ids:
            continue
        anchor = ids[0]
        for other in ids[1:]:
            if _compatible_years(by_id[anchor], by_id[other]) and _compatible_lengths(
                by_id[anchor], by_id[other]
            ):
                uf.union(anchor, other)
    for ids in source_ids.values():
        if len(ids) > 64:
            continue
        for i, left in enumerate(ids):
            for right in ids[i + 1 :]:
                if _same_entity(by_id[left], by_id[right]):
                    uf.union(left, right)

    representatives: dict[int, int] = {}
    for track in tracks:
        root_id = uf.find(track.track_id)
        representatives[root_id] = min(
            track.track_id,
            representatives.get(root_id, track.track_id),
        )
    representative_ids = sorted(representatives.values())

    blocks: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for track_id in representative_ids:
        tk, ak, _, _ = features[track_id]
        if not tk or not ak:
            continue
        blocks[("balanced", tk[:8], ak[:8])].append(track_id)
        blocks[("title", tk[:10], ak[:4])].append(track_id)
        blocks[("artist", tk[:4], ak[:10])].append(track_id)

    seen_pairs: set[tuple[int, int]] = set()
    for ids in blocks.values():
        if len(ids) > 96:
            continue
        for i, left_id in enumerate(ids):
            ltk, lak, lal, _ = features[left_id]
            for right_id in ids[i + 1 :]:
                pair = (left_id, right_id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                rtk, rak, ral, _ = features[right_id]
                left_numbers = tuple(re.findall(r"\d+", ltk))
                right_numbers = tuple(re.findall(r"\d+", rtk))
                if left_numbers and right_numbers and left_numbers != right_numbers:
                    continue
                if abs(len(ltk) - len(rtk)) > max(4, int(0.18 * max(len(ltk), len(rtk)))):
                    continue
                if abs(len(lak) - len(rak)) > max(3, int(0.18 * max(len(lak), len(rak)))):
                    continue
                left = by_id[left_id]
                right = by_id[right_id]
                if not _compatible_years(left, right) or not _compatible_lengths(left, right):
                    continue

                title_similarity = 1.0 if ltk == rtk else _ratio(ltk, rtk)
                artist_similarity = 1.0 if lak == rak else _ratio(lak, rak)
                album_similarity = (
                    1.0
                    if not lal or not ral or lal == ral
                    else _ratio(lal, ral)
                )
                if (
                    artist_similarity >= 0.97
                    and title_similarity >= 0.93
                    and album_similarity >= 0.74
                ) or (
                    title_similarity >= 0.98
                    and artist_similarity >= 0.92
                    and album_similarity >= 0.80
                ):
                    uf.union(left_id, right_id)

    members: dict[int, list[Track]] = defaultdict(list)
    for track in tracks:
        members[uf.find(track.track_id)].append(track)

    entities: list[Entity] = []
    track_to_entity: dict[int, int] = {}
    for entity_id, group in enumerate(
        sorted(members.values(), key=lambda group: min(track.track_id for track in group)),
        start=1,
    ):
        years = [track.year for track in group if track.year is not None]
        lengths = [track.length_seconds for track in group if track.length_seconds is not None]
        entity = Entity(
            entity_id=entity_id,
            track_ids={track.track_id for track in group},
            title=_representative(
                [track.title for track in group],
                normalizer=title_key,
                prefer_shortest=True,
            ),
            artist=_representative(
                [track.artist for track in group],
                normalizer=artist_key,
            ),
            album=_representative(
                [track.album for track in group],
                normalizer=album_key,
                prefer_shortest=True,
            ),
            year=int(statistics.median(years)) if years else None,
            length_seconds=float(statistics.median(lengths)) if lengths else None,
            language=_representative([track.language for track in group]),
        )
        entities.append(entity)
        for track in group:
            track_to_entity[track.track_id] = entity_id
    return entities, track_to_entity


def load_domain(root: Path) -> tuple[list[Track], list[Sale]]:
    if duckdb is None:
        raise RuntimeError("duckdb is required to load official data")
    dataset = root / "query_music_brainz_20k" / "query_dataset"
    tracks_path = dataset / "tracks.db"
    sales_path = dataset / "sales.duckdb"

    conn = sqlite3.connect(tracks_path)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name LIMIT 1"
        ).fetchone()[0]
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        track_rows = [dict(zip(columns, row)) for row in conn.execute(f'SELECT * FROM "{table}"')]
    finally:
        conn.close()

    sales_conn = duckdb.connect(str(sales_path), read_only=True)
    try:
        table = sales_conn.execute("SHOW TABLES").fetchone()[0]
        result = sales_conn.execute(f'SELECT * FROM "{table}"')
        columns = [item[0] for item in result.description]
        sale_rows = [dict(zip(columns, row)) for row in result.fetchall()]
    finally:
        sales_conn.close()

    tracks: list[Track] = []
    for row in track_rows:
        lookup = {key(k): value for k, value in row.items()}
        tracks.append(
            Track(
                track_id=int(lookup["trackid"]),
                source_id=int(lookup["sourceid"]) if lookup.get("sourceid") is not None else None,
                source_track_id=space(lookup.get("sourcetrackid")),
                title=space(lookup.get("title")),
                artist=space(lookup.get("artist")),
                album=space(lookup.get("album")),
                year=parse_year(lookup.get("year")),
                length_seconds=parse_length_seconds(lookup.get("length")),
                language=space(lookup.get("language")),
            )
        )

    sales: list[Sale] = []
    for row in sale_rows:
        lookup = {key(k): value for k, value in row.items()}
        units = float(lookup.get("unitssold") or 0)
        revenue = float(lookup.get("revenueusd") or 0)
        if not math.isfinite(units) or not math.isfinite(revenue):
            continue
        sales.append(
            Sale(
                sale_id=int(lookup["saleid"]),
                track_id=int(lookup["trackid"]),
                country=space(lookup.get("country")),
                store=space(lookup.get("store")),
                units_sold=units,
                revenue_usd=revenue,
            )
        )
    return tracks, sales


@dataclass
class Fact:
    entity_id: int
    title: str
    artist: str
    album: str
    year: int | None
    decade: int | None
    language: str
    length_seconds: float | None
    country: str
    store: str
    units_sold: float
    revenue_usd: float
    sale_id: int
    source_track_id: str


def build_facts(tracks: Sequence[Track], sales: Sequence[Sale]) -> tuple[list[Entity], list[Fact]]:
    entities, track_to_entity = resolve_entities(tracks)
    entity_by_id = {entity.entity_id: entity for entity in entities}
    track_by_id = {track.track_id: track for track in tracks}
    facts: list[Fact] = []
    for sale in sales:
        entity_id = track_to_entity.get(sale.track_id)
        track = track_by_id.get(sale.track_id)
        if entity_id is None or track is None:
            continue
        entity = entity_by_id[entity_id]
        facts.append(
            Fact(
                entity_id=entity_id,
                title=entity.title,
                artist=entity.artist,
                album=entity.album,
                year=entity.year,
                decade=(entity.year // 10 * 10) if entity.year is not None else None,
                language=entity.language,
                length_seconds=entity.length_seconds,
                country=sale.country,
                store=sale.store,
                units_sold=sale.units_sold,
                revenue_usd=sale.revenue_usd,
                sale_id=sale.sale_id,
                source_track_id=track.source_track_id,
            )
        )
    return entities, facts


DIMENSIONS = ("artist", "title", "album", "year", "decade", "language", "country", "store")
MEASURE_ALIASES = {
    "revenue_usd": (
        "revenue", "sales revenue", "money", "usd", "dollars", "income", "gross revenue"
    ),
    "units_sold": (
        "units sold", "unit sales", "copies sold", "sales volume", "number of units"
    ),
    "transactions": (
        "transactions", "sales transactions", "number of sales", "sale records"
    ),
    "distinct_tracks": (
        "distinct tracks", "unique tracks", "different tracks", "distinct songs", "unique songs"
    ),
    "track_count": ("tracks", "songs"),
    "distinct_artists": ("distinct artists", "unique artists", "different artists"),
    "distinct_albums": ("distinct albums", "unique albums", "different albums"),
    "length_seconds": ("length", "duration", "track length"),
    "revenue_per_unit": ("revenue per unit", "revenue per copy", "average selling price"),
}


@dataclass
class Predicate:
    field: str
    operator: str
    value: Any


@dataclass
class Plan:
    predicates: list[Predicate] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    measure: str = "revenue_usd"
    aggregate: str = "sum"
    direction: str | None = None
    top_k: int = 1
    min_support: int | None = None
    support_field: str = "entity_id"
    support_distinct: bool = True
    having_operator: str | None = None
    having_value: float | None = None
    count_groups: bool = False
    coverage_field: str | None = None
    coverage_min: int | None = None
    normalize_by: str | None = None
    contrast_field: str | None = None
    contrast_left: str | None = None
    contrast_right: str | None = None
    contrast_mode: str | None = None
    scalar_share: bool = False
    return_value: bool = True
    output_mode: str = "scalar"
    share: bool = False


def _quoted_values(text: str) -> list[str]:
    pattern = re.compile(r"(?<!\w)(?P<quote>['\"])(?P<value>[^'\"]{1,160})(?P=quote)(?!\w)")
    return [space(match.group("value")) for match in pattern.finditer(text)]


def _extract_number(text: str) -> int | None:
    match = re.search(r"\b(\d[\d,]*)\b", text)
    if match:
        return int(match.group(1).replace(",", ""))
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "twenty": 20, "fifty": 50, "hundred": 100,
    }
    for word, value in words.items():
        if re.search(rf"\b{word}\b", text):
            return value
    return None


def _dimension_from_question(text: str) -> list[str]:
    noun_patterns = {
        "artist": r"artists?",
        "title": r"(?:tracks?|songs?|titles?)",
        "album": r"albums?",
        "country": r"countr(?:y|ies)",
        "store": r"(?:stores?|platforms?)",
        "language": r"languages?",
        "year": r"(?:publication\s+|release\s+)?years?",
        "decade": r"(?:publication\s+|release\s+)?decades?",
    }
    result: list[str] = []
    for dimension, noun in noun_patterns.items():
        patterns = (
            rf"\bwhich\s+(?:\d+\s+|top\s+\d+\s+)?{noun}\b",
            rf"\bwhat\s+(?:are\s+|is\s+)?(?:the\s+)?(?:top|bottom|highest|lowest|most|least)?\s*(?:\d+\s+)?{noun}\b",
            rf"\b(?:top|bottom)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+{noun}\b",
            rf"\b{noun}\s+(?:had|has|have|generated|earned|sold|produced|accounted|with)\b",
            rf"\b(?:by|per|for each|grouped by|broken down by)\s+{noun}\b",
        )
        if any(re.search(pattern, text) for pattern in patterns):
            result.append(dimension)
    return result


def _measure_from_text(text: str) -> str:
    if any(phrase in text for phrase in ("revenue per unit", "revenue per copy", "average selling price")):
        return "revenue_per_unit"
    if any(phrase in text for phrase in ("revenue", "sales revenue", "money", "income", "gross revenue", "dollars", " usd")):
        return "revenue_usd"
    if any(phrase in text for phrase in ("units sold", "unit sales", "copies sold", "sales volume", "number of units", "most units", "fewest units")):
        return "units_sold"
    if any(phrase in text for phrase in ("distinct tracks", "unique tracks", "different tracks", "distinct songs", "unique songs")):
        return "distinct_tracks"
    if any(phrase in text for phrase in ("distinct artists", "unique artists", "different artists")):
        return "distinct_artists"
    if any(phrase in text for phrase in ("distinct albums", "unique albums", "different albums")):
        return "distinct_albums"
    if any(phrase in text for phrase in ("transactions", "sales transactions", "number of sales", "sale records")):
        return "transactions"
    if any(phrase in text for phrase in ("length", "duration", "track length")):
        return "length_seconds"
    if re.search(r"\b(?:tracks?|songs?)\b", text):
        return "track_count"
    return "revenue_usd"


def _extract_filters(text: str, known_entities: Mapping[str, Sequence[str]] | None) -> list[Predicate]:
    predicates: list[Predicate] = []
    lowered = text.casefold()

    for country in COUNTRIES:
        if re.search(rf"\b{re.escape(country.casefold())}\b", lowered):
            predicates.append(Predicate("country", "eq", country))
    country_adjectives = {
        "american": "USA",
        "u.s.": "USA",
        "us": "USA",
        "british": "UK",
        "canadian": "Canada",
        "german": "Germany",
        "french": "France",
    }
    if not any(predicate.field == "country" for predicate in predicates):
        for adjective, country in country_adjectives.items():
            if re.search(rf"\b{re.escape(adjective)}\b", lowered):
                predicates.append(Predicate("country", "eq", country))
                break
    for store in STORES:
        if re.search(rf"\b{re.escape(store.casefold())}\b", lowered):
            predicates.append(Predicate("store", "eq", store))
    for alias, language in LANGUAGE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}(?:-language)?\b", lowered):
            predicates.append(Predicate("language", "eq", language))
            break

    match = re.search(r"\b(?:between|from)\s+(18\d{2}|19\d{2}|20\d{2})\s+(?:and|to|through|-)\s+(18\d{2}|19\d{2}|20\d{2})\b", lowered)
    if match:
        start, end = sorted((int(match.group(1)), int(match.group(2))))
        predicates.extend((Predicate("year", "ge", start), Predicate("year", "le", end)))
    else:
        match = re.search(r"\b(?:since|from|after)\s+(18\d{2}|19\d{2}|20\d{2})\b", lowered)
        if match:
            year = int(match.group(1)) + (1 if "after" in match.group(0) else 0)
            predicates.append(Predicate("year", "ge", year))
        match = re.search(r"\b(?:before|until|through|up to)\s+(18\d{2}|19\d{2}|20\d{2})\b", lowered)
        if match:
            year = int(match.group(1)) - (1 if "before" in match.group(0) else 0)
            predicates.append(Predicate("year", "le", year))
        match = re.search(r"\b(?:in|during|released in|published in)\s+(18\d{2}|19\d{2}|20\d{2})\b", lowered)
        if match and not any(predicate.field == "year" for predicate in predicates):
            predicates.append(Predicate("year", "eq", int(match.group(1))))
        match = re.search(r"\b(18\d0s|19\d0s|20\d0s)\b", lowered)
        if match:
            decade = int(match.group(1)[:4])
            predicates.append(Predicate("decade", "eq", decade))

    quotes = _quoted_values(text)
    possessive = re.search(
        r"\b(?:by|from)\s+([A-ZÀ-ÖØ-Þ][^?,'\"]{1,100}?)(?=\s+(?:in|on|at|from|during|between|since|through|with|that|who|whose|$))",
        text,
    )
    artist_possessive = re.search(
        r"\bfrom\s+([^?,'\"]{1,80}?)['’]s\s+(?:song|track|album)\b",
        text,
        re.IGNORECASE,
    )
    if not artist_possessive:
        artist_possessive = re.search(
            r"\b((?:[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ.&-]*\s*){1,5})['’]s\s+(?:song|track|album)\b",
            text,
        )
    if artist_possessive:
        predicates.append(Predicate("artist", "fuzzy", space(artist_possessive.group(1))))
    elif possessive:
        candidate = space(possessive.group(1))
        if candidate and fold(candidate) not in {"all artists", "each artist", "artist"}:
            predicates.append(Predicate("artist", "fuzzy", candidate))

    if quotes:
        for quote in quotes:
            prefix = lowered[: lowered.find(quote.casefold())] if quote.casefold() in lowered else lowered
            if re.search(r"\balbum\b[^'\"]*$", prefix[-80:]):
                predicates.append(Predicate("album", "fuzzy", quote))
            else:
                predicates.append(Predicate("title", "fuzzy", quote))

    if known_entities:
        occupied = {(predicate.field, key(predicate.value)) for predicate in predicates}
        for dimension in ("artist", "album", "title"):
            values = sorted(
                {space(value) for value in known_entities.get(dimension, ()) if space(value)},
                key=lambda value: (-len(value), value.casefold()),
            )
            for value in values:
                normalized = fold(value)
                if len(normalized) < 3:
                    continue
                if re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", fold(text)):
                    marker = (dimension, key(value))
                    if marker not in occupied:
                        predicates.append(Predicate(dimension, "fuzzy", value))
                        occupied.add(marker)
                    break
    return predicates


def plan_query(query: str, known_entities: Mapping[str, Sequence[str]] | None = None) -> Plan:
    text = space(query)
    lowered = text.casefold()
    measure = _measure_from_text(lowered)
    group_by = _dimension_from_question(lowered)
    predicates = _extract_filters(text, known_entities)

    if measure in {"transactions", "track_count", "distinct_tracks", "distinct_artists", "distinct_albums"}:
        aggregate = "count"
    elif any(phrase in lowered for phrase in ("average", "mean", "on average")):
        aggregate = "mean"
    elif "median" in lowered:
        aggregate = "median"
    elif measure == "revenue_per_unit":
        aggregate = "ratio"
    else:
        aggregate = "sum"

    if any(word in lowered for word in ("highest", "most", "largest", "greatest", "top", "best")):
        direction = "max"
    elif any(word in lowered for word in ("lowest", "least", "smallest", "fewest", "bottom", "worst")):
        direction = "min"
    else:
        direction = None

    top_k = 1
    match = re.search(r"\btop\s+(\d+)\b", lowered)
    if match:
        top_k = max(1, int(match.group(1)))
    else:
        word_numbers = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
        for word, number in word_numbers.items():
            if re.search(rf"\btop\s+{word}\b", lowered):
                top_k = number
                break

    min_support = None
    support_field = "entity_id"
    match = re.search(
        r"\b(?:at least|minimum of|no fewer than)\s+(\d[\d,]*)\s+"
        r"(distinct\s+)?(tracks?|songs?|artists?|albums?|sales?|transactions?|units?)\b",
        lowered,
    )
    if match:
        min_support = int(match.group(1).replace(",", ""))
        noun = match.group(3)
        support_field = {
            "track": "entity_id", "tracks": "entity_id", "song": "entity_id", "songs": "entity_id",
            "artist": "artist", "artists": "artist", "album": "album", "albums": "album",
            "sale": "sale_id", "sales": "sale_id", "transaction": "sale_id", "transactions": "sale_id",
            "unit": "units_sold", "units": "units_sold",
        }[noun]

    having_operator = None
    having_value = None
    having_match = re.search(
        r"\b(at least|more than|over|greater than|above|at most|less than|under|below)\s+"
        r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*"
        r"(?:usd|dollars?)?\s*(?:in\s+)?"
        r"(revenue|units?(?:\s+sold)?|transactions?|sales?\s+transactions?)\b",
        lowered,
    )
    if having_match:
        phrase = having_match.group(1)
        having_operator = {
            "at least": "ge", "more than": "gt", "over": "gt",
            "greater than": "gt", "above": "gt", "at most": "le",
            "less than": "lt", "under": "lt", "below": "lt",
        }[phrase]
        having_value = float(having_match.group(2).replace(",", ""))
        unit = having_match.group(3)
        if "revenue" in unit:
            measure = "revenue_usd"
            aggregate = "sum"
        elif "unit" in unit:
            measure = "units_sold"
            aggregate = "sum"
        else:
            measure = "transactions"
            aggregate = "count"

    coverage_field = None
    coverage_min = None
    if re.search(r"\b(?:all|every)\s+(?:five|5)?\s*(?:countries|markets)\b", lowered):
        coverage_field, coverage_min = "country", len(COUNTRIES)
    elif re.search(r"\b(?:all|every)\s+(?:five|5)?\s*(?:stores|platforms)\b", lowered):
        coverage_field, coverage_min = "store", len(STORES)

    normalize_by = None
    normalize_patterns = (
        ("entity_id", r"\bper\s+(?:distinct|unique)?\s*(?:track|song)\b"),
        ("artist", r"\bper\s+(?:distinct|unique)?\s*artist\b"),
        ("album", r"\bper\s+(?:distinct|unique)?\s*album\b"),
        ("sale_id", r"\bper\s+(?:sale|transaction)\b"),
    )
    for field_name, pattern in normalize_patterns:
        if re.search(pattern, lowered):
            normalize_by = field_name
            break

    share = any(word in lowered for word in ("share", "percentage", "proportion", "percent"))
    if share and measure == "revenue_usd":
        aggregate = "share"

    contrast_field = None
    contrast_left = None
    contrast_right = None
    contrast_mode = None
    if any(token in lowered for token in (" than ", "ratio", "difference between", "compared with", "versus", " vs ")):
        for field_name, values in (("country", COUNTRIES), ("store", STORES)):
            positions = []
            for value in values:
                match_value = re.search(rf"\b{re.escape(value.casefold())}\b", lowered)
                if match_value:
                    positions.append((match_value.start(), value))
            positions.sort()
            if len(positions) >= 2:
                contrast_field = field_name
                contrast_left, contrast_right = positions[0][1], positions[1][1]
                contrast_mode = "ratio" if "ratio" in lowered else "difference"
                predicates = [
                    predicate for predicate in predicates
                    if not (
                        predicate.field == field_name
                        and key(predicate.value) in {key(contrast_left), key(contrast_right)}
                    )
                ]
                break

    count_groups = bool(re.search(
        r"^\s*how many\s+(?:distinct|unique|different)?\s*"
        r"(?:artists?|albums?|tracks?|songs?|countries|stores?|platforms?|languages?|years?|decades?)\b",
        lowered,
    ) and group_by)

    output_mode = "ranking" if group_by else "scalar"
    if count_groups:
        output_mode = "group_count"
    elif direction is not None and not group_by:
        group_by = ["title"]
        output_mode = "ranking"

    scalar_share = share and not group_by
    numeric_question = bool(
        re.search(
            r"^(?:how much|how many|what is|what was|calculate|compute)\b",
            lowered,
        )
        or any(word in lowered for word in ("percentage", "proportion", "ratio", "average", "mean", "total"))
    )
    return_value = numeric_question or not bool(
        re.match(r"^(?:which|what|name|identify)\b", lowered)
    )

    return Plan(
        predicates=predicates,
        group_by=group_by,
        measure=measure,
        aggregate=aggregate,
        direction=direction,
        top_k=top_k,
        min_support=min_support,
        support_field=support_field,
        support_distinct=support_field != "units_sold",
        having_operator=having_operator,
        having_value=having_value,
        count_groups=count_groups,
        coverage_field=coverage_field,
        coverage_min=coverage_min,
        normalize_by=normalize_by,
        contrast_field=contrast_field,
        contrast_left=contrast_left,
        contrast_right=contrast_right,
        contrast_mode=contrast_mode,
        scalar_share=scalar_share,
        return_value=return_value,
        output_mode=output_mode,
        share=share,
    )


def _fuzzy_equal(actual: Any, expected: Any, field: str) -> bool:
    if field == "artist":
        left, right = artist_key(actual), artist_key(expected)
    elif field == "title":
        left, right = title_key(actual), title_key(expected)
    elif field == "album":
        left, right = album_key(actual), album_key(expected)
    else:
        left, right = key(actual), key(expected)
    if not left or not right:
        return False
    return left == right or left in right or right in left or _ratio(left, right) >= 0.90


def _predicate_matches(fact: Fact, predicate: Predicate) -> bool:
    actual = getattr(fact, predicate.field)
    if predicate.operator == "eq":
        if isinstance(actual, (int, float)) and isinstance(predicate.value, (int, float)):
            return actual == predicate.value
        return key(actual) == key(predicate.value)
    if predicate.operator == "fuzzy":
        return _fuzzy_equal(actual, predicate.value, predicate.field)
    if actual is None:
        return False
    if predicate.operator == "ge":
        return actual >= predicate.value
    if predicate.operator == "le":
        return actual <= predicate.value
    if predicate.operator == "gt":
        return actual > predicate.value
    if predicate.operator == "lt":
        return actual < predicate.value
    if predicate.operator == "ne":
        return key(actual) != key(predicate.value)
    raise ValueError(f"unsupported predicate operator: {predicate.operator}")


def _support_value(rows: Sequence[Fact], field: str, distinct: bool) -> float:
    if field == "units_sold":
        return sum(row.units_sold for row in rows)
    values = [getattr(row, field) for row in rows]
    return float(len(set(values)) if distinct else len(values))


def _measure_value(rows: Sequence[Fact], plan: Plan) -> float | None:
    if not rows:
        return None
    if plan.measure == "revenue_usd":
        values = [row.revenue_usd for row in rows]
    elif plan.measure == "units_sold":
        values = [row.units_sold for row in rows]
    elif plan.measure == "transactions":
        return float(len({row.sale_id for row in rows}))
    elif plan.measure in {"track_count", "distinct_tracks"}:
        return float(len({row.entity_id for row in rows}))
    elif plan.measure == "distinct_artists":
        return float(len({key(row.artist) for row in rows if row.artist}))
    elif plan.measure == "distinct_albums":
        return float(len({key(row.album) for row in rows if row.album}))
    elif plan.measure == "length_seconds":
        values = [row.length_seconds for row in rows if row.length_seconds is not None]
    elif plan.measure == "revenue_per_unit":
        units = sum(row.units_sold for row in rows)
        return sum(row.revenue_usd for row in rows) / units if units else None
    else:
        raise ValueError(f"unsupported measure: {plan.measure}")

    if not values:
        return None
    if plan.aggregate == "mean":
        return float(sum(values) / len(values))
    if plan.aggregate == "median":
        return float(statistics.median(values))
    if plan.aggregate == "count":
        return float(len(values))
    return float(sum(values))


def _compare(value: float, operator: str | None, threshold: float | None) -> bool:
    if operator is None or threshold is None:
        return True
    return {
        "ge": value >= threshold,
        "gt": value > threshold,
        "le": value <= threshold,
        "lt": value < threshold,
        "eq": value == threshold,
    }[operator]


def _sum_plan(plan: Plan) -> Plan:
    return Plan(measure=plan.measure, aggregate="sum")


def evaluate(plan: Plan, facts: Sequence[Fact]) -> Any:
    filtered = [
        fact for fact in facts
        if all(_predicate_matches(fact, predicate) for predicate in plan.predicates)
    ]

    if not plan.group_by:
        if plan.contrast_field and plan.contrast_left is not None and plan.contrast_right is not None:
            left_rows = [
                fact for fact in filtered
                if key(getattr(fact, plan.contrast_field)) == key(plan.contrast_left)
            ]
            right_rows = [
                fact for fact in filtered
                if key(getattr(fact, plan.contrast_field)) == key(plan.contrast_right)
            ]
            left = _measure_value(left_rows, _sum_plan(plan))
            right = _measure_value(right_rows, _sum_plan(plan))
            if left is None or right is None:
                return None
            if plan.contrast_mode == "ratio":
                return left / right if right else None
            return left - right

        numerator = _measure_value(filtered, plan)
        if not plan.scalar_share:
            return numerator

        denominator_field = next(
            (
                field_name
                for field_name in ("store", "country", "artist", "title", "album", "language")
                if any(predicate.field == field_name for predicate in plan.predicates)
            ),
            None,
        )
        denominator_predicates = [
            predicate for predicate in plan.predicates
            if predicate.field != denominator_field
        ]
        denominator_rows = [
            fact for fact in facts
            if all(_predicate_matches(fact, predicate) for predicate in denominator_predicates)
        ]
        denominator = _measure_value(denominator_rows, _sum_plan(plan))
        return numerator / denominator if numerator is not None and denominator not in (None, 0) else None

    grouped: dict[tuple[Any, ...], list[Fact]] = defaultdict(list)
    for fact in filtered:
        label = tuple(getattr(fact, dimension) for dimension in plan.group_by)
        grouped[label].append(fact)

    scored: list[tuple[tuple[Any, ...], float]] = []
    total = _measure_value(filtered, _sum_plan(plan))
    for label, rows in grouped.items():
        if plan.min_support is not None and _support_value(
            rows, plan.support_field, plan.support_distinct
        ) < plan.min_support:
            continue
        if (
            plan.coverage_field is not None
            and plan.coverage_min is not None
            and len({key(getattr(row, plan.coverage_field)) for row in rows}) < plan.coverage_min
        ):
            continue

        if plan.contrast_field and plan.contrast_left is not None and plan.contrast_right is not None:
            left_rows = [
                row for row in rows
                if key(getattr(row, plan.contrast_field)) == key(plan.contrast_left)
            ]
            right_rows = [
                row for row in rows
                if key(getattr(row, plan.contrast_field)) == key(plan.contrast_right)
            ]
            left = _measure_value(left_rows, _sum_plan(plan))
            right = _measure_value(right_rows, _sum_plan(plan))
            if left is None or right is None:
                continue
            if plan.contrast_mode == "ratio":
                if right == 0:
                    continue
                value = left / right
            else:
                value = left - right
                if plan.direction is None and value <= 0:
                    continue
        else:
            value = _measure_value(rows, plan)

        if value is None or not math.isfinite(value):
            continue
        if plan.normalize_by:
            denominator = _support_value(rows, plan.normalize_by, True)
            if denominator == 0:
                continue
            value /= denominator
        if plan.aggregate == "share":
            if total in (None, 0):
                continue
            value /= total
        if not _compare(float(value), plan.having_operator, plan.having_value):
            continue
        scored.append((label, float(value)))

    if plan.count_groups:
        return len(scored)
    if not scored:
        return []
    if plan.direction is None:
        scored.sort(key=lambda item: tuple(key(value) for value in item[0]))
        return scored
    reverse = plan.direction == "max"
    scored.sort(
        key=lambda item: (
            -item[1] if reverse else item[1],
            tuple(key(value) for value in item[0]),
        )
    )
    return scored[: plan.top_k]


def _format_label(label: tuple[Any, ...]) -> str:
    return ":".join(space(value) for value in label)


def render_answer(answer: Any, plan: Plan) -> str:
    if answer is None:
        return ""
    if isinstance(answer, (int, float)):
        if isinstance(answer, float) and answer.is_integer():
            return str(int(answer))
        return f"{answer:.12g}"
    if isinstance(answer, list):
        lines = []
        for label, value in answer:
            label_text = _format_label(label)
            lines.append(f"{label_text}: {value:.12g}" if plan.return_value else label_text)
        return "\n".join(lines)
    return space(answer)


def solve(
    query: str,
    tracks: Sequence[Track],
    sales: Sequence[Sale],
) -> tuple[Plan, Any, str]:
    entities, facts = build_facts(tracks, sales)
    known = {
        "artist": [entity.artist for entity in entities],
        "album": [entity.album for entity in entities],
        "title": [entity.title for entity in entities],
    }
    plan = plan_query(query, known)
    answer = evaluate(plan, facts)
    return plan, answer, render_answer(answer, plan)


def read_query(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, str) else str(payload.get("query") or payload.get("question") or payload)


def write_outputs(output_dir: Path, query_id: str, query: str, plan: Plan, answer: Any) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{query_id}.txt").write_text(render_answer(answer, plan) + "\n", encoding="utf-8")
    (output_dir / f"{query_id}.json").write_text(
        json.dumps(
            {"query": query, "plan": asdict(plan), "answer": answer},
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n",
        encoding="utf-8",
    )
