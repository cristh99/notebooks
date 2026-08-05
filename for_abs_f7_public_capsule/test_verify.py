from __future__ import annotations

import copy
import hashlib
import json
import unittest

import verify


def rehash(payload, field):
    body = dict(payload)
    body.pop(field, None)
    payload[field] = hashlib.sha256(verify.canonical(body).encode("utf-8")).hexdigest()


class PublicF7VerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payloads = {
            name: copy.deepcopy(verify.load(path))
            for name, path in verify.FILES.items()
        }

    def test_frozen_receipts_pass_and_bind_score(self) -> None:
        report = verify.verify_all(self.payloads)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["f7_after"], 82)
        self.assertEqual(report["score_after"], 671)
        self.assertEqual(report["executed_negative_attacks"], 18)
        self.assertFalse(report["is_god_mode"])

    def test_bundle_amount_tamper_fails_after_semantic_rehash(self) -> None:
        for row in self.payloads["bundle"]["amount_manifest"]:
            if row["role"] == "STRUCTURED_CONTRACT_VALUE":
                row["amount_cents"] += 100
        rehash(self.payloads["bundle"], "receipt_sha256")
        with self.assertRaisesRegex(ValueError, "amount value"):
            verify.verify_all(self.payloads)

    def test_replay_missing_negative_attacks_fails_after_rehash(self) -> None:
        self.payloads["replay"]["page_substitution_attack_count"] = 0
        rehash(self.payloads["replay"], "receipt_sha256")
        with self.assertRaisesRegex(ValueError, "attack count"):
            verify.verify_all(self.payloads)

    def test_pointer_lineage_forgery_fails_after_rehash(self) -> None:
        self.payloads["pointer"]["independent_replay_receipt_sha256"] = "f" * 64
        rehash(self.payloads["pointer"], "pointer_receipt_sha256")
        with self.assertRaisesRegex(ValueError, "pointer replay lineage"):
            verify.verify_all(self.payloads)

    def test_failed_frozen_block_cannot_promote_after_rehash(self) -> None:
        self.payloads["promotion"]["blocks"][
            "F7D_INDEPENDENT_ADVERSARIAL_REPLAY"
        ] = False
        rehash(self.payloads["promotion"], "receipt_sha256")
        with self.assertRaisesRegex(ValueError, "failed block"):
            verify.verify_all(self.payloads)

    def test_corruption_claim_guard_fails_after_rehash(self) -> None:
        self.payloads["bundle"]["corruption_claims_created"] = 1
        rehash(self.payloads["bundle"], "receipt_sha256")
        with self.assertRaisesRegex(ValueError, "corruption claim"):
            verify.verify_all(self.payloads)

    def test_plain_digest_tamper_is_detected(self) -> None:
        self.payloads["bundle"]["source_count"] = 5
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify.verify_all(self.payloads)

    def test_report_is_deterministic(self) -> None:
        first = verify.verify_all(self.payloads)
        second = verify.verify_all(copy.deepcopy(self.payloads))
        self.assertEqual(first, second)
        self.assertEqual(
            first["report_digest"],
            hashlib.sha256(
                verify.canonical(
                    {key: value for key, value in first.items() if key != "report_digest"}
                ).encode("utf-8")
            ).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
