from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from . import verify_final_contract_v3 as legacy

SCHEMA = "fin-rvi-002/g09-final-promotion/4"
CLAIM_ID = "FIN-RVI-002-C1-BOUNDED"
BASE_CONTRACT_SHA256 = "5e1bde35b3cddb0e77a0eb8cb72482d1582e3578854fa4ec959e19f1b444526f"
EXPECTED_SCOPE_EXCLUSIONS = {
    "legality",
    "fraud",
    "corruption",
    "physical receipt",
    "quality",
    "liquidation",
    "causal impact",
    "global universality",
    "novelty of entity resolution",
    "novelty of procurement knowledge graphs",
    "novelty of active evidence acquisition",
}
EXPECTED_FINAL_GATES = {
    "g07_operational_utility": "PASS",
    "stage4_independent_code_disjoint_cohort": "PASS",
    "stage5_clean_reconstruction": "PASS",
    "systematic_primary_prior_art_closure": "PASS",
    "claim_scope_audit": "PASS",
    "stage6_third_code_disjoint_cohort": "PASS",
    "stage6_independent_policy_implementation": "PASS",
    "stage7_third_cohort_clean_reconstruction": "PASS",
}
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
EXPECTED_REPLAY = {
    "compact_file_sha256": "90e26745ced9dafd81249edb39ffbd4c10f0b64a5c6855eadf6053c4abf503e3",
    "labels_file_sha256": "fc3a33ba87ecc29a909717e4702ea3e281d5461fa2c5d45e242f9be8a4dc7f2a",
    "exclusion_manifest_file_sha256": "b4aa12fdf1126e11512579c71ce2a38f109aecbdac0081758951c2757f99103a",
    "candidate_ids_sha256": "d259ec1f3cccae2dc0756ce6b318253359970ca759e89fce92d36b5336ca1aa4",
    "independent_policy_decisions_sha256": "3f4999ae8d4282f6a71c25fe790ca28cad1fd7549fdb07f17a2bbdd209bbff0b",
}
EXPECTED_STAGE6 = {
    "status": "PASS",
    "head_sha": "9beb7ec13e09674ea95d7a517f038acb37b9653b",
    "run_id": 30847688470,
    "artifact_id": 8869552099,
    "artifact_sha256": "ad221e7cafb7fc8d11afb5e53f486842788f0fa5a423fbdb9891f9dc7824dfaf",
    "cohort_rows": 120,
    "prior_shared_codes_excluded": 237,
    "prior_shared_codes_sha256": "927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984",
    "labels": EXPECTED_LABEL_COUNTS,
    "baseline": {"unsafe_overpromotions": 19, "supported_recovered": 63},
    "challenger": {
        "unsafe_overpromotions": 0,
        "supported_recovered": 63,
        "missed_supported": 0,
    },
    "permutation": {"unsafe_overpromotions": 22, "supported_recovered": 41},
    "independent_policy_mismatches": 0,
    "report_payload_sha256": "92c5e556cd0688dfdf5fa9a993c47506267ad171a9033da85702a57a9763a40b",
    "compact_rows_sha256": EXPECTED_REPLAY["compact_file_sha256"],
    "labels_sha256": EXPECTED_REPLAY["labels_file_sha256"],
    "candidate_ids_sha256": EXPECTED_REPLAY["candidate_ids_sha256"],
    "node_receipt_sha256": "81d8cd3bb35c7b5f30d50f823cdbc28b72bc05728d7717c10acf9de72881b6b4",
    "independent_policy_decisions_sha256": EXPECTED_REPLAY[
        "independent_policy_decisions_sha256"
    ],
}
EXPECTED_OPEN_CONTRACT = {
    "head_sha": "27c35d6833d8ff3cdc73f8a308eae4fe50422eec",
    "run_id": 30847916495,
    "artifact_id": 8869425757,
    "artifact_sha256": "4467ebf198d15e199afc64180bf456d2ee0166b3520b01c9f4f9dccb1d60417b",
    "contract_sha256": BASE_CONTRACT_SHA256,
    "python_receipt_sha256": "ea9edeb832608cf9f30806c00abba9c09cdfe77a3c88aa463afd8456bd0b9919",
    "node_receipt_sha256": "780d25a90e0e41b333ae49c9b32ce5396c36f4c2d1f54db0a6abe5e882ce87bf",
    "scope_audit_receipt_sha256": "e1fd5faae0ec3e7aa5a52de151f188101d84f43692e515709b1f6cb2f36e9add",
}
EXPECTED_READOUT = {"G07": "PASS", "G09": "PASS", "finance_score": 1000}


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _load(root: Path, relative: str) -> dict[str, Any]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _verify_stage7_receipt(
    receipt: Mapping[str, Any], expected_schema: str, node: bool
) -> list[str]:
    errors: list[str] = []
    payload = _mapping(receipt.get("payload"))
    if payload is None:
        return ["stage7-receipt-payload"]
    if receipt.get("sha256") != digest(payload):
        errors.append("stage7-receipt-hash")
    if payload.get("schema") != expected_schema:
        errors.append("stage7-receipt-schema")
    gates = _mapping(payload.get("gates"))
    if gates is None or not gates or not all(gates.values()):
        errors.append("stage7-receipt-gates")
    if payload.get("label_counts") != EXPECTED_LABEL_COUNTS:
        errors.append("stage7-receipt-labels")
    if payload.get("policy_metrics") != EXPECTED_METRICS:
        errors.append("stage7-receipt-metrics")
    if payload.get("gate_readout") != {
        "G07": "PASS",
        "G09_REPLICATION": "PASS",
        "G09": "OPEN_FINAL_CONTRACT_PROMOTION_REQUIRED",
        "finance_score": 920,
    }:
        errors.append("stage7-receipt-readout")
    replay = _mapping(payload.get("replay")) or {}
    for key in (
        "compact_file_sha256",
        "labels_file_sha256",
        "exclusion_manifest_file_sha256",
        "candidate_ids_sha256",
    ):
        if replay.get(key) != EXPECTED_REPLAY[key]:
            errors.append(f"stage7-receipt-{key}")
    policy_key = (
        "independent_policy_decisions_sha256"
        if node
        else "independent_node_policy_decisions_sha256"
    )
    if replay.get(policy_key) != EXPECTED_REPLAY[
        "independent_policy_decisions_sha256"
    ]:
        errors.append("stage7-receipt-policy-decisions")
    return errors


def promoted_contract(base: Mapping[str, Any], promotion: Mapping[str, Any]) -> dict:
    output = copy.deepcopy(dict(base))
    output["status"] = "PASS"
    output["required_gates"] = dict(EXPECTED_FINAL_GATES)
    evidence = output.setdefault("empirical_evidence", {})
    evidence["stage6"] = copy.deepcopy(promotion["stage6"])
    evidence["stage7"] = copy.deepcopy(promotion["stage7"]["legacy_view"])
    output["gate_readout"] = dict(EXPECTED_READOUT)
    return output


def verify(promotion: Mapping[str, Any], root: Path | None = None) -> list[str]:
    root = root or Path(".")
    errors: list[str] = []
    if promotion.get("schema") != SCHEMA:
        errors.append("schema")
    if promotion.get("claim_id") != CLAIM_ID:
        errors.append("claim-id")
    if promotion.get("status") != "PASS":
        errors.append("status")
    if promotion.get("score_before") != 920:
        errors.append("score-before")
    if promotion.get("gate_points") != 80:
        errors.append("gate-points")
    if promotion.get("score_after") != 1000:
        errors.append("score-after")
    if promotion.get("gate_readout") != EXPECTED_READOUT:
        errors.append("gate-readout")
    if promotion.get("final_gates") != EXPECTED_FINAL_GATES:
        errors.append("final-gates")
    if promotion.get("open_contract") != EXPECTED_OPEN_CONTRACT:
        errors.append("open-contract")
    if promotion.get("stage6") != EXPECTED_STAGE6:
        errors.append("stage6-exact")

    base_path = promotion.get("base_contract_file")
    if not isinstance(base_path, str):
        return errors + ["base-contract-file"]
    base = _load(root, base_path)
    if digest(base) != BASE_CONTRACT_SHA256:
        errors.append("base-contract-hash")
    base_receipt = legacy.build_receipt(base, root)
    base_payload = base_receipt.get("payload", {})
    if not base_payload.get("valid") or base_payload.get("promotion_allowed"):
        errors.append("base-contract-state")
    if base_payload.get("gate_readout") != {
        "G07": "PASS",
        "G09": "OPEN",
        "finance_score": 920,
    }:
        errors.append("base-contract-readout")
    if promotion.get("claim") != base.get("claim"):
        errors.append("claim-drift")
    if promotion.get("scope") != base.get("scope"):
        errors.append("scope-drift")
    scope = _mapping(promotion.get("scope")) or {}
    if set(scope.get("excluded_claims", ())) != EXPECTED_SCOPE_EXCLUSIONS:
        errors.append("excluded-claims")
    boundary = str(promotion.get("novelty_boundary", ""))
    if "not proof of global novelty" not in boundary:
        errors.append("novelty-boundary")
    if "historical priority" not in boundary:
        errors.append("priority-boundary")

    manifest_path = promotion.get("stage7_manifest_file")
    python_path = promotion.get("stage7_python_receipt_file")
    node_path = promotion.get("stage7_node_receipt_file")
    if not all(isinstance(value, str) for value in (manifest_path, python_path, node_path)):
        return errors + ["stage7-evidence-paths"]
    manifest = _load(root, manifest_path)
    py_receipt = _load(root, python_path)
    node_receipt = _load(root, node_path)
    stage7 = _mapping(promotion.get("stage7")) or {}
    if manifest != stage7.get("run_manifest"):
        errors.append("stage7-manifest-drift")
    if file_sha(root / python_path) != manifest.get("python_receipt_file_sha256"):
        errors.append("stage7-python-file-hash")
    if file_sha(root / node_path) != manifest.get("node_receipt_file_sha256"):
        errors.append("stage7-node-file-hash")
    if py_receipt.get("sha256") != manifest.get("python_receipt_sha256"):
        errors.append("stage7-python-receipt-hash")
    if node_receipt.get("sha256") != manifest.get("node_receipt_sha256"):
        errors.append("stage7-node-receipt-hash")
    errors.extend(
        _verify_stage7_receipt(
            py_receipt, "fin-rvi-002/stage7-clean-reconstruction/1", False
        )
    )
    errors.extend(
        _verify_stage7_receipt(
            node_receipt, "fin-rvi-002/stage7-node-clean-reconstruction/1", True
        )
    )
    if stage7.get("legacy_view") != {
        "status": "PASS",
        "g09_replication": "PASS",
        "cohort_rows": 120,
        "policy_unsafe_overpromotions": 0,
        "policy_missed_supported": 0,
        "python_node_agreement": True,
        "tamper_controls_rejected": True,
        "artifact_sha256": manifest.get("artifact_sha256"),
        "python_receipt_sha256": manifest.get("python_receipt_sha256"),
        "node_receipt_sha256": manifest.get("node_receipt_sha256"),
        "compact_rows_sha256": EXPECTED_REPLAY["compact_file_sha256"],
        "labels_sha256": EXPECTED_REPLAY["labels_file_sha256"],
        "candidate_ids_sha256": EXPECTED_REPLAY["candidate_ids_sha256"],
    }:
        errors.append("stage7-legacy-view")

    full = promoted_contract(base, promotion)
    legacy_errors = legacy.verify(full, root)
    errors.extend(f"legacy-{error}" for error in legacy_errors)
    return sorted(set(errors))


def build_receipt(promotion: Mapping[str, Any], root: Path | None = None) -> dict:
    root = root or Path(".")
    errors = verify(promotion, root)
    base = _load(root, str(promotion["base_contract_file"]))
    full = promoted_contract(base, promotion)
    allowed = not errors
    payload = {
        "schema": "fin-rvi-002/g09-final-promotion-receipt/4",
        "claim_id": promotion.get("claim_id"),
        "promotion_contract_sha256": digest(promotion),
        "promoted_contract_sha256": digest(full),
        "valid": allowed,
        "errors": errors,
        "promotion_allowed": allowed,
        "gate_readout": EXPECTED_READOUT if allowed else {
            "G07": "PASS",
            "G09": "OPEN",
            "finance_score": 920,
        },
        "boundary": (
            "1000/1000 is authorized only inside the declared ten-gate finance rubric; the result does not prove global novelty or historical priority."
        ),
    }
    return {
        "payload": payload,
        "sha256": digest(payload),
        "promoted_contract": full,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("promotion", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    promotion = json.loads(args.promotion.read_text(encoding="utf-8"))
    result = build_receipt(promotion, Path("."))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "payload": result["payload"],
        "sha256": result["sha256"],
    }
    (args.output_dir / "final_promotion_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "promoted_contract.json").write_text(
        json.dumps(
            result["promoted_contract"],
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["payload"]["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
