from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from verify_preregistration import canonical_bytes, validate_file, validate_payload


HERE = Path(__file__).resolve().parent
BASE = json.loads((HERE / "PREREGISTRATION.json").read_text(encoding="utf-8"))


class PreregistrationTests(unittest.TestCase):
    def mutated(self) -> dict[str, object]:
        return copy.deepcopy(BASE)

    def test_canonical_preregistration_passes(self) -> None:
        checks = validate_file(HERE / "PREREGISTRATION.json")
        self.assertTrue(all(checks.values()))

    def test_pdf_url_must_remain_unknown(self) -> None:
        payload = self.mutated()
        payload["source_selection"]["pdf_url"] = "https://oncae.gob.hn/example.pdf"
        with self.assertRaisesRegex(ValueError, "pdf_url"):
            validate_payload(payload)

    def test_content_access_before_freeze_is_rejected(self) -> None:
        payload = self.mutated()
        payload["source_selection"]["document_content_accessed_before_freeze"] = True
        with self.assertRaisesRegex(ValueError, "document_content_accessed_before_freeze"):
            validate_payload(payload)

    def test_wrong_host_is_rejected(self) -> None:
        payload = self.mutated()
        payload["source_selection"]["official_host"] = "example.com"
        with self.assertRaisesRegex(ValueError, "official host"):
            validate_payload(payload)

    def test_metadata_cannot_confirm_content(self) -> None:
        payload = self.mutated()
        payload["channel_contract"]["document_metadata"]["can_confirm_content"] = True
        with self.assertRaisesRegex(ValueError, "metadata authority"):
            validate_payload(payload)

    def test_partial_document_policy_is_rejected(self) -> None:
        payload = self.mutated()
        payload["evaluation_contract"]["document_scope"]["full_document_required"] = False
        with self.assertRaisesRegex(ValueError, "full document"):
            validate_payload(payload)

    def test_retired_hashes_must_be_unique(self) -> None:
        payload = self.mutated()
        hashes = payload["freshness"]["retired_source_sha256"]
        hashes.append(hashes[0])
        with self.assertRaisesRegex(ValueError, "retired hashes duplicate"):
            validate_payload(payload)

    def test_nonzero_cost_is_rejected(self) -> None:
        payload = self.mutated()
        payload["execution_controls"]["external_cost_usd"] = 0.01
        with self.assertRaisesRegex(ValueError, "external cost"):
            validate_payload(payload)

    def test_post_result_retuning_is_rejected(self) -> None:
        payload = self.mutated()
        payload["execution_controls"]["post_result_retuning_permitted"] = True
        with self.assertRaisesRegex(ValueError, "retuning"):
            validate_payload(payload)

    def test_metadata_cannot_replace_ocr_channel(self) -> None:
        payload = self.mutated()
        payload["evaluation_contract"]["content_claim"]["confirmation_channel"] = "document_metadata"
        with self.assertRaisesRegex(ValueError, "content channel"):
            validate_payload(payload)

    def test_secret_like_field_is_rejected(self) -> None:
        payload = self.mutated()
        payload["execution_controls"]["api_key"] = "not-a-real-key"
        with self.assertRaisesRegex(ValueError, "credential-like"):
            validate_payload(payload)

    def test_noncanonical_json_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prereg.json"
            path.write_text(json.dumps(BASE, indent=2, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "canonical JSON"):
                validate_file(path)


if __name__ == "__main__":
    unittest.main()
