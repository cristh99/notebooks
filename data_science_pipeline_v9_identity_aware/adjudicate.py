from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from facts_contract import canonical_json_bytes, fact_key, fact_set, sha256_file, split_fact_key


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _expected_sha(path: Path) -> str:
    fields = path.read_text(encoding="utf-8").strip().split()
    if len(fields) < 1 or len(fields[0]) != 64:
        raise RuntimeError(f"invalid SHA receipt: {path}")
    return fields[0].casefold()


def _fact_row(key: str) -> dict[str, str]:
    fact_type, value = split_fact_key(key)
    return {"fact_type": fact_type, "value": value}


def adjudicate(
    freeze_path: Path,
    landing_receipt_path: Path,
    binding_path: Path,
    pdf_receipt_path: Path,
    candidate_path: Path,
    candidate_sha_path: Path,
    oracle_path: Path,
    output: Path,
) -> dict[str, Any]:
    freeze = _load(freeze_path)
    landing = _load(landing_receipt_path)
    binding = _load(binding_path)
    pdf = _load(pdf_receipt_path)
    candidate = _load(candidate_path)
    oracle = _load(oracle_path)

    allowed_hosts = {host.casefold().rstrip(".") for host in freeze["source_discovery"]["allowed_hosts"]}
    candidate_expected_sha = _expected_sha(candidate_sha_path)
    candidate_actual_sha = sha256_file(candidate_path)
    landing_url = freeze["source_discovery"]["official_landing_page"]
    required_id = freeze["adjudication_gate"]["required_circular_id"]
    required_key = fact_key("circular_id", required_id)

    source_checks = {
        "landing_receipt_pass": landing.get("verdict") == "PASS",
        "landing_requested_url_frozen": landing.get("requested_url") == landing_url,
        "landing_final_host_allowlisted": str(landing.get("final_host", "")).casefold().rstrip(".") in allowed_hosts,
        "binding_pass": binding.get("verdict") == "PASS" and all(bool(value) for value in binding.get("checks", {}).values()),
        "binding_uses_landing_bytes": binding.get("landing_sha256") == landing.get("sha256"),
        "binding_title_frozen": binding.get("visible_title") == freeze["source_discovery"]["visible_title"],
        "binding_date_frozen": binding.get("visible_publication_date") == freeze["source_discovery"]["visible_publication_date"],
        "pdf_receipt_pass": pdf.get("verdict") == "PASS",
        "pdf_requested_from_binding": pdf.get("requested_url") == binding.get("pdf_url"),
        "pdf_final_host_allowlisted": str(pdf.get("final_host", "")).casefold().rstrip(".") in allowed_hosts,
        "pdf_magic": pdf.get("magic") == "%PDF-",
        "metadata_not_injected": binding.get("metadata_injected_as_document_facts") is False,
    }
    candidate_checks = {
        "candidate_receipt_sha_matches": candidate_actual_sha == candidate_expected_sha,
        "candidate_sealed": candidate.get("verdict") == "CANDIDATE_SEALED",
        "native_text_not_used": candidate.get("native_text_used") is False,
        "minimum_support_two": candidate.get("minimum_support") == freeze["candidate_gate"]["minimum_support"] == 2,
        "candidate_pdf_bound": candidate.get("source_pdf_sha256") == pdf.get("sha256"),
        "candidate_internal_checks": all(bool(value) for value in candidate.get("checks", {}).values()),
    }
    oracle_checks = {
        "oracle_pdf_bound": oracle.get("source_pdf_sha256") == pdf.get("sha256"),
        "oracle_schema": oracle.get("schema") == "data-science-pipeline/native-text-oracle/1",
    }

    candidate_facts = fact_set(candidate)
    oracle_facts = fact_set(oracle)
    intersection = candidate_facts & oracle_facts
    extras = candidate_facts - oracle_facts
    missing = oracle_facts - candidate_facts
    precision = len(intersection) / len(candidate_facts) if candidate_facts else 0.0
    recall = len(intersection) / len(oracle_facts) if oracle_facts else 0.0
    oracle_types = {split_fact_key(key)[0] for key in oracle_facts}

    thresholds = {
        "required_precision": float(freeze["adjudication_gate"]["required_precision"]),
        "minimum_recall": float(freeze["adjudication_gate"]["minimum_recall"]),
        "minimum_oracle_facts": int(freeze["oracle_gate"]["minimum_facts"]),
        "minimum_oracle_fact_types": int(freeze["oracle_gate"]["minimum_fact_types"]),
    }

    if not all(source_checks.values()):
        verdict = "FAIL_SOURCE_BINDING"
    elif not all(candidate_checks.values()) or not all(oracle_checks.values()):
        verdict = "FAIL_CANDIDATE_INTEGRITY"
    elif oracle.get("verdict") == "BLOCKED_NO_NATIVE_ORACLE":
        verdict = "BLOCKED_NO_NATIVE_ORACLE"
    elif oracle.get("verdict") != "ORACLE_SEALED":
        verdict = "FAIL_ORACLE_INTEGRITY"
    elif (
        len(oracle_facts) < thresholds["minimum_oracle_facts"]
        or len(oracle_types) < thresholds["minimum_oracle_fact_types"]
        or required_key not in oracle_facts
    ):
        verdict = "BLOCKED_INSUFFICIENT_ORACLE"
    elif extras:
        verdict = "FAIL_HALLUCINATION"
    elif (
        required_key not in candidate_facts
        or precision < thresholds["required_precision"]
        or recall < thresholds["minimum_recall"]
    ):
        verdict = "FAIL_EXTERNAL_RESOLUTION"
    else:
        verdict = "PASS_EXTERNAL_RESOLUTION"

    result = {
        "schema": "data-science-pipeline/identity-aware-external-adjudication/1",
        "verdict": verdict,
        "source": {
            "landing_url": landing_url,
            "landing_sha256": landing.get("sha256"),
            "pdf_url": binding.get("pdf_url"),
            "pdf_final_url": pdf.get("final_url"),
            "pdf_bytes": pdf.get("bytes"),
            "pdf_sha256": pdf.get("sha256"),
        },
        "checks": {
            "source": source_checks,
            "candidate": candidate_checks,
            "oracle": oracle_checks,
        },
        "metrics": {
            "candidate_facts": len(candidate_facts),
            "oracle_facts": len(oracle_facts),
            "oracle_fact_types": len(oracle_types),
            "true_positive_facts": len(intersection),
            "precision": precision,
            "recall": recall,
            "thresholds": thresholds,
            "required_circular_id": required_id,
            "required_id_in_candidate": required_key in candidate_facts,
            "required_id_in_oracle": required_key in oracle_facts,
        },
        "matched_facts": [_fact_row(key) for key in sorted(intersection)],
        "extra_candidate_facts": [_fact_row(key) for key in sorted(extras)],
        "missing_candidate_facts": [_fact_row(key) for key in sorted(missing)],
        "integrity": {
            "freeze_sha256": sha256_file(freeze_path),
            "landing_receipt_sha256": sha256_file(landing_receipt_path),
            "binding_sha256": sha256_file(binding_path),
            "pdf_receipt_sha256": sha256_file(pdf_receipt_path),
            "candidate_sha256": candidate_actual_sha,
            "oracle_sha256": sha256_file(oracle_path),
        },
        "controls": {
            "candidate_sealed_before_native_oracle": True,
            "metadata_body_token_equality_required": False,
            "post_result_retuning_permitted": False,
            "same_document_reuse_for_promotion_permitted": False,
            "merge_authorized": False,
            "mass_processing_authorized": False,
            "production_modified": False,
            "external_cost_usd": 0.0,
            "gcloud_used": False,
            "paid_compute_used": False,
            "scientific_credit": 1 if verdict == "PASS_EXTERNAL_RESOLUTION" else 0,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(result)
    output.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--landing-receipt", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--pdf-receipt", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = adjudicate(
        args.freeze,
        args.landing_receipt,
        args.binding,
        args.pdf_receipt,
        args.candidate,
        args.candidate_sha,
        args.oracle,
        args.output,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
