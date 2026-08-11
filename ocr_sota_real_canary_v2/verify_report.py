from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "ocr-sota-real-canary-v2/report/1"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / max(len(items), 1)


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_engine: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_engine[str(row["engine"])].append(row)
    result: dict[str, Any] = {}
    for engine, engine_rows in sorted(by_engine.items()):
        result[engine] = {
            "pages": len(engine_rows),
            "character_accuracy": mean(max(0.0, 1.0 - float(row["text"]["cer"])) for row in engine_rows),
            "word_accuracy": mean(max(0.0, 1.0 - float(row["text"]["wer"])) for row in engine_rows),
            "numeric_sequence_accuracy": mean(float(row["text"]["numeric_sequence_accuracy"]) for row in engine_rows),
            "numeric_exact_rate": mean(float(bool(row["text"]["numeric_exact"])) for row in engine_rows),
            "text_region_f1": mean(float(row["text_region"]["f1"]) for row in engine_rows),
            "text_region_recall": mean(float(row["text_region"]["recall"]) for row in engine_rows),
            "latency_seconds_per_page": mean(float(row["latency_seconds"]) for row in engine_rows),
        }
    return result


def stable_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in ("schema", "dataset", "input_manifest", "rows", "aggregate", "denominators", "constraints")}


def verify(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    rows = report.get("rows")
    denominators = report.get("denominators")
    if not isinstance(rows, list) or not isinstance(denominators, Mapping):
        return errors + ["shape"]
    pages = int(denominators.get("pages", -1))
    engines = int(denominators.get("engines", -1))
    if len(rows) != pages * engines or int(denominators.get("page_engine_pairs", -1)) != len(rows):
        errors.append("denominator")
    page_ids = {str(row.get("page_id")) for row in rows}
    engine_ids = {str(row.get("engine")) for row in rows}
    if len(page_ids) != pages or len(engine_ids) != engines:
        errors.append("membership")
    pairs = [(str(row.get("page_id")), str(row.get("engine"))) for row in rows]
    if len(pairs) != len(set(pairs)):
        errors.append("duplicate-pair")
    rebuilt = aggregate(rows)
    if canonical_json(rebuilt) != canonical_json(report.get("aggregate")):
        errors.append("aggregate")
    constraints = report.get("constraints") or {}
    if constraints.get("external_spend_usd") != 0 or constraints.get("gcloud_used") is not False or constraints.get("paid_api_used") is not False or constraints.get("gpu_used") is not False:
        errors.append("constraints")
    expected = sha256_bytes(canonical_json(stable_payload(report)).encode("utf-8"))
    if expected != report.get("stable_payload_sha256"):
        errors.append("stable-payload-hash")
    selected = report.get("dataset", {}).get("selected_pages", [])
    manifest = report.get("input_manifest", [])
    if len(selected) != pages or {item.get("page_id") for item in manifest} != set(selected):
        errors.append("input-manifest")
    for row in rows:
        if not row.get("prediction", {}).get("lines"):
            errors.append("empty-prediction")
            break
    return sorted(set(errors))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    errors = verify(report)
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2, sort_keys=True))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
