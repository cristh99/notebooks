from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scaleup import canonical, fisher_two_sided, sha256, wilson


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify(output_dir: Path, protocol_path: Path, freeze_path: Path) -> dict:
    protocol = load_json(protocol_path)
    freeze = load_json(freeze_path)
    source = load_json(output_dir / "SOURCE_IDENTITY.json")
    result = load_json(output_dir / "SCALEUP_RESULT.json")
    manifest = load_json(output_dir / "SCALEUP_MANIFEST.json")
    cohort = load_jsonl(output_dir / "SCALEUP_COHORT.jsonl")
    quarantines = load_jsonl(output_dir / "QUARANTINE.jsonl")

    files = {
        name: output_dir / name
        for name in ("SOURCE_IDENTITY.json", "SCALEUP_COHORT.jsonl", "SCALEUP_RESULT.json", "QUARANTINE.jsonl")
    }
    group_rows = {group: [row for row in cohort if row["method_group"] == group] for group in ("DIRECT", "OPEN")}
    checks: dict[str, bool] = {
        "protocol_schema": protocol["schema"] == "data-science-pipeline/stage09-preregistered-scaleup-protocol/1",
        "protocol_frozen_before_discovery": protocol["status"] == "FROZEN_BEFORE_COHORT_DISCOVERY",
        "freeze_no_source_access": freeze["source_bytes_accessed_before_freeze"] is False,
        "freeze_no_count_access": freeze["cohort_counts_observed_before_freeze"] is False,
        "hypothesis_unchanged": protocol["analysis_contract"]["hypothesis_id"] == "H09-001",
        "test_unchanged": protocol["analysis_contract"]["test"] == "two_sided_fisher_exact",
        "minimum_cell_unchanged": protocol["analysis_contract"]["minimum_cell_n"] == 5,
        "fdr_unchanged": protocol["analysis_contract"]["fdr_method"] == "Benjamini-Hochberg" and protocol["analysis_contract"]["fdr_q"] == 0.05,
        "source_official": source["publisher"] == "ONCAE" and source["publication_id"] == 122,
        "source_hash_shape": len(source["sha256"]) == 64 and source["bytes"] > 0,
        "manifest_schema": manifest["schema"] == "data-science-pipeline/stage09-scaleup-manifest/1",
        "manifest_file_set": set(manifest["files"]) == set(files),
        "manifest_hashes": all(manifest["files"][name]["sha256"] == sha256(path.read_bytes()) for name, path in files.items()),
        "manifest_sizes": all(manifest["files"][name]["bytes"] == path.stat().st_size for name, path in files.items()),
        "source_identity_canonical": (output_dir / "SOURCE_IDENTITY.json").read_bytes() == canonical(source),
        "result_canonical": (output_dir / "SCALEUP_RESULT.json").read_bytes() == canonical(result),
        "manifest_canonical": (output_dir / "SCALEUP_MANIFEST.json").read_bytes() == canonical(manifest),
        "cohort_count": len(cohort) == manifest["selected_rows"],
        "group_counts": all(len(group_rows[group]) == result["selected_group_counts"][group] == manifest["selected_group_counts"][group] for group in group_rows),
        "minimum_cells_met": all(len(group_rows[group]) >= protocol["analysis_contract"]["minimum_cell_n"] for group in group_rows),
        "target_respected": all(len(group_rows[group]) <= protocol["cohort"]["target_per_group"] for group in group_rows),
        "unique_event_ids": len({row["event_id"] for row in cohort}) == len(cohort),
        "one_per_ocid": len({row["ocid_commitment_sha256"] for row in cohort}) == len(cohort),
        "roles_exact": all((row["event_role"], row["amount_role"], row["date_role"]) == ("CONTRACT", "CONTRACT_VALUE", "CONTRACT_DATE") for row in cohort),
        "groups_exact": {row["method_group"] for row in cohort} == {"DIRECT", "OPEN"},
        "methods_exact": all(row["procurement_method"] == row["method_group"].lower() for row in cohort),
        "bid_count_explicit": all(isinstance(row["bid_count"], int) and row["bid_count"] >= 0 for row in cohort),
        "low_competition_exact": all(row["low_competition"] is (row["bid_count"] <= 1) for row in cohort),
        "currency_hnl": all(row["currency"] == "HNL" and row["amount_hnl_cents"] > 0 for row in cohort),
        "lineage_source_bound": all(row["lineage"]["archive_sha256"] == source["sha256"] and row["lineage"]["compressed_byte_count"] == source["bytes"] for row in cohort),
        "record_hashes": all(row["record_sha256"] == sha256(canonical({key: value for key, value in row.items() if key != "record_sha256"})) for row in cohort),
        "no_raw_identity_fields": all(not ({"buyer_id", "buyer_name", "supplier_id", "supplier_name", "ocid", "contract_id"} & set(row)) for row in cohort),
        "quarantine_count": len(quarantines) == result["quarantine_count"],
        "terminal_validated": result["terminal"] == "ANALYSIS_EXECUTION_VALIDATED",
        "terminal_reason": result["reason"] == "BOUNDED_PREREGISTERED_CANARY_SUFFICIENT",
        "hypothesis_executed": result["hypothesis_test_executed"] is True and result["inferential_outputs_emitted"] is True,
        "production_unmodified": result["governance"]["production_modified"] is False,
        "zero_cost": result["governance"]["external_cost_usd"] == 0.0,
        "stage10_blocked": result["governance"]["stage10_unblocked"] is False,
        "zero_scientific_credit": result["governance"]["scientific_promotion_credit"] == 0,
        "association_only_boundary": "association-only" in result["claim_boundary"] and "no causality" in result["claim_boundary"],
    }

    contingency = result["contingency"]
    for group in ("DIRECT", "OPEN"):
        successes = sum(row["low_competition"] for row in group_rows[group])
        total = len(group_rows[group])
        expected = contingency[group]
        checks[f"{group.lower()}_contingency"] = (
            expected["low_competition"] == successes
            and expected["not_low_competition"] == total - successes
            and expected["n"] == total
            and abs(expected["rate"] - successes / total) < 1e-15
        )
        expected_wilson = wilson(successes, total)
        checks[f"{group.lower()}_wilson"] = all(abs(a - b) < 1e-14 for a, b in zip(expected["wilson_95"], expected_wilson))

    direct = contingency["DIRECT"]
    opened = contingency["OPEN"]
    p_value = fisher_two_sided(
        direct["low_competition"], direct["not_low_competition"],
        opened["low_competition"], opened["not_low_competition"],
    )
    checks.update({
        "fisher_exact": abs(result["fisher_two_sided_p"] - p_value) < 1e-15,
        "single_hypothesis_bh": abs(result["bh_adjusted_p"] - result["fisher_two_sided_p"]) < 1e-15,
        "risk_difference": abs(result["risk_difference_direct_minus_open"] - (direct["rate"] - opened["rate"])) < 1e-15,
        "fdr_decision": result["fdr_reject"] is (result["bh_adjusted_p"] <= result["fdr_q"]),
        "negative_control_not_promoted": result["negative_control"]["promoted"] is False,
    })

    if not all(checks.values()):
        raise RuntimeError({key: value for key, value in checks.items() if not value})
    receipt = {
        "schema": "data-science-pipeline/stage09-scaleup-local-receipt/1",
        "verdict": "PASS_STAGE09_PREREGISTERED_SCALEUP_LOCAL",
        "checks": checks,
        "tests_expected": 0,
        "source_sha256": source["sha256"],
        "cohort_sha256": sha256((output_dir / "SCALEUP_COHORT.jsonl").read_bytes()),
        "result_sha256": sha256((output_dir / "SCALEUP_RESULT.json").read_bytes()),
        "manifest_sha256": sha256((output_dir / "SCALEUP_MANIFEST.json").read_bytes()),
        "selected_group_counts": result["selected_group_counts"],
        "terminal": result["terminal"],
        "stage10_unblocked": False,
        "external_cost_usd": 0.0,
        "production_modified": False,
        "scientific_promotion_credit": 0,
    }
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(args.output_dir, args.protocol, args.freeze)
    args.receipt.write_bytes(canonical(receipt))
    print(receipt["verdict"])


if __name__ == "__main__":
    main()
