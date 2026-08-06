from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import verify_envelope as v

HERE = Path(__file__).resolve().parent
PAYLOAD = json.loads((HERE / "ENVELOPE.json").read_text())


class EnvelopeTests(unittest.TestCase):
    def test_canonical_envelope_passes(self):
        v.validate_envelope(copy.deepcopy(PAYLOAD))

    def test_original_commit_drift_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["original_preregistration"]["commit_sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "commit"): v.validate_envelope(p)

    def test_original_blob_drift_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["original_preregistration"]["git_blob_sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "blob"): v.validate_envelope(p)

    def test_original_path_drift_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["original_preregistration"]["path"] = "other"
        with self.assertRaisesRegex(ValueError, "path"): v.validate_envelope(p)

    def test_content_opened_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["original_preregistration"]["source_document_content_opened"] = True
        with self.assertRaisesRegex(ValueError, "opened"): v.validate_envelope(p)

    def test_pdf_download_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["original_preregistration"]["source_pdf_bytes_downloaded"] = True
        with self.assertRaisesRegex(ValueError, "downloaded"): v.validate_envelope(p)

    def test_wrong_base_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["trust_contract"]["expected_base_branch"] = "main"
        with self.assertRaisesRegex(ValueError, "base"): v.validate_envelope(p)

    def test_wrong_head_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["trust_contract"]["expected_head_branch"] = "main"
        with self.assertRaisesRegex(ValueError, "head"): v.validate_envelope(p)

    def test_wrong_issuer_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["trust_contract"]["oidc_issuer"] = "https://example.com"
        with self.assertRaisesRegex(ValueError, "issuer"): v.validate_envelope(p)

    def test_cosign_hash_drift_is_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["trust_contract"]["cosign_linux_amd64_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "cosign hash"): v.validate_envelope(p)

    def test_stage08_unblock_is_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["execution_controls"]["stage08_unblocked"] = True
        with self.assertRaisesRegex(ValueError, "stage08"): v.validate_envelope(p)

    def test_nonzero_cost_is_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["execution_controls"]["external_cost_usd"] = 0.01
        with self.assertRaisesRegex(ValueError, "cost"): v.validate_envelope(p)

    def test_secret_like_key_is_rejected(self):
        p = copy.deepcopy(PAYLOAD); p["execution_controls"]["private" + "_key"] = "x"
        with self.assertRaisesRegex(ValueError, "credential-like"): v.validate_envelope(p)

    def test_noncanonical_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = v.ENVELOPE_PATH
            try:
                path = Path(tmp) / "ENVELOPE.json"
                path.write_text(json.dumps(PAYLOAD, indent=2) + "\n")
                v.ENVELOPE_PATH = path
                with self.assertRaisesRegex(ValueError, "canonical"): v.load_envelope()
            finally:
                v.ENVELOPE_PATH = original


if __name__ == "__main__":
    unittest.main()
