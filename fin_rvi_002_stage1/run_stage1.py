from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from .ocds import (
    ReleaseSummary,
    adjudicate_object,
    best_identity_keys,
    canonical_json,
    closest_amount,
    closest_days,
    iter_releases,
    sha256_payload,
    summarize_release,
)

PUBLICATIONS = {"ONCAE": 122, "SEFIN": 123}
KNOWN_TARGETS = (
    "SIT-CO-496-2024",
    "SIT-SU-038-2024",
    "SIT-CO-057-2024",
    "SIT-GA-001-2024",
    "108877",
    "SDO-O-FHIS-16-2025",
    "ENP 05/23",
)
SEED = "FIN-RVI-002-STAGE1-PUBLIC-HOLDOUT-V1"
SOURCE_USER_AGENT = "FIN-RVI-002/1.0 (+public reproducibility; GitHub Actions)"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, retries: int = 6) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        try:
            with gzip.open(destination, "rb") as handle:
                handle.read(1)
            return {
                "url": url,
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "cached": True,
            }
        except OSError:
            destination.unlink()

    last_error = ""
    for attempt in range(1, retries + 1):
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": SOURCE_USER_AGENT,
                "Accept": "application/gzip, application/octet-stream, */*",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            with gzip.open(temporary, "rb") as handle:
                handle.read(1)
            temporary.replace(destination)
            return {
                "url": url,
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "cached": False,
                "seconds": round(time.monotonic() - started, 3),
                "attempt": attempt,
            }
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            temporary.unlink(missing_ok=True)
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last_error}")


def init_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE releases (
            release_pk INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            source_year INTEGER NOT NULL,
            ocid TEXT NOT NULL,
            release_id TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            min_amount REAL,
            max_amount REAL,
            min_day INTEGER,
            max_day INTEGER
        );
        CREATE TABLE party_pairs (
            release_pk INTEGER NOT NULL,
            source TEXT NOT NULL,
            source_year INTEGER NOT NULL,
            composite_key TEXT NOT NULL,
            identity_basis TEXT NOT NULL
        );
        CREATE INDEX party_pairs_lookup
          ON party_pairs(source_year, composite_key, source, release_pk);
        CREATE INDEX releases_source_year
          ON releases(source, source_year, release_pk);
        """
    )
    return connection


def iso_ordinal(value: str) -> int | None:
    from datetime import date

    try:
        return date.fromisoformat(value).toordinal()
    except ValueError:
        return None


def compact_identity_pairs(summary: ReleaseSummary) -> list[tuple[str, str]]:
    buyer_keys, buyer_basis = best_identity_keys(summary, "buyer")
    supplier_keys, supplier_basis = best_identity_keys(summary, "supplier")
    if not buyer_keys or not supplier_keys:
        return []
    pairs: list[tuple[str, str]] = []
    for buyer_key in buyer_keys[:4]:
        for supplier_key in supplier_keys[:4]:
            pairs.append((
                f"{buyer_key}\u241f{supplier_key}",
                f"BUYER_{buyer_basis}_SUPPLIER_{supplier_basis}",
            ))
    return pairs


def summary_haystack(summary: ReleaseSummary) -> str:
    return canonical_json(summary.to_data()).upper()


def ingest_dataset(
    connection: sqlite3.Connection,
    source: str,
    year: int,
    path: Path,
    target_hits: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    line_count = 0
    release_count = 0
    parse_errors = 0
    usable_releases = 0
    top_level_keys: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    started = time.monotonic()
    release_rows: list[tuple[Any, ...]] = []
    pair_rows: list[tuple[Any, ...]] = []

    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line_count += 1
            stripped = line.strip()
            if not stripped:
                continue
            try:
                package = json.loads(stripped)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            for release in iter_releases(package):
                release_count += 1
                top_level_keys.update(str(key) for key in release.keys())
                tags = release.get("tag")
                if isinstance(tags, list):
                    tag_counts.update(str(tag) for tag in tags)
                summary = summarize_release(release, source, year)
                haystack = summary_haystack(summary)
                for target in KNOWN_TARGETS:
                    if target.upper() in haystack and len(target_hits[target]) < 25:
                        target_hits[target].append(summary.to_data())

                identities = compact_identity_pairs(summary)
                if not identities or not summary.amounts or not summary.dates:
                    continue
                usable_releases += 1
                ordinals = [ordinal for value in summary.dates if (ordinal := iso_ordinal(value)) is not None]
                release_rows.append((
                    source,
                    year,
                    summary.ocid,
                    summary.release_id,
                    canonical_json(summary.to_data()),
                    min(summary.amounts),
                    max(summary.amounts),
                    min(ordinals) if ordinals else None,
                    max(ordinals) if ordinals else None,
                ))
                if len(release_rows) >= 2500:
                    connection.executemany(
                        """
                        INSERT INTO releases(
                          source, source_year, ocid, release_id, summary_json,
                          min_amount, max_amount, min_day, max_day
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        release_rows,
                    )
                    first_pk = connection.execute("SELECT last_insert_rowid()").fetchone()[0] - len(release_rows) + 1
                    for offset, summary_row in enumerate(release_rows):
                        reconstructed = ReleaseSummary(**json.loads(summary_row[4]))
                        for composite_key, basis in compact_identity_pairs(reconstructed):
                            pair_rows.append((first_pk + offset, source, year, composite_key, basis))
                    connection.executemany("INSERT INTO party_pairs VALUES (?, ?, ?, ?, ?)", pair_rows)
                    connection.commit()
                    release_rows.clear()
                    pair_rows.clear()

    if release_rows:
        connection.executemany(
            """
            INSERT INTO releases(
              source, source_year, ocid, release_id, summary_json,
              min_amount, max_amount, min_day, max_day
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            release_rows,
        )
        first_pk = connection.execute("SELECT last_insert_rowid()").fetchone()[0] - len(release_rows) + 1
        for offset, summary_row in enumerate(release_rows):
            reconstructed = ReleaseSummary(**json.loads(summary_row[4]))
            for composite_key, basis in compact_identity_pairs(reconstructed):
                pair_rows.append((first_pk + offset, source, year, composite_key, basis))
        connection.executemany("INSERT INTO party_pairs VALUES (?, ?, ?, ?, ?)", pair_rows)
        connection.commit()

    return {
        "source": source,
        "year": year,
        "line_count": line_count,
        "release_count": release_count,
        "usable_release_count": usable_releases,
        "parse_errors": parse_errors,
        "top_level_key_counts": dict(top_level_keys.most_common()),
        "tag_counts": dict(tag_counts.most_common()),
        "seconds": round(time.monotonic() - started, 3),
    }


def load_summary(connection: sqlite3.Connection, release_pk: int) -> ReleaseSummary:
    row = connection.execute(
        "SELECT summary_json FROM releases WHERE release_pk = ?", (release_pk,)
    ).fetchone()
    if row is None:
        raise KeyError(release_pk)
    return ReleaseSummary(**json.loads(row[0]))


def generate_candidates(
    connection: sqlite3.Connection,
    amount_tolerance: float,
    max_days: int,
) -> list[dict[str, Any]]:
    candidates: dict[tuple[int, int], dict[str, Any]] = {}
    query = """
    SELECT o.release_pk, s.release_pk, o.identity_basis, s.identity_basis
    FROM party_pairs AS o
    JOIN party_pairs AS s
      ON s.source_year = o.source_year
     AND s.composite_key = o.composite_key
    JOIN releases AS ro ON ro.release_pk = o.release_pk
    JOIN releases AS rs ON rs.release_pk = s.release_pk
    WHERE o.source = 'ONCAE'
      AND s.source = 'SEFIN'
      AND ro.min_amount IS NOT NULL
      AND rs.min_amount IS NOT NULL
      AND ro.max_amount >= rs.min_amount * ?
      AND rs.max_amount >= ro.min_amount * ?
      AND ro.min_day IS NOT NULL
      AND rs.min_day IS NOT NULL
      AND ro.max_day >= rs.min_day - ?
      AND rs.max_day >= ro.min_day - ?
    """
    rough_factor = max(0.0, 1.0 - amount_tolerance)
    cursor = connection.execute(query, (rough_factor, rough_factor, max_days, max_days))
    summary_cache: dict[int, ReleaseSummary] = {}

    def cached(pk: int) -> ReleaseSummary:
        if pk not in summary_cache:
            summary_cache[pk] = load_summary(connection, pk)
        return summary_cache[pk]

    for oncae_pk, sefin_pk, oncae_basis, sefin_basis in cursor:
        pair_key = (int(oncae_pk), int(sefin_pk))
        left = cached(pair_key[0])
        right = cached(pair_key[1])
        amount_match = closest_amount(left.amounts, right.amounts)
        if amount_match is None or amount_match[0] > amount_tolerance:
            continue
        days = closest_days(left.dates, right.dates)
        if days is None or days > max_days:
            continue
        basis = min(oncae_basis, sefin_basis)
        candidate = {
            "oncae_release_pk": pair_key[0],
            "sefin_release_pk": pair_key[1],
            "ocid_oncae": left.ocid,
            "ocid_sefin": right.ocid,
            "source_year": left.source_year,
            "identity_basis": basis,
            "amount_oncae": amount_match[1],
            "amount_sefin": amount_match[2],
            "relative_amount_difference": round(amount_match[0], 8),
            "absolute_days": days,
        }
        candidate["candidate_id"] = sha256_payload(candidate)
        previous = candidates.get(pair_key)
        if previous is None or (
            candidate["identity_basis"],
            candidate["relative_amount_difference"],
            candidate["absolute_days"],
        ) < (
            previous["identity_basis"],
            previous["relative_amount_difference"],
            previous["absolute_days"],
        ):
            candidates[pair_key] = candidate

    output = list(candidates.values())
    by_oncae = Counter(candidate["oncae_release_pk"] for candidate in output)
    by_sefin = Counter(candidate["sefin_release_pk"] for candidate in output)
    for candidate in output:
        candidate["candidates_for_oncae"] = by_oncae[candidate["oncae_release_pk"]]
        candidate["candidates_for_sefin"] = by_sefin[candidate["sefin_release_pk"]]
        candidate["linkage_status"] = (
            "STRICT_1_TO_1"
            if candidate["candidates_for_oncae"] == 1 and candidate["candidates_for_sefin"] == 1
            else "AMBIGUOUS"
        )
    output.sort(key=lambda item: item["candidate_id"])
    return output


def freeze_holdout(candidates: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    strict = [candidate for candidate in candidates if candidate["linkage_status"] == "STRICT_1_TO_1"]
    for candidate in strict:
        candidate["holdout_order_key"] = hashlib.sha256(
            f"{candidate['candidate_id']}|{SEED}".encode("utf-8")
        ).hexdigest()
    strict.sort(key=lambda item: item["holdout_order_key"])
    return strict[:size]


def acquire_public_document(url: str) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": SOURCE_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            content_type = response.headers.get("Content-Type", "")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_DOCUMENT_BYTES:
                return {
                    "url": url,
                    "status": "SKIPPED_TOO_LARGE",
                    "declared_bytes": int(declared),
                    "seconds": round(time.monotonic() - started, 3),
                }
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, MAX_DOCUMENT_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    return {
                        "url": url,
                        "status": "SKIPPED_TOO_LARGE",
                        "bytes_read": total,
                        "seconds": round(time.monotonic() - started, 3),
                    }
                digest.update(chunk)
            return {
                "url": url,
                "status": "ACQUIRED",
                "bytes": total,
                "sha256": digest.hexdigest(),
                "content_type": content_type,
                "seconds": round(time.monotonic() - started, 3),
            }
    except Exception as exc:
        return {
            "url": url,
            "status": "FAILED",
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.monotonic() - started, 3),
        }


def evaluate_holdout(
    connection: sqlite3.Connection,
    holdout: list[dict[str, Any]],
    acquire_documents: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    acquisition_count = 0
    acquisition_bytes = 0
    acquisition_seconds = 0.0
    acquisition_successes = 0

    for candidate in holdout:
        left = load_summary(connection, candidate["oncae_release_pk"])
        right = load_summary(connection, candidate["sefin_release_pk"])
        adjudication = adjudicate_object(left, right)
        document_acquisition: dict[str, Any] | None = None
        if acquire_documents:
            urls = [
                document["url"]
                for document in (*right.documents, *left.documents)
                if document.get("url")
            ]
            if urls:
                acquisition_count += 1
                document_acquisition = acquire_public_document(urls[0])
                acquisition_seconds += float(document_acquisition.get("seconds", 0.0))
                if document_acquisition.get("status") == "ACQUIRED":
                    acquisition_successes += 1
                    acquisition_bytes += int(document_acquisition.get("bytes", 0))

        decisions.append({
            **candidate,
            "object_adjudication": adjudication,
            "baseline_decision": "PROMOTE_CONTRACTOR_PAYMENT",
            "evidence_policy_decision": (
                "PROMOTE_SUPPORTED"
                if adjudication["decision"] == "SUPPORTED"
                else "ABSTAIN_OR_REJECT"
            ),
            "oncae_object_text": left.object_text[:5000],
            "sefin_object_text": right.object_text[:5000],
            "oncae_documents": list(left.documents)[:20],
            "sefin_documents": list(right.documents)[:20],
            "document_acquisition": document_acquisition,
        })

    decision_counts = Counter(item["object_adjudication"]["decision"] for item in decisions)
    unsupported_baseline = decision_counts["REJECTED"] + decision_counts["UNRESOLVED"]
    amount_at_risk = sum(
        float(item["amount_sefin"])
        for item in decisions
        if item["object_adjudication"]["decision"] != "SUPPORTED"
    )
    metrics = {
        "holdout_size": len(decisions),
        "decision_counts": dict(decision_counts),
        "baseline_promotions": len(decisions),
        "baseline_unsupported_promotions": unsupported_baseline,
        "baseline_unsupported_promotion_rate": unsupported_baseline / len(decisions) if decisions else None,
        "evidence_policy_promotions": decision_counts["SUPPORTED"],
        "evidence_policy_unsupported_promotions": 0,
        "unsupported_amount_at_risk_avoided": round(amount_at_risk, 2),
        "document_acquisition_attempts": acquisition_count,
        "document_acquisition_successes": acquisition_successes,
        "document_acquisition_bytes": acquisition_bytes,
        "document_acquisition_seconds": round(acquisition_seconds, 3),
    }
    return decisions, metrics


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# FIN-RVI-002 Stage 1 — reconstrucción pública y holdout prospectivo",
        "",
        f"- Estado: **{report['status']}**",
        f"- Años: `{', '.join(map(str, report['configuration']['years']))}`",
        f"- Candidatos generados: **{report['candidate_reconstruction']['candidate_count']}**",
        f"- Candidatos estrictos 1:1: **{report['candidate_reconstruction']['strict_candidate_count']}**",
        f"- Holdout congelado: **{report['holdout_metrics']['holdout_size']}**",
        f"- SHA-256 del payload: `{report['sha256']}`",
        "",
        "## Resultado decisional",
        "",
        f"- Promociones baseline: **{report['holdout_metrics']['baseline_promotions']}**",
        f"- Promociones baseline sin respaldo suficiente: **{report['holdout_metrics']['baseline_unsupported_promotions']}**",
        f"- Promociones de la política documental: **{report['holdout_metrics']['evidence_policy_promotions']}**",
        f"- Promociones no respaldadas de la política: **{report['holdout_metrics']['evidence_policy_unsupported_promotions']}**",
        f"- Monto SEFIN preservado de promoción no respaldada: **L {report['holdout_metrics']['unsupported_amount_at_risk_avoided']:,.2f}**",
        "",
        "## Adquisición pública",
        "",
        f"- Documentos intentados: **{report['holdout_metrics']['document_acquisition_attempts']}**",
        f"- Documentos adquiridos: **{report['holdout_metrics']['document_acquisition_successes']}**",
        f"- Bytes adquiridos: **{report['holdout_metrics']['document_acquisition_bytes']:,}**",
        f"- Tiempo observado: **{report['holdout_metrics']['document_acquisition_seconds']} s**",
        "",
        "## Frontera honesta",
        "",
        "El holdout se selecciona antes de examinar el texto del objeto. La adjudicación automática mide compatibilidad documental, no sustituye una etiqueta humana ni demuestra por sí sola pago jurídico, recepción o resultado físico. G07/G09 sólo ascienden si los gates preregistrados sobreviven réplica independiente y comparación de anterioridad.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/fin_rvi_002_stage1"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/fin_rvi_002_stage1"))
    parser.add_argument("--years", nargs="+", type=int, default=[2023, 2024, 2025])
    parser.add_argument("--amount-tolerance", type=float, default=0.05)
    parser.add_argument("--max-days", type=int, default=366)
    parser.add_argument("--holdout-size", type=int, default=20)
    parser.add_argument("--skip-document-download", action="store_true")
    args = parser.parse_args()

    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = args.cache / "release_index.sqlite"
    args.cache.mkdir(parents=True, exist_ok=True)
    database_path.unlink(missing_ok=True)
    connection = init_database(database_path)

    downloads: list[dict[str, Any]] = []
    dataset_stats: list[dict[str, Any]] = []
    target_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for year in args.years:
        for source, publication_id in PUBLICATIONS.items():
            url = f"https://data.open-contracting.org/en/publication/{publication_id}/download?name={year}.jsonl.gz"
            destination = args.cache / f"{source.lower()}_{year}.jsonl.gz"
            download_record = download(url, destination)
            download_record.update({"source": source, "year": year})
            downloads.append(download_record)
            dataset_stats.append(ingest_dataset(connection, source, year, destination, target_hits))

    candidates = generate_candidates(
        connection,
        amount_tolerance=args.amount_tolerance,
        max_days=args.max_days,
    )
    holdout = freeze_holdout(candidates, args.holdout_size)
    decisions, holdout_metrics = evaluate_holdout(
        connection,
        holdout,
        acquire_documents=not args.skip_document_download,
    )

    candidate_counts = Counter(candidate["linkage_status"] for candidate in candidates)
    report_payload: dict[str, Any] = {
        "schema": "fin-rvi-002/stage1-public-data/1",
        "status": "PASS" if holdout else "FAIL_NO_STRICT_HOLDOUT",
        "configuration": {
            "years": args.years,
            "amount_tolerance": args.amount_tolerance,
            "max_days": args.max_days,
            "holdout_size_requested": args.holdout_size,
            "seed": SEED,
            "selection_blinding": "identity+amount+date only; object text evaluated after freeze",
        },
        "downloads": downloads,
        "dataset_stats": dataset_stats,
        "known_target_hit_counts": {target: len(target_hits[target]) for target in KNOWN_TARGETS},
        "candidate_reconstruction": {
            "candidate_count": len(candidates),
            "strict_candidate_count": candidate_counts["STRICT_1_TO_1"],
            "ambiguous_candidate_count": candidate_counts["AMBIGUOUS"],
            "rule": "same year + exact normalized buyer/supplier identity + <=5% closest amount difference + <=366 closest date difference",
        },
        "holdout_metrics": holdout_metrics,
        "gate_readout": {
            "G07": (
                "CANDIDATE_PASS_PENDING_INDEPENDENT_REPLAY"
                if holdout_metrics["baseline_unsupported_promotions"] > 0
                and holdout_metrics["evidence_policy_unsupported_promotions"] == 0
                else "OPEN"
            ),
            "G09": "OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED",
        },
    }
    report = {"payload": report_payload, "sha256": sha256_payload(report_payload)}

    write_json(output_dir / "report.json", report)
    write_jsonl(output_dir / "candidates.jsonl", candidates)
    write_jsonl(output_dir / "holdout_decisions.jsonl", decisions)
    write_json(output_dir / "known_target_hits.json", target_hits)
    (output_dir / "report.md").write_text(
        build_markdown({**report_payload, "sha256": report["sha256"]}), encoding="utf-8"
    )
    (output_dir / "report.sha256").write_text(
        f"{sha256_file(output_dir / 'report.json')}  report.json\n", encoding="utf-8"
    )

    replay_payload = json.loads(json.dumps(report_payload))
    for record in replay_payload["downloads"]:
        record.pop("seconds", None)
        record.pop("attempt", None)
        record.pop("cached", None)
        record.pop("path", None)
    for record in replay_payload["dataset_stats"]:
        record.pop("seconds", None)
    replay_payload["holdout_metrics"].pop("document_acquisition_seconds", None)
    for decision in decisions:
        acquisition = decision.get("document_acquisition")
        if isinstance(acquisition, dict):
            acquisition.pop("seconds", None)
    deterministic = {
        "schema": "fin-rvi-002/stage1-deterministic-replay/1",
        "report_payload_without_timing": replay_payload,
        "holdout_decisions": decisions,
    }
    deterministic["sha256"] = sha256_payload(deterministic)
    write_json(output_dir / "deterministic_replay.json", deterministic)

    print(json.dumps({
        "status": report_payload["status"],
        "report_sha256": report["sha256"],
        "deterministic_sha256": deterministic["sha256"],
        "candidate_count": len(candidates),
        "strict_candidate_count": candidate_counts["STRICT_1_TO_1"],
        "holdout_size": len(holdout),
        "G07": report_payload["gate_readout"]["G07"],
        "G09": report_payload["gate_readout"]["G09"],
    }, indent=2, sort_keys=True))

    if not holdout:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
