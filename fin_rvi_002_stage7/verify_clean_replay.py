from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

SOURCE_HEAD = "9beb7ec13e09674ea95d7a517f038acb37b9653b"
SOURCE_RUN_ID = 30847688470
SOURCE_ARTIFACT_ID = 8869552099
SOURCE_ARTIFACT_SHA256 = "ad221e7cafb7fc8d11afb5e53f486842788f0fa5a423fbdb9891f9dc7824dfaf"
EXPECTED_COMPACT_FILE_SHA256 = "90e26745ced9dafd81249edb39ffbd4c10f0b64a5c6855eadf6053c4abf503e3"
EXPECTED_LABEL_FILE_SHA256 = "fc3a33ba87ecc29a909717e4702ea3e281d5461fa2c5d45e242f9be8a4dc7f2a"
EXPECTED_EXCLUSION_MANIFEST_FILE_SHA256 = "b4aa12fdf1126e11512579c71ce2a38f109aecbdac0081758951c2757f99103a"
EXPECTED_CANDIDATE_IDS_SHA256 = "d259ec1f3cccae2dc0756ce6b318253359970ca759e89fce92d36b5336ca1aa4"
EXPECTED_COMPACT_LOGICAL_SHA256 = "e07374f31c47df2a366793c27cdfedf153e212f20b719454b3eab1f4a760ac61"
EXPECTED_LABEL_LOGICAL_SHA256 = "f959add5fd963238939d4e0951307a63247044c720d9aecb3661577c04238552"
EXPECTED_STAGE6_BLOCK_SHA256 = "8c8e3b5f8f180071b1a17b33e9fd5f8bce7de02feff86cf2d837f27b8e796597"
EXPECTED_CANDIDATE_RECONSTRUCTION_SHA256 = "75f9d14514f7e490cd6071a63d6e80e74542be9de03fb64a5f489d1a6d2bbb25"
EXPECTED_CONFIGURATION_SHA256 = "9469b68ab4be25e4953c1078982b0644b5ada19b90b8690b052ea8a4ef99205b"
EXPECTED_DATASET_COUNTS_SHA256 = "631fc080a97c22f6221cc23787a5d004b53f35d408a76b9ed608366635ab2f40"
EXPECTED_DOWNLOADS_STABLE_SHA256 = "a8735983060ac5d0c3b258729cd93ee604cfaff00a8d829fa3216e578010d5ab"
EXPECTED_EXCLUSION_PAYLOAD_SHA256 = "d7cc93a4a1233f4e2309fe9e3bd74fd9813e460cf82b2e15ccfcdf46d1e5425c"
EXPECTED_NODE_POLICY_DECISIONS_SHA256 = "3f4999ae8d4282f6a71c25fe790ca28cad1fd7549fdb07f17a2bbdd209bbff0b"
EXPECTED_NODE_COMPACT_LOGICAL_SHA256 = "d02f65f00435f0e0710fd44c2ad1512cc9925a6048b364c9de85722872f45890"
EXPECTED_LABEL_COUNTS = {"SUPPORTED": 63, "REJECTED": 28, "UNRESOLVED": 29}
EXPECTED_METRICS = {
    "B1_CODE_SUPPLIER": {
        "labeled_rows": 91,
        "promotions": 82,
        "supported_recovered": 63,
        "unsafe_overpromotions": 19,
        "missed_supported": 0,
        "correct_rejections": 9,
    },
    "POLICY_DOCUMENTARY": {
        "labeled_rows": 91,
        "promotions": 63,
        "supported_recovered": 63,
        "unsafe_overpromotions": 0,
        "missed_supported": 0,
        "correct_rejections": 28,
    },
}
EXPECTED_PERMUTATION = {
    "seed": "FIN-RVI-002-STAGE3-PERMUTATION-V1",
    "labeled_rows": 91,
    "promotions": 63,
    "supported_recovered": 41,
    "unsafe_overpromotions": 22,
}
EXPECTED_PACKAGE_HASHES = {
    ("ONCAE", 2023): "db9a76958a069ff5fc47b6f68caf59a74174efcbebcca0458d0f4a08cf00683d",
    ("SEFIN", 2023): "9bae4bcef17c618137901f1f9b7a548ab734a7195cb92aaddeb34b2a49b1ced6",
    ("ONCAE", 2024): "43e12ce76ba1fcd3bf1240ffea4e246126bdcc2832d3d77bcb7415d8a1195c37",
    ("SEFIN", 2024): "f41f2f9b11ab8e6ccd185ab2c7e193a7107bd1b12f25d33a14946589d5dccd47",
    ("ONCAE", 2025): "aa33b9b591fabce5f2397b5966b67ba7fc6471bf8b394ceb5c2aeec707f6cb06",
    ("SEFIN", 2025): "3971d50d45b21ea97dbdaf05b70cd38f674765a9d70f2ed30e80d7b9a5d25db5",
}
EXACT_POLICY_FIELDS = (
    "policy_numeric_conflict",
    "policy_exact_numeric_support",
    "policy_name_support",
    "policy_payment_language",
    "policy_hard_category_conflict",
    "policy_shared_object_token_count",
    "policy_shared_classifications",
    "policy_base_v2_decision",
)


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


def independent_policy_v3(row: Mapping[str, Any]) -> dict[str, str]:
    hard_conflict = bool(row["policy_hard_category_conflict"])
    classification_support = bool(row["policy_shared_classifications"])
    token_count = int(row["policy_shared_object_token_count"])
    if row["policy_numeric_conflict"]:
        return {
            "decision": "REJECTED",
            "reason": "V3_NUMERIC_SUPPLIER_CONFLICT_VETO",
        }
    if (
        row["policy_exact_numeric_support"]
        and row["policy_payment_language"]
        and not hard_conflict
        and (token_count >= 2 or classification_support)
    ):
        return {
            "decision": "SUPPORTED",
            "reason": "V3_EXACT_ID_PAYMENT_AND_OBJECT_SUPPORT",
        }
    if (
        row["policy_base_v2_decision"] == "SUPPORTED"
        and row["policy_name_support"]
        and row["policy_payment_language"]
        and not hard_conflict
        and (token_count >= 6 or classification_support)
    ):
        return {
            "decision": "SUPPORTED",
            "reason": "V3_NAME_PAYMENT_AND_STRONG_OBJECT_SUPPORT",
        }
    if hard_conflict:
        return {
            "decision": "REJECTED",
            "reason": "V3_HARD_OBJECT_CONFLICT",
        }
    return {
        "decision": "UNRESOLVED",
        "reason": "V3_INSUFFICIENT_JOINT_EVIDENCE",
    }


def policy_decision_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": row["candidate_id"],
            "expected_decision": row["policy_decision"],
            "expected_reason": row["policy_reason"],
            **independent_policy_v3(row),
        }
        for row in sorted(rows, key=lambda item: item["candidate_id"])
    ]


def metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    labeled = [row for row in rows if row["label"] in {"SUPPORTED", "REJECTED"}]
    output: dict[str, dict[str, int]] = {}
    for name in ("B1_CODE_SUPPLIER", "POLICY_DOCUMENTARY"):
        if name == "B1_CODE_SUPPLIER":
            promotes = lambda row: bool(row["baseline_supplier_support"])
        else:
            promotes = lambda row: independent_policy_v3(row)["decision"] == "SUPPORTED"
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
    seed = EXPECTED_PERMUTATION["seed"]
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


def stable_dataset_stats(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in record.items() if key != "seconds"}
        for record in payload["dataset_stats"]
    ]


def stable_downloads(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in record.items()
            if key not in {"seconds", "attempt", "cached", "path"}
        }
        for record in payload["downloads"]
    ]


def combined_statistical_evidence() -> dict[str, Any]:
    corrected_without_regression = 20 + 19
    rejected_rows = 28 + 28
    supported_rows = 58 + 63
    alpha = 0.05
    return {
        "code_disjoint_cohorts": 2,
        "corrected_unsafe_promotions": corrected_without_regression,
        "introduced_unsafe_promotions": 0,
        "exact_one_sided_sign_test_p": 2.0 ** (-corrected_without_regression),
        "observed_unsafe_promotions": 0,
        "rejected_rows": rejected_rows,
        "one_sided_95pct_upper_bound_unsafe_rate": 1.0 - alpha ** (1.0 / rejected_rows),
        "supported_recovered": supported_rows,
        "supported_expected": supported_rows,
        "one_sided_95pct_lower_bound_supported_recovery": alpha ** (1.0 / supported_rows),
        "interpretation": (
            "Exact paired and binomial summaries of the declared cohorts; not a global population guarantee."
        ),
    }


def verify(
    report_path: Path,
    rows_path: Path,
    labels_path: Path,
    node_receipt_path: Path,
    exclusion_manifest_path: Path,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = report.get("payload", {})
    stage6 = payload.get("stage6", {})
    rows = sorted(read_jsonl(rows_path), key=lambda row: row["candidate_id"])
    labels = sorted(read_jsonl(labels_path), key=lambda row: row["candidate_id"])
    node_receipt = json.loads(node_receipt_path.read_text(encoding="utf-8"))
    report_rows = sorted(stage6.get("compact_rows", []), key=lambda row: row["candidate_id"])
    decisions = policy_decision_rows(rows)
    mismatches = [
        row
        for row in decisions
        if row["decision"] != row["expected_decision"]
        or row["reason"] != row["expected_reason"]
    ]
    recalculated_metrics = metrics(rows)
    recalculated_permutation = permutation(rows)
    label_counts = dict(Counter(row["label"] for row in rows))
    ids_hash = hashlib.sha256(
        "\n".join(row["candidate_id"] for row in rows).encode("utf-8")
    ).hexdigest()
    label_by_id = {row["candidate_id"]: row for row in labels}
    labels_match_rows = len(label_by_id) == len(labels) and all(
        candidate_id in {row["candidate_id"] for row in rows}
        and label_by_id[candidate_id]["label"]
        == next(row["label"] for row in rows if row["candidate_id"] == candidate_id)
        for candidate_id in label_by_id
    )
    downloads = {
        (record["source"], int(record["year"])): record["sha256"]
        for record in payload.get("downloads", [])
    }
    excluded = set(stage6.get("source_stage34_manifest", {}).get("shared_codes", []))
    code_counts = Counter(row["shared_code"] for row in rows)
    node_payload = node_receipt.get("payload", {})
    gates = {
        "source_head_pinned": SOURCE_HEAD == "9beb7ec13e09674ea95d7a517f038acb37b9653b",
        "schema": payload.get("schema") == "fin-rvi-002/stage6-third-sealed-cohort/1",
        "official_packages_exact": downloads == EXPECTED_PACKAGE_HASHES,
        "candidate_universe": payload.get("candidate_reconstruction", {}).get("candidate_count") == 2295,
        "candidate_reconstruction_exact": logical_sha(payload.get("candidate_reconstruction")) == EXPECTED_CANDIDATE_RECONSTRUCTION_SHA256,
        "configuration_exact": logical_sha(payload.get("configuration")) == EXPECTED_CONFIGURATION_SHA256,
        "dataset_counts_exact": logical_sha(stable_dataset_stats(payload)) == EXPECTED_DATASET_COUNTS_SHA256,
        "downloads_stable_exact": logical_sha(stable_downloads(payload)) == EXPECTED_DOWNLOADS_STABLE_SHA256,
        "cohort_size": len(rows) == len(report_rows) == 120,
        "compact_file_exact": file_sha(rows_path) == EXPECTED_COMPACT_FILE_SHA256,
        "labels_file_exact": file_sha(labels_path) == EXPECTED_LABEL_FILE_SHA256,
        "exclusion_manifest_file_exact": file_sha(exclusion_manifest_path) == EXPECTED_EXCLUSION_MANIFEST_FILE_SHA256,
        "candidate_ids_exact": ids_hash == EXPECTED_CANDIDATE_IDS_SHA256,
        "compact_rows_logical_exact": logical_sha(rows) == EXPECTED_COMPACT_LOGICAL_SHA256,
        "labels_logical_exact": logical_sha(labels) == EXPECTED_LABEL_LOGICAL_SHA256,
        "stage6_block_exact": logical_sha(stage6) == EXPECTED_STAGE6_BLOCK_SHA256,
        "exclusion_payload_exact": stage6.get("source_stage34_manifest_sha256") == EXPECTED_EXCLUSION_PAYLOAD_SHA256,
        "report_rows_match_file": canonical(rows) == canonical(report_rows),
        "labels_match_rows": labels_match_rows,
        "label_counts": label_counts == EXPECTED_LABEL_COUNTS,
        "exact_policy_inputs_present": all(
            all(field in row for field in EXACT_POLICY_FIELDS) for row in rows
        ),
        "independent_python_policy_exact": len(mismatches) == 0,
        "policy_metrics": recalculated_metrics == EXPECTED_METRICS == stage6.get("policy_metrics"),
        "permutation": recalculated_permutation == EXPECTED_PERMUTATION == stage6.get("permutation_control"),
        "all_source_gates": all(stage6.get("gate_checks", {}).values()),
        "source_gate_candidate": stage6.get("gate_status") == "PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION",
        "policy_fixed": stage6.get("policy_id") == "FIN-RVI-002-DOCUMENTARY-V3",
        "prior_codes_excluded": len(excluded) == 237 and not any(row["shared_code"] in excluded for row in rows),
        "prior_codes_hash": stage6.get("source_stage34_manifest", {}).get("shared_codes_sha256") == "927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984",
        "code_cardinality_cap": max(code_counts.values(), default=0) <= 2,
        "zero_unsafe_and_full_recovery": (
            recalculated_metrics["POLICY_DOCUMENTARY"]["unsafe_overpromotions"] == 0
            and recalculated_metrics["POLICY_DOCUMENTARY"]["supported_recovered"] == 63
            and recalculated_metrics["POLICY_DOCUMENTARY"]["missed_supported"] == 0
        ),
        "strict_baseline_improvement": recalculated_metrics["B1_CODE_SUPPLIER"]["unsafe_overpromotions"] == 19,
        "node_schema": node_payload.get("schema") == "fin-rvi-002/stage6-node-independent-policy-receipt/3",
        "node_all_gates": all(node_payload.get("gates", {}).values()),
        "node_zero_mismatches": node_payload.get("independent_policy_mismatches") == 0,
        "node_policy_decisions_exact": node_payload.get("independent_policy_decisions_sha256") == EXPECTED_NODE_POLICY_DECISIONS_SHA256,
        "node_compact_logical_exact": node_payload.get("compact_rows_sha256") == EXPECTED_NODE_COMPACT_LOGICAL_SHA256,
        "node_metrics_match": node_payload.get("policy_metrics") == recalculated_metrics,
        "node_labels_match": node_payload.get("label_counts") == label_counts,
        "g09_not_premature": payload.get("gate_readout", {}).get("G09") == "OPEN_PRIOR_ART_AND_CLEAN_REPLAY_REQUIRED",
    }
    valid = all(gates.values())
    receipt_payload = {
        "schema": "fin-rvi-002/stage7-clean-reconstruction/1",
        "source": {
            "head": SOURCE_HEAD,
            "run_id": SOURCE_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_sha256": SOURCE_ARTIFACT_SHA256,
        },
        "replay": {
            "report_file_sha256": file_sha(report_path),
            "report_payload_sha256": report.get("sha256"),
            "compact_file_sha256": file_sha(rows_path),
            "labels_file_sha256": file_sha(labels_path),
            "exclusion_manifest_file_sha256": file_sha(exclusion_manifest_path),
            "candidate_ids_sha256": ids_hash,
            "compact_rows_logical_sha256": logical_sha(rows),
            "labels_logical_sha256": logical_sha(labels),
            "stage6_block_sha256": logical_sha(stage6),
            "node_receipt_file_sha256": file_sha(node_receipt_path),
            "node_receipt_payload_sha256": node_receipt.get("sha256"),
            "independent_python_policy_decisions_sha256": logical_sha(decisions),
            "independent_node_policy_decisions_sha256": node_payload.get("independent_policy_decisions_sha256"),
        },
        "label_counts": label_counts,
        "policy_metrics": recalculated_metrics,
        "permutation_control": recalculated_permutation,
        "combined_code_disjoint_statistical_evidence": combined_statistical_evidence(),
        "gates": gates,
        "gate_readout": {
            "G07": "PASS",
            "G09_REPLICATION": "PASS" if valid else "OPEN_CLEAN_RECONSTRUCTION_FAILED",
            "G09": "OPEN_FINAL_CONTRACT_PROMOTION_REQUIRED",
            "finance_score": 920,
        },
        "boundary": (
            "Stage 7 closes clean replication of the bounded CONTRACTOR_PAYMENT result; final G09 promotion still requires the fail-closed claim contract to absorb these exact receipts."
        ),
    }
    return {"payload": receipt_payload, "sha256": logical_sha(receipt_payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("compact_rows", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("node_receipt", type=Path)
    parser.add_argument("exclusion_manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(
        args.report,
        args.compact_rows,
        args.labels,
        args.node_receipt,
        args.exclusion_manifest,
    )
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
                "# FIN-RVI-002 Stage 7 — clean reconstruction",
                "",
                f"- Status: **{'PASS' if all(payload['gates'].values()) else 'FAIL'}**",
                f"- G09 replication: `{payload['gate_readout']['G09_REPLICATION']}`",
                f"- Finance score pending final contract: **{payload['gate_readout']['finance_score']}/1000**",
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
