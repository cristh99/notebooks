from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from verify_static import canonical_bytes, validate_file, validate_payload

HERE = Path(__file__).resolve().parent
PREREG = json.loads((HERE / "PREREGISTRATION.json").read_text(encoding="utf-8"))


class PreregistrationTests(unittest.TestCase):
    def test_canonical_record_passes(self) -> None:
        self.assertTrue(all(validate_payload(copy.deepcopy(PREREG)).values()))

    def test_pdf_url_must_remain_unknown(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["source_selection"]["pdf_url"] = "https://oncae.gob.hn/document.pdf"
        with self.assertRaisesRegex(ValueError, "pdf_url"):
            validate_payload(payload)

    def test_document_content_access_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["source_selection"]["document_content_accessed_before_freeze"] = True
        with self.assertRaisesRegex(ValueError, "document_content_accessed"):
            validate_payload(payload)

    def test_wrong_source_host_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["source_selection"]["official_host"] = "example.com"
        with self.assertRaisesRegex(ValueError, "host"):
            validate_payload(payload)

    def test_metadata_cannot_confirm_content(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["channel_contract"]["document_metadata"]["can_confirm_content"] = True
        with self.assertRaisesRegex(ValueError, "metadata authority"):
            validate_payload(payload)

    def test_post_result_retuning_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["execution_controls"]["post_result_retuning_permitted"] = True
        with self.assertRaisesRegex(ValueError, "retuning"):
            validate_payload(payload)

    def test_stage08_unblock_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["execution_controls"]["stage08_unblocked"] = True
        with self.assertRaisesRegex(ValueError, "Stage 08"):
            validate_payload(payload)

    def test_nonzero_cost_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["execution_controls"]["external_cost_usd"] = 0.01
        with self.assertRaisesRegex(ValueError, "cost"):
            validate_payload(payload)

    def test_retired_hash_duplicate_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        retired = payload["freshness"]["retired_source_sha256"]
        retired[-1] = retired[0]
        with self.assertRaisesRegex(ValueError, "retired hash"):
            validate_payload(payload)

    def test_transparency_log_requirement_cannot_be_removed(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["trust_contract"]["transparency_log_inclusion_required"] = False
        with self.assertRaisesRegex(ValueError, "transparency"):
            validate_payload(payload)

    def test_cosign_hash_drift_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["trust_contract"]["cosign_linux_amd64_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "cosign hash"):
            validate_payload(payload)

    def test_workflow_ref_drift_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["trust_contract"]["workflow_path"] = "other"
        with self.assertRaisesRegex(ValueError, "workflow path"):
            validate_payload(payload)

    def test_issuer_drift_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["trust_contract"]["oidc_issuer"] = "https://example.com"
        with self.assertRaisesRegex(ValueError, "issuer"):
            validate_payload(payload)

    def test_secret_like_field_is_rejected(self) -> None:
        payload = copy.deepcopy(PREREG)
        payload["execution_controls"]["private_key"] = "forbidden"
        with self.assertRaisesRegex(ValueError, "credential-like"):
            validate_payload(payload)

    def test_noncanonical_json_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.json"
            path.write_text(json.dumps(PREREG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "canonical JSON"):
                validate_file(path)


if __name__ == "__main__":
    unittest.main()
