"""Rebuild the frozen Stage 2 v2 corpus from public Stage 1 summaries.

Pair selectors and labels were frozen from pre-existing Stage 0 adjudications.
Evidence fields are reconstructed from Stage 1 `known_target_hits.json` using
Stage 1's own supplier/object implementation. Policy code never sees labels.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from fin_rvi_002_stage1.identity_v2 import adjudicate_object_v2
from fin_rvi_002_stage1.ocds import ReleaseSummary, closest_amount

CORPUS_SCHEMA = "fin-rvi-002/frozen-adjudication-corpus/2"
MANIFEST_SCHEMA = "fin-rvi-002/frozen-pair-manifest/2"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def candidate_id(target: str, oncae_ocid: str, sefin_ocid: str) -> str:
    return hashlib.sha256(
        f"{target}|{oncae_ocid}|{sefin_ocid}".encode("utf-8")
    ).hexdigest()


def _amount_data(
    left: ReleaseSummary, right: ReleaseSummary
) -> tuple[str | None, str]:
    match = closest_amount(left.amounts, right.amounts)
    if match is None:
        amount = Decimal(str(right.amounts[0] if right.amounts else 0)).quantize(
            Decimal("0.01")
        )
        return None, format(amount, "f")
    relative, _, right_amount = match
    return (
        format(Decimal(str(relative)).quantize(Decimal("0.00000001")), "f"),
        format(Decimal(str(right_amount)).quantize(Decimal("0.01")), "f"),
    )


def build_corpus(
    manifest_path: Path,
    known_target_hits_path: Path,
) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    source_bytes = known_target_hits_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    known_hits = json.loads(source_bytes)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unexpected frozen pair manifest schema")

    index: dict[tuple[str, str, str], ReleaseSummary] = {}
    for target, summaries in known_hits.items():
        for summary in summaries:
            key = (target, summary["source"], summary["ocid"])
            if key in index:
                raise ValueError(f"duplicate known-target summary: {key}")
            index[key] = ReleaseSummary(**summary)

    rows: list[dict[str, Any]] = []
    for pair in manifest["pairs"]:
        target = pair["target"]
        left_key = (target, "ONCAE", pair["oncae_ocid"])
        right_key = (target, "SEFIN", pair["sefin_ocid"])
        if left_key not in index or right_key not in index:
            raise KeyError(f"frozen pair cannot be reconstructed: {left_key} / {right_key}")
        left = index[left_key]
        right = index[right_key]
        expected_candidate = candidate_id(target, left.ocid, right.ocid)
        if expected_candidate != pair["candidate_id"]:
            raise ValueError(f"candidate fingerprint mismatch: {pair['candidate_id']}")
        adjudication = adjudicate_object_v2(left, right)
        relative, amount = _amount_data(left, right)
        rows.append(
            {
                "candidate_id": pair["candidate_id"],
                "split": pair["split"],
                "target": target,
                "gold_rule": pair["gold_rule"],
                "gold_expected": pair["gold_expected"],
                "oncae_ocid": left.ocid,
                "sefin_ocid": right.ocid,
                "oncae_supplier_names": list(left.supplier_names),
                "sefin_supplier_names": list(right.supplier_names),
                "oncae_supplier_ids": list(left.supplier_ids),
                "sefin_supplier_ids": list(right.supplier_ids),
                "supplier_supported": bool(
                    adjudication.get("supplier_identity_supported")
                ),
                "documentary_decision": adjudication["decision"],
                "oncae_object_text": left.object_text,
                "sefin_object_text": right.object_text,
                "oncae_dates": list(left.dates),
                "sefin_dates": list(right.dates),
                "relative_amount_difference": relative,
                "amount_sefin": amount,
            }
        )

    rows.sort(key=lambda row: row["candidate_id"])
    corpus = {
        "schema": CORPUS_SCHEMA,
        "source_hashes": {
            "manifest_file_sha256": sha256_bytes(manifest_bytes),
            "known_target_hits_observed_file_sha256": sha256_bytes(source_bytes),
            "known_target_hits_frozen_file_sha256": manifest[
                "source_known_target_hits_file_sha256"
            ],
            "stage0_cases_file_sha256": manifest["stage0_cases_file_sha256"],
            "stage0_report_file_sha256": manifest["stage0_report_file_sha256"],
        },
        "source_hash_match": (
            sha256_bytes(source_bytes)
            == manifest["source_known_target_hits_file_sha256"]
        ),
        "gold_sources": manifest["gold_sources"],
        "derivation": manifest["derivation"],
        "rows": rows,
    }
    return corpus


def main() -> None:
    root = Path("fin_rvi_002_stage2")
    source = Path("reports/fin_rvi_002_stage1/known_target_hits.json")
    output = Path("reports/fin_rvi_002_stage2_v2/frozen_adjudication_corpus_v2.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    corpus = build_corpus(root / "frozen_pair_manifest_v2.json", source)
    output.write_text(
        json.dumps(corpus, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "rows": len(corpus["rows"]),
                "source_hash_match": corpus["source_hash_match"],
                "corpus_sha256": hashlib.sha256(
                    canonical_json(corpus).encode("utf-8")
                ).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
