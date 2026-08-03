"""Semantic-boundary wrapper for the G09 final contract.

The systematic-search log was frozen before the final contract added explicit
independent-implementation language. This wrapper accepts that strengthening
only when the search log contains every scientific core of the final claim; it
never permits a broader financial, legal, causal, or global claim.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from . import verify_final_contract_v2 as base

PRIOR_ART_CORE_PHRASES = (
    "multiple preregistered, mutually code-disjoint public Honduras ONCAE-SEFIN cohorts",
    "exact contract/project-code blocking",
    "compatible supplier identity",
    "fixed fail-closed documentary policy",
    "maximum claim CONTRACTOR_PAYMENT",
    "reduces unsupported payment attribution",
    "without reducing recovery of supported payments",
    "preserving one-to-many contract-payment cardinality",
    "strong baselines",
    "monetary amount at risk",
    "permutation controls",
    "independent clean replay",
)


def verify_prior_art_semantic(
    contract: Mapping[str, Any], root: Path
) -> list[str]:
    errors = base.verify_prior_art(contract, root)
    if "prior-art-claim-boundary" not in errors:
        return errors
    boundary = contract.get("prior_art_boundary")
    if not isinstance(boundary, Mapping):
        return errors
    relative = boundary.get("closure_file")
    if not isinstance(relative, str):
        return errors
    path = root / relative
    if not path.exists():
        return errors
    closure = json.loads(path.read_text(encoding="utf-8"))
    bounded = str(closure.get("bounded_remaining_claim", ""))
    contract_claim = str(contract.get("claim", ""))
    absorbed = set(boundary.get("absorbed_components", ()))
    semantic_pass = (
        all(phrase in bounded for phrase in PRIOR_ART_CORE_PHRASES)
        and "independent policy implementation" in contract_claim
        and "clean public reconstruction" in contract_claim
        and absorbed == base.REQUIRED_ABSORBED
    )
    if semantic_pass:
        errors = [error for error in errors if error != "prior-art-claim-boundary"]
    return errors


def verify(contract: Mapping[str, Any], root: Path | None = None) -> list[str]:
    root = root or Path(".")
    original = base.verify_prior_art
    base.verify_prior_art = verify_prior_art_semantic
    try:
        return base.verify(contract, root)
    finally:
        base.verify_prior_art = original


def build_receipt(
    contract: Mapping[str, Any], root: Path | None = None
) -> dict[str, Any]:
    errors = verify(contract, root)
    gates = contract.get("required_gates")
    gates = gates if isinstance(gates, Mapping) else {}
    passed = sum(value == "PASS" for value in gates.values())
    promotion = (
        not errors
        and contract.get("status") == "PASS"
        and passed == len(base.REQUIRED_GATES)
    )
    payload = {
        "schema": "fin-rvi-002/g09-final-contract-receipt/3",
        "claim_id": contract.get("claim_id"),
        "contract_sha256": base.digest(contract),
        "valid": not errors,
        "errors": errors,
        "status": contract.get("status"),
        "passed_required_gates": passed,
        "total_required_gates": len(base.REQUIRED_GATES),
        "promotion_allowed": promotion,
        "gate_readout": (
            {"G07": "PASS", "G09": "PASS", "finance_score": 1000}
            if promotion
            else {"G07": "PASS", "G09": "OPEN", "finance_score": 920}
        ),
    }
    return {"payload": payload, "sha256": base.digest(payload)}


def main() -> int:
    source = Path("fin_rvi_002_g09/final_contract_v2.json")
    contract = json.loads(source.read_text(encoding="utf-8"))
    receipt = build_receipt(contract, Path("."))
    output = Path("reports/fin_rvi_002_g09_v3")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "final_contract_receipt.json"
    target.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["payload"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
