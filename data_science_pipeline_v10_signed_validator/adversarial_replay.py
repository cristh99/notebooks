from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from evidence_scope import ChannelValidation, EvidenceChannel, canonical_bytes
from signed_validator import (
    SignedChannelValidation,
    TrustEntry,
    TrustRegistry,
    authorize_validations,
)

SEED = 20260806
CASES = 1000
CASE_NAMES = (
    "valid",
    "forged",
    "cross_validator",
    "untrusted",
    "wrong_policy",
    "wrong_channel",
    "wrong_registry",
)
POLICY_A = hashlib.sha256(b"policy-a").hexdigest()
POLICY_B = hashlib.sha256(b"policy-b").hexdigest()


def _public_raw(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def run() -> dict[str, Any]:
    rng = random.Random(SEED)
    private_a = Ed25519PrivateKey.generate()
    private_b = Ed25519PrivateKey.generate()
    entry = TrustEntry(
        validator_id="validator:oncae:01",
        public_key_raw=_public_raw(private_a),
        allowed_policy_sha256=(POLICY_A,),
        allowed_channels=(
            EvidenceChannel.SOURCE_PROVENANCE,
            EvidenceChannel.OCR_CONTENT,
        ),
    )
    registry = TrustRegistry((entry,))
    registry_sha256 = registry.sha256()
    counts = {case: 0 for case in CASE_NAMES}
    accepted = {case: 0 for case in CASE_NAMES}
    rejected = {case: 0 for case in CASE_NAMES}
    channels = (
        EvidenceChannel.SOURCE_PROVENANCE,
        EvidenceChannel.OCR_CONTENT,
    )

    for index in range(CASES):
        case = rng.choice(CASE_NAMES)
        counts[case] += 1
        channel = rng.choice(channels)
        observation = f"case-{index}-PACC-ONCAE"
        validator_id = entry.validator_id
        policy_sha256 = POLICY_A
        private_key = private_a
        mapping_channel = channel
        expected_registry_sha256 = registry_sha256

        if case == "untrusted":
            validator_id = "validator:unknown"
            private_key = private_b
        elif case == "wrong_policy":
            policy_sha256 = POLICY_B
        elif case == "wrong_channel":
            channel = EvidenceChannel.DOCUMENT_METADATA
            mapping_channel = channel
        elif case == "cross_validator":
            private_key = private_b
        elif case == "wrong_registry":
            expected_registry_sha256 = "0" * 64

        validation = ChannelValidation.issue(
            channel=channel,
            observation=observation,
            validator_id=validator_id,
            policy_sha256=policy_sha256,
        )
        signed = SignedChannelValidation.sign(
            validation=validation,
            private_key=private_key,
            registry_sha256=registry_sha256,
        )
        if case == "forged":
            signature = bytearray(signed.signature)
            signature[rng.randrange(64)] ^= 1
            signed = signed.with_signature(bytes(signature))

        try:
            authorized = authorize_validations(
                {mapping_channel: signed},
                registry=registry,
                expected_registry_sha256=expected_registry_sha256,
            )
            accepted[case] += int(mapping_channel in authorized)
        except (TypeError, ValueError):
            rejected[case] += 1

    invariant_violations = 0
    if accepted["valid"] != counts["valid"] or rejected["valid"] != 0:
        invariant_violations += 1
    for case in CASE_NAMES:
        if case == "valid":
            continue
        if accepted[case] != 0 or rejected[case] != counts[case]:
            invariant_violations += 1

    return {
        "schema": "data-science-pipeline/signed-validator-adversarial-report/1",
        "seed": SEED,
        "cases": CASES,
        "counts": counts,
        "accepted": accepted,
        "rejected": rejected,
        "invariant_violations": invariant_violations,
        "verdict": "PASS" if invariant_violations == 0 else "FAIL",
    }


def main() -> int:
    report = run()
    print(canonical_bytes(report).decode("utf-8"), end="")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
