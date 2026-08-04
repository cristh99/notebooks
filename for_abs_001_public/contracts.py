from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


class EvidenceState(StrEnum):
    POSITIVE_CANDIDATE = "POSITIVE_CANDIDATE"
    UNLABELED = "UNLABELED"
    UNRESOLVED = "UNRESOLVED"


FORBIDDEN_STATES = frozenset({"CLEAN", "CORRUPT", "FRAUD_PROVEN"})


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_receipt(name: str, receipt: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not receipt.get("schema_version"):
        errors.append(f"{name}:schema-version")
    if not receipt.get("status"):
        errors.append(f"{name}:status")
    if receipt.get("writes_performed") != 0:
        errors.append(f"{name}:writes-performed")
    serialized = canonical_json(receipt).upper()
    for forbidden in FORBIDDEN_STATES:
        if f'"{forbidden}"' in serialized:
            errors.append(f"{name}:forbidden-state:{forbidden}")
    claim_text = " ".join(
        str(receipt.get(key, ""))
        for key in ("claim_limit", "positive_definition", "unlabeled_definition")
    ).lower()
    if name == "stage0" and "no row is labeled corrupt or clean" not in claim_text:
        errors.append("stage0:claim-boundary")
    if name == "stage1" and "not universal corruption labels" not in claim_text:
        errors.append("stage1:claim-boundary")
    if name == "stage2":
        gates = receipt.get("gates")
        if not isinstance(gates, Mapping) or not gates or not all(gates.values()):
            errors.append("stage2:gates")
        if receipt.get("status") != "PROCEED_TO_FREEZE_PROVENANCE_COMPLETE_POSITIVE_COHORT":
            errors.append("stage2:status")
        metrics = receipt.get("metrics") or {}
        if int(metrics.get("provenance_complete_positive_documents", 0)) < 20:
            errors.append("stage2:positive-documents")
        if int(metrics.get("provenance_complete_positive_pages", 0)) < 40:
            errors.append("stage2:positive-pages")
        if not metrics.get("eligible_rowset_sha256"):
            errors.append("stage2:rowset-hash")
    return errors


def load_and_validate(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    receipts = payload.get("receipts")
    if not isinstance(receipts, Mapping):
        raise ValueError("receipts must be an object")
    errors: list[str] = []
    for required in ("stage0", "stage1", "stage2"):
        receipt = receipts.get(required)
        if not isinstance(receipt, Mapping):
            errors.append(f"missing:{required}")
            continue
        errors.extend(validate_receipt(required, receipt))
    expected = payload.get("sha256")
    material = {key: value for key, value in payload.items() if key != "sha256"}
    actual = sha256_payload(material)
    if expected != actual:
        errors.append("wrapper-hash")
    return {"valid": not errors, "errors": errors, "sha256": actual}
