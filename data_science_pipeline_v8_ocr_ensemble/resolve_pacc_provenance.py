from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import resolve_canonical as canonical
import resolve_pacc as pacc

SOURCE_URL = "https://oncae.gob.hn/wp-content/uploads/2024/05/Conceptos-basicos-PACC-ONCAE-2023.pdf"


def load_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve(normalized: Path, output: Path):
    manifest = pacc.resolve_pacc(normalized, output)
    entities_path = output / "entities.jsonl"
    entities = load_jsonl(entities_path)
    ids = {row["entity_id"] for row in entities}
    if "hn:institution:oncae" not in ids:
        source_sha = manifest["source_pdf_sha256"]
        entities.append({
            "schema": "canonical-entity/1",
            "entity_id": "hn:institution:oncae",
            "entity_type": "public_institution",
            "canonical_name": "Oficina Normativa de Contratación y Adquisiciones del Estado",
            "aliases": ["ONCAE"],
            "mention_count": 0,
            "mean_confidence": None,
            "evidence_mention_ids": [],
            "evidence_source_url": SOURCE_URL,
            "evidence_source_pdf_sha256": source_sha,
            "resolution_method": "trusted_source_host_registry",
            "resolution_status": "resolved_from_source_provenance",
        })
        entities.sort(key=lambda row: row["entity_id"])
        meta = pacc.write_jsonl(entities_path, entities)
        manifest["outputs"]["entities.jsonl"] = meta
        manifest["row_counts"]["entities"] = len(entities)
    manifest["checks"]["oncae_resolved"] = any(row["entity_id"] == "hn:institution:oncae" for row in entities)
    manifest["source_provenance"] = {
        "url": SOURCE_URL,
        "host": "oncae.gob.hn",
        "institution_entity_id": "hn:institution:oncae",
        "source_pdf_sha256": manifest["source_pdf_sha256"],
        "claim_scope": "publisher provenance; not an OCR text mention",
    }
    payload = canonical.canonical_json(manifest)
    (output / "resolve-manifest.json").write_bytes(payload)
    (output / "resolve-manifest.sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  resolve-manifest.json\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(resolve(args.normalized, args.output), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
