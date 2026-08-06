from __future__ import annotations

import inspect
import math
import unittest

import arbiter
from arbiter import (
    Candidate,
    CandidateKind,
    DecisionStatus,
    EvidenceChannel,
    SemanticClass,
    TrustEvidence,
    arbitrate_entities,
    arbitrate_numeric,
    build_receipt,
    classify_numeric,
    receipt_json,
    strict_json_loads,
)


D = "a" * 64
P = "b" * 64
R = "c" * 64
V = "d" * 64


def trust(**overrides):
    values = {
        "validator_id": "validator-1",
        "validation_receipt_sha256": V,
        "policy_sha256": P,
        "validator_registry_sha256": R,
        "signature_valid": True,
        "registry_hash_matches": True,
        "policy_authorized": True,
        "channel_authorized": True,
        "native_control_contradicts": False,
    }
    values.update(overrides)
    return TrustEvidence(**values)


def candidate(
    candidate_id: str,
    *,
    kind=CandidateKind.ENTITY,
    value="ONCAE",
    display="ONCAE",
    channel=EvidenceChannel.OCR_CONTENT,
    trust_value=None,
    semantic_class=None,
    context="",
    role=None,
    body_support=False,
    registry_support=False,
    exact_match=False,
    contextual_only=False,
    generic_jurisdiction=False,
    exclusive_role=False,
    confidence_rank=10,
    source_hash_verified=True,
    normalization_hash_verified=True,
):
    return Candidate(
        candidate_id=candidate_id,
        kind=kind,
        document_id="doc-1",
        page_id="page-1",
        line_id="line-1",
        source_sha256=D,
        normalization_manifest_sha256="e" * 64,
        candidate_value_normalized=value,
        candidate_value_display=display,
        evidence_channel=channel,
        trust=trust_value or trust(),
        resolver_id="resolver",
        resolver_version="1",
        role=role,
        semantic_class=semantic_class,
        context=context,
        body_support=body_support,
        registry_support=registry_support,
        exact_match=exact_match,
        contextual_only=contextual_only,
        generic_jurisdiction=generic_jurisdiction,
        exclusive_role=exclusive_role,
        confidence_rank=confidence_rank,
        source_hash_verified=source_hash_verified,
        normalization_hash_verified=normalization_hash_verified,
    )


class ArbiterContractTests(unittest.TestCase):
    def test_01_exact_issuing_entity_accepted(self):
        c = candidate(
            "e1",
            value="oficina normativa de contratacion y adquisiciones del estado",
            display="ONCAE",
            body_support=True,
            exact_match=True,
            role="issuing_entity",
            exclusive_role=True,
        )
        d = arbitrate_entities([c])
        self.assertEqual(d.status, DecisionStatus.ACCEPT)
        self.assertEqual(d.code, "EXACT_SOURCE_BOUND_ENTITY")

    def test_02_address_landmark_contextual_only(self):
        c = candidate(
            "e2",
            value="colegio de ingenieros civiles de honduras",
            contextual_only=True,
        )
        d = arbitrate_entities([c])
        self.assertEqual(d.status, DecisionStatus.ABSTAIN)
        self.assertEqual(d.code, "CONTEXTUAL_ORGANIZATION_ONLY")

    def test_03_generic_jurisdiction_abstains(self):
        c = candidate(
            "e3",
            value="honduras gobierno de la republica",
            generic_jurisdiction=True,
        )
        self.assertEqual(
            arbitrate_entities([c]).code, "GENERIC_JURISDICTION_ABSTAIN"
        )

    def test_04_equal_strength_collision_abstains(self):
        c1 = candidate(
            "e4a",
            value="entidad a",
            body_support=True,
            exact_match=True,
            exclusive_role=True,
        )
        c2 = candidate(
            "e4b",
            value="entidad b",
            body_support=True,
            exact_match=True,
            exclusive_role=True,
        )
        d = arbitrate_entities([c1, c2])
        self.assertEqual(d.code, "COLLISION_ABSTAIN")

    def test_05_decree_is_legal_instrument(self):
        self.assertEqual(
            classify_numeric("62-2023", "Decreto Legislativo 62-2023"),
            SemanticClass.LEGAL_INSTRUMENT_ID,
        )

    def test_06_phone_not_amount(self):
        self.assertEqual(
            classify_numeric("+504 2209-5355"), SemanticClass.TELEPHONE
        )

    def test_07_fiscal_year_not_amount(self):
        c = candidate(
            "n7",
            kind=CandidateKind.NUMERIC,
            value="2024",
            display="2024",
            context="EJERCICIO FISCAL 2024",
            semantic_class=SemanticClass.FISCAL_PERIOD,
            body_support=True,
        )
        d = arbitrate_numeric(c)
        self.assertEqual(d.semantic_class, SemanticClass.FISCAL_PERIOD)
        self.assertNotIn("MONETARY", d.code)

    def test_08_explicit_amount_accepted(self):
        c = candidate(
            "n8",
            kind=CandidateKind.NUMERIC,
            value="1250.00",
            display="L. 1,250.00",
            semantic_class=SemanticClass.MONETARY_AMOUNT,
            context="monto contractual",
            body_support=True,
        )
        d = arbitrate_numeric(c)
        self.assertEqual(d.status, DecisionStatus.ACCEPT)
        self.assertEqual(d.semantic_class, SemanticClass.MONETARY_AMOUNT)

    def test_09_metadata_only_identity_rejected(self):
        c = candidate(
            "e9",
            value="editor declarado",
            channel=EvidenceChannel.DOCUMENT_METADATA,
            exact_match=True,
            body_support=False,
            registry_support=False,
        )
        d = arbitrate_entities([c])
        self.assertNotEqual(d.status, DecisionStatus.ACCEPT)

    def test_10_native_control_contradiction_quarantines(self):
        c = candidate(
            "n10",
            kind=CandidateKind.NUMERIC,
            value="1250.00",
            display="L. 1,250.00",
            semantic_class=SemanticClass.MONETARY_AMOUNT,
            body_support=True,
            trust_value=trust(native_control_contradicts=True),
        )
        self.assertEqual(
            arbitrate_numeric(c).code, "OCR_CANDIDATE_QUARANTINE"
        )

    def test_11_forged_signature_fails_closed(self):
        c = candidate(
            "e11",
            body_support=True,
            exact_match=True,
            trust_value=trust(signature_valid=False),
        )
        d = arbitrate_entities([c])
        self.assertEqual(d.status, DecisionStatus.QUARANTINE)

    def test_12_unauthorized_channel_fails_closed(self):
        c = candidate(
            "e12",
            body_support=True,
            exact_match=True,
            trust_value=trust(channel_authorized=False),
        )
        self.assertEqual(arbitrate_entities([c]).code, "CHANNEL_SCOPE_REJECT")

    def test_13_altered_hash_fails_closed(self):
        c = candidate(
            "e13",
            body_support=True,
            exact_match=True,
            source_hash_verified=False,
        )
        self.assertEqual(
            arbitrate_entities([c]).code,
            "QUARANTINE_MISSING_OR_ALTERED_LINEAGE",
        )

    def test_14_nonfinite_json_rejected(self):
        with self.assertRaises(ValueError):
            strict_json_loads('{"x": NaN}')
        with self.assertRaises(ValueError):
            arbiter.canonical_json({"x": math.inf})

    def test_15_receipt_is_byte_deterministic(self):
        c1 = candidate(
            "e15",
            body_support=True,
            exact_match=True,
            value="oncae",
        )
        d1 = arbitrate_entities([c1])
        r1 = build_receipt(candidates=[c1], decisions=[d1])
        r2 = build_receipt(candidates=[c1], decisions=[d1])
        self.assertEqual(receipt_json(r1), receipt_json(r2))
        self.assertEqual(r1.replay_digest, r2.replay_digest)

    def test_16_module_has_no_network_or_production_api(self):
        source = inspect.getsource(arbiter)
        forbidden = (
            "requests.",
            "urllib.",
            "socket.",
            "google.cloud",
            "boto3",
            "subprocess.",
            "open(",
        )
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
