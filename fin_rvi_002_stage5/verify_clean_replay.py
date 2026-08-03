from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

SOURCE_HEAD = "9e6686204fce20bc21d17f041d506a2a9c92761d"
SOURCE_RUN_ID = 30841561243
SOURCE_ARTIFACT_ID = 8867231467
SOURCE_ARTIFACT_SHA256 = "a1a4a2e7dd3a722ce9b1dac9b5dbe02a5bfde0f7bd63c9e5fb6974c056de3928"
EXPECTED_COMPACT_FILE_SHA256 = "5793b9d1f88176b9ba3b61a006510766041572502a6ad0595e05fc2869f71571"
EXPECTED_LABEL_FILE_SHA256 = "949b6e8d0ad035130cb47d2e7c97a5f4176ea5d9bbcdb7dbc7b0444c22754a1f"
EXPECTED_IDS_SHA256 = "7352d9e05195fe597a4b8001192f39f7e540a0ee8799d0b0e940c73dff2354db"
EXPECTED_ROWS_LOGICAL_SHA256 = "c17ded7b3cebe91574156e2f62aae86ff2924abea2b2a11a16ea7a2db0c8299e"
EXPECTED_LABELS_LOGICAL_SHA256 = "617afa5eda7e530611d372bc519e371b9e5a2525f56259500051ec2cce465d18"
EXPECTED_PACKAGE_HASHES = {
    ("ONCAE", 2023): "db9a76958a069ff5fc47b6f68caf59a74174efcbebcca0458d0f4a08cf00683d",
    ("SEFIN", 2023): "9bae4bcef17c618137901f1f9b7a548ab734a7195cb92aaddeb34b2a49b1ced6",
    ("ONCAE", 2024): "43e12ce76ba1fcd3bf1240ffea4e246126bdcc2832d3d77bcb7415d8a1195c37",
    ("SEFIN", 2024): "f41f2f9b11ab8e6ccd185ab2c7e193a7107bd1b12f25d33a14946589d5dccd47",
    ("ONCAE", 2025): "aa33b9b591fabce5f2397b5966b67ba7fc6471bf8b394ceb5c2aeec707f6cb06",
    ("SEFIN", 2025): "3971d50d45b21ea97dbdaf05b70cd38f674765a9d70f2ed30e80d7b9a5d25db5",
}
EXPECTED_LABEL_COUNTS = {"SUPPORTED": 58, "REJECTED": 28, "UNRESOLVED": 34}
EXPECTED_METRICS = {
    "B1_CODE_SUPPLIER": {
        "labeled_rows": 86,
        "promotions": 78,
        "supported_recovered": 58,
        "unsafe_overpromotions": 20,
        "missed_supported": 0,
        "correct_rejections": 8,
    },
    "POLICY_DOCUMENTARY": {
        "labeled_rows": 86,
        "promotions": 58,
        "supported_recovered": 58,
        "unsafe_overpromotions": 0,
        "missed_supported": 0,
        "correct_rejections": 28,
    },
}
EXPECTED_PERMUTATION = {
    "seed": "FIN-RVI-002-STAGE3-PERMUTATION-V1",
    "labeled_rows": 86,
    "promotions": 58,
    "supported_recovered": 37,
    "unsafe_overpromotions": 21,
}


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def logical_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    labeled = [row for row in rows if row["label"] in {"SUPPORTED", "REJECTED"}]
    policies: dict[str, Callable[[dict[str, Any]], bool]] = {
        "B1_CODE_SUPPLIER": lambda row: bool(row["baseline_supplier_support"]),
        "POLICY_DOCUMENTARY": lambda row: row["policy_decision"] == "SUPPORTED",
    }
    output: dict[str, dict[str, int]] = {}
    for name, promotes in policies.items():
        promoted = [row for row in labeled if promotes(row)]
        output[name] = {
            "labeled_rows": len(labeled),
            "promotions": len(promoted),
            "supported_recovered": sum(
                row["label"] == "SUPPORTED" for row in promoted
            ),
            "unsafe_overpromotions": sum(
                row["label"] == "REJECTED" for row in promoted
            ),
            "missed_supported": sum(
                row["label"] == "SUPPORTED" and not promotes(row)
                for row in labeled
            ),
            "correct_rejections": sum(
                row["label"] == "REJECTED" and not promotes(row)
                for row in labeled
            ),
        }
    return output


def permutation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seed = "FIN-RVI-002-STAGE3-PERMUTATION-V1"
    labeled = sorted(
        (row for row in rows if row["label"] in {"SUPPORTED", "REJECTED"}),
        key=lambda row: hashlib.sha256(
            canonical(f"{row['candidate_id']}|{seed}").encode("utf-8")
        ).hexdigest(),
    )
    decisions = [row["policy_decision"] for row in labeled]
    if decisions:
        decisions = decisions[1:] + decisions[:1]
    promoted = [
        row
        for row, decision in zip(labeled, decisions, strict=True)
        if decision == "SUPPORTED"
    ]
    return {
        "seed": seed,
        "labeled_rows": len(labeled),
        "promotions": len(promoted),
        "supported_recovered": sum(
            row["label"] == "SUPPORTED" for row in promoted
        ),
        "unsafe_overpromotions": sum(
            row["label"] == "REJECTED" for row in promoted
        ),
    }


def verify(report_path: Path, rows_path: Path, labels_path: Path) -> dict[str, Any]:
    report_file_hash = file_sha(report_path)
    compact_file_hash = file_sha(rows_path)
    label_file_hash = file_sha(labels_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = sorted(read_jsonl(rows_path), key=lambda row: row["candidate_id"])
    labels = sorted(read_jsonl(labels_path), key=lambda row: row["candidate_id"])
    payload = report.get("payload", {})
    stage4 = payload.get("stage4", {})
    report_rows = sorted(
        stage4.get("compact_rows", []), key=lambda row: row["candidate_id"]
    )
    ids_hash = hashlib.sha256(
        "\n".join(row["candidate_id"] for row in rows).encode("utf-8")
    ).hexdigest()
    recalculated_metrics = metrics(rows)
    recalculated_permutation = permutation(rows)
    label_counts = dict(Counter(row["label"] for row in rows))
    downloads = {
        (record["source"], int(record["year"])): record["sha256"]
        for record in payload.get("downloads", [])
    }
    row_by_id = {row["candidate_id"]: row for row in rows}
    label_by_id = {row["candidate_id"]: row for row in labels}
    labels_match_rows = len(label_by_id) == len(labels) and all(
        candidate_id in row_by_id
        and label_by_id[candidate_id]["label"] == row_by_id[candidate_id]["label"]
        for candidate_id in label_by_id
    )
    excluded = set(stage4.get("source_stage3_manifest", {}).get("shared_codes", []))
    code_counts = Counter(row["shared_code"] for row in rows)
    gates = {
        "source_head_pinned": SOURCE_HEAD
        == "9e6686204fce20bc21d17f041d506a2a9c92761d",
        "report_internal_hash": logical_sha(payload) == report.get("sha256"),
        "schema": payload.get("schema")
        == "fin-rvi-002/stage4-independent-policy-v3/1",
        "official_packages_exact": downloads == EXPECTED_PACKAGE_HASHES,
        "candidate_universe": payload.get("candidate_reconstruction", {}).get(
            "candidate_count"
        )
        == 2295,
        "cohort_size": len(rows) == len(report_rows) == 120,
        "compact_file_exact": compact_file_hash == EXPECTED_COMPACT_FILE_SHA256,
        "labels_file_exact": label_file_hash == EXPECTED_LABEL_FILE_SHA256,
        "candidate_ids_exact": ids_hash == EXPECTED_IDS_SHA256,
        "compact_rows_logical_exact": logical_sha(rows)
        == EXPECTED_ROWS_LOGICAL_SHA256,
        "labels_logical_exact": logical_sha(labels)
        == EXPECTED_LABELS_LOGICAL_SHA256,
        "report_rows_match_file": canonical(rows) == canonical(report_rows),
        "labels_match_rows": labels_match_rows,
        "label_counts": label_counts == EXPECTED_LABEL_COUNTS,
        "policy_metrics": recalculated_metrics
        == EXPECTED_METRICS
        == stage4.get("policy_metrics"),
        "permutation": recalculated_permutation
        == EXPECTED_PERMUTATION
        == stage4.get("permutation_control"),
        "all_stage4_gates": all(stage4.get("gate_checks", {}).values()),
        "source_gate_candidate": stage4.get("gate_status")
        == "PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION",
        "policy_fixed": stage4.get("policy_id")
        == "FIN-RVI-002-DOCUMENTARY-V3",
        "stage3_codes_excluded": len(excluded) == 118
        and not any(row["shared_code"] in excluded for row in rows),
        "code_cardinality_cap": max(code_counts.values(), default=0) <= 2,
        "independence_contract": all(
            stage4.get("independence_contract", {}).get(key) is True
            for key in (
                "stage3_shared_codes_excluded",
                "policy_fixed_before_stage4_outcomes",
                "labeler_unchanged_from_stage3",
            )
        ),
        "zero_unsafe_and_full_recovery": (
            recalculated_metrics["POLICY_DOCUMENTARY"]["unsafe_overpromotions"]
            == 0
            and recalculated_metrics["POLICY_DOCUMENTARY"][
                "supported_recovered"
            ]
            == 58
            and recalculated_metrics["POLICY_DOCUMENTARY"]["missed_supported"]
            == 0
        ),
        "strict_baseline_improvement": (
            recalculated_metrics["B1_CODE_SUPPLIER"]["unsafe_overpromotions"]
            == 20
            and recalculated_metrics["POLICY_DOCUMENTARY"][
                "unsafe_overpromotions"
            ]
            == 0
        ),
        "g09_remains_open": payload.get("gate_readout", {}).get("G09")
        == "OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED",
    }
    valid = all(gates.values())
    receipt_payload = {
        "schema": "fin-rvi-002/stage5-clean-reconstruction/1",
        "source": {
            "head": SOURCE_HEAD,
            "run_id": SOURCE_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_sha256": SOURCE_ARTIFACT_SHA256,
        },
        "replay": {
            "report_file_sha256": report_file_hash,
            "report_payload_sha256": report.get("sha256"),
            "compact_file_sha256": compact_file_hash,
            "labels_file_sha256": label_file_hash,
            "candidate_ids_sha256": ids_hash,
            "rows_logical_sha256": logical_sha(rows),
            "labels_logical_sha256": logical_sha(labels),
        },
        "label_counts": label_counts,
        "policy_metrics": recalculated_metrics,
        "permutation_control": recalculated_permutation,
        "gates": gates,
        "gate_readout": {
            "G07": "PASS" if valid else "OPEN_CLEAN_RECONSTRUCTION_FAILED",
            "G09": "OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED",
            "finance_score": 920 if valid else 820,
        },
        "boundary": (
            "PASS is scoped to auditable CONTRACTOR_PAYMENT attribution on the "
            "declared Honduras ONCAE-SEFIN cohorts. It does not prove legality, "
            "receipt, quality, liquidation, fraud, corruption, or physical result."
        ),
    }
    return {"payload": receipt_payload, "sha256": logical_sha(receipt_payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("compact_rows", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(args.report, args.compact_rows, args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md = args.output.with_suffix(".md")
    payload = receipt["payload"]
    md.write_text(
        "\n".join(
            [
                "# FIN-RVI-002 Stage 5 — clean reconstruction",
                "",
                f"- Status: **{'PASS' if all(payload['gates'].values()) else 'FAIL'}**",
                f"- G07: `{payload['gate_readout']['G07']}`",
                f"- Finance score: **{payload['gate_readout']['finance_score']}/1000**",
                f"- G09: `{payload['gate_readout']['G09']}`",
                f"- Supported recovered: **{payload['policy_metrics']['POLICY_DOCUMENTARY']['supported_recovered']}**",
                f"- Unsafe promotions: **{payload['policy_metrics']['POLICY_DOCUMENTARY']['unsafe_overpromotions']}**",
                f"- Baseline unsafe promotions: **{payload['policy_metrics']['B1_CODE_SUPPLIER']['unsafe_overpromotions']}**",
                f"- Receipt SHA-256: `{receipt['sha256']}`",
                "",
                "## Boundary",
                "",
                payload["boundary"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "valid": all(payload["gates"].values()),
                "receipt_sha256": receipt["sha256"],
                "gate_readout": payload["gate_readout"],
            },
            sort_keys=True,
        )
    )
    return 0 if all(payload["gates"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
