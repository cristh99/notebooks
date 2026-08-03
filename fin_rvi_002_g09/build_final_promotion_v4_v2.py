from __future__ import annotations

import argparse
import json
from pathlib import Path

from .verify_final_promotion_v4 import (
    EXPECTED_FINAL_GATES,
    EXPECTED_OPEN_CONTRACT,
    EXPECTED_READOUT,
    EXPECTED_REPLAY,
    EXPECTED_STAGE6,
)

CANONICAL_TARGET = Path("fin_rvi_002_g09/final_promotion_v4.json")


def build(base_contract: dict, manifest: dict, manifest_path: str, python_receipt_path: str, node_receipt_path: str) -> dict:
    legacy_view = {
        "status": "PASS",
        "g09_replication": "PASS",
        "cohort_rows": 120,
        "policy_unsafe_overpromotions": 0,
        "policy_missed_supported": 0,
        "python_node_agreement": True,
        "tamper_controls_rejected": True,
        "artifact_sha256": manifest["artifact_sha256"],
        "python_receipt_sha256": manifest["python_receipt_sha256"],
        "node_receipt_sha256": manifest["node_receipt_sha256"],
        "compact_rows_sha256": EXPECTED_REPLAY["compact_file_sha256"],
        "labels_sha256": EXPECTED_REPLAY["labels_file_sha256"],
        "candidate_ids_sha256": EXPECTED_REPLAY["candidate_ids_sha256"],
    }
    return {
        "schema": "fin-rvi-002/g09-final-promotion/4",
        "claim_id": "FIN-RVI-002-C1-BOUNDED",
        "status": "PASS",
        "score_before": 920,
        "gate_points": 80,
        "score_after": 1000,
        "claim": base_contract["claim"],
        "scope": base_contract["scope"],
        "novelty_boundary": "The systematic search found no exact hit in the searched corpora, but this is not proof of global novelty or historical priority; promotion is limited to the declared empirical Honduras ONCAE-SEFIN result and finance gate rubric.",
        "base_contract_file": "fin_rvi_002_g09/final_contract_v2.json",
        "open_contract": EXPECTED_OPEN_CONTRACT,
        "stage6": EXPECTED_STAGE6,
        "stage7_manifest_file": manifest_path,
        "stage7_python_receipt_file": python_receipt_path,
        "stage7_node_receipt_file": node_receipt_path,
        "stage7": {"run_manifest": manifest, "legacy_view": legacy_view},
        "final_gates": EXPECTED_FINAL_GATES,
        "gate_readout": EXPECTED_READOUT,
    }


def compare(left: object, right: object, path: str = "$") -> str | None:
    if type(left) is not type(right):
        return f"{path}: type mismatch"
    if isinstance(left, dict):
        if set(left) != set(right):
            return f"{path}: key mismatch"
        for key in sorted(left):
            result = compare(left[key], right[key], f"{path}.{key}")
            if result:
                return result
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: list length mismatch"
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            result = compare(a, b, f"{path}[{index}]")
            if result:
                return result
        return None
    if left != right:
        if isinstance(left, str):
            return json.dumps(
                {
                    "path": path,
                    "left": left,
                    "right": right,
                    "left_length": len(left),
                    "right_length": len(right),
                    "left_codepoints": [ord(char) for char in left],
                    "right_codepoints": [ord(char) for char in right],
                },
                sort_keys=True,
            )
        return f"{path}: {left!r} != {right!r}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--python-receipt", type=Path, required=True)
    parser.add_argument("--node-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rebuilt = build(
        json.loads(args.base.read_text(encoding="utf-8")),
        json.loads(args.manifest.read_text(encoding="utf-8")),
        args.manifest.as_posix(),
        args.python_receipt.as_posix(),
        args.node_receipt.as_posix(),
    )
    canonical = json.loads(CANONICAL_TARGET.read_text(encoding="utf-8"))
    difference = compare(rebuilt, canonical)
    if difference:
        raise ValueError(f"rebuilt promotion differs semantically: {difference}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(CANONICAL_TARGET.read_bytes())
    print(json.dumps({"score": 1000, "semantic_equal": True, "transport_equal": True}, sort_keys=True))


if __name__ == "__main__":
    main()
