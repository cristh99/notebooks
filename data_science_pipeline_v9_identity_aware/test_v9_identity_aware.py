from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from adjudicate import adjudicate
from candidate_resolver import EXPECTED_CANDIDATES, extract_facts, resolve
from discover_pdf import discover
from facts_contract import canonical_decimal, canonical_json_bytes, fact_key, sha256_file
from native_oracle import build_oracle, extract_oracle_facts
from secure_fetch import FetchValidationError, PinnedHTTPSConnection, resolve_public_addresses, validate_url


class MoneyTests(unittest.TestCase):
    def test_canonical_decimal_common_honduran_formats(self) -> None:
        self.assertEqual(canonical_decimal("1,250.50"), "1250.50")
        self.assertEqual(canonical_decimal("1.250,50"), "1250.50")
        self.assertEqual(canonical_decimal("1,250"), "1250")
        self.assertEqual(canonical_decimal("1250,50"), "1250.50")

    def test_canonical_decimal_rejects_ambiguous_or_extreme_values(self) -> None:
        self.assertIsNone(canonical_decimal("1,2,34"))
        self.assertIsNone(canonical_decimal("0"))
        self.assertIsNone(canonical_decimal("999999999999999999999"))


class CandidateExtractionTests(unittest.TestCase):
    SAMPLE = """
    CIRCULAR ONCAE-004-2026
    Tegucigalpa, 14 de julio de 2026
    Oficina Normativa de Contratación y Adquisiciones del Estado (ONCAE)
    Monto de referencia: L. 1,250.50
    Correo: info@oncae.gob.hn
    Teléfono: 2230-1234
    """

    def test_extracts_frozen_fact_types(self) -> None:
        facts = extract_facts(self.SAMPLE)
        self.assertIn(fact_key("circular_id", "ONCAE-004-2026"), facts)
        self.assertIn(fact_key("date", "2026-07-14"), facts)
        self.assertIn(fact_key("money", "HNL:1250.50"), facts)
        self.assertIn(fact_key("email", "info@oncae.gob.hn"), facts)
        self.assertIn(fact_key("phone", "+50422301234"), facts)
        self.assertIn(fact_key("institution", "hn:institution:oncae"), facts)

    def test_fiscal_year_is_not_money(self) -> None:
        facts = extract_facts("EJERCICIO FISCAL L 2024 — ONCAE")
        self.assertNotIn(fact_key("money", "HNL:2024"), facts)

    def test_invalid_dates_are_rejected(self) -> None:
        facts = extract_facts("ONCAE Circular 004-2026, 31 de febrero de 2026")
        self.assertNotIn(fact_key("date", "2026-02-31"), facts)

    def test_external_metadata_tokens_are_not_required(self) -> None:
        facts = extract_facts("ONCAE comunica una disposición general. Correo info@oncae.gob.hn")
        self.assertIn(fact_key("institution", "hn:institution:oncae"), facts)
        self.assertNotIn(fact_key("date", "2023-01-01"), facts)


class CandidateConsensusTests(unittest.TestCase):
    def _make_ocr_root(self, root: Path, texts: dict[str, str]) -> Path:
        ocr_root = root / "ocr"
        ocr_root.mkdir()
        manifest = {
            "schema": "data-science-pipeline/frozen-ocr-ensemble/1",
            "source_pdf_sha256": "a" * 64,
            "candidates": [{"name": name} for name in EXPECTED_CANDIDATES],
        }
        (ocr_root / "ocr-manifest.json").write_bytes(canonical_json_bytes(manifest))
        for name in EXPECTED_CANDIDATES:
            candidate = ocr_root / name
            candidate.mkdir()
            (candidate / "page_0001.txt").write_text(texts[name], encoding="utf-8")
        return ocr_root

    def test_two_of_three_consensus_accepts_fact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = "Circular ONCAE-004-2026, 14 de julio de 2026, ONCAE"
            ocr_root = self._make_ocr_root(
                root,
                {
                    EXPECTED_CANDIDATES[0]: common,
                    EXPECTED_CANDIDATES[1]: common,
                    EXPECTED_CANDIDATES[2]: "texto ilegible sin identificador",
                },
            )
            result = resolve(ocr_root, root / "out")
            values = {(row["fact_type"], row["value"]) for row in result["facts"]}
            self.assertIn(("circular_id", "ONCAE-004-2026"), values)
            circular = next(row for row in result["facts"] if row["fact_type"] == "circular_id")
            self.assertEqual(circular["support_count"], 2)

    def test_single_strategy_fact_is_abstained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ocr_root = self._make_ocr_root(
                root,
                {
                    EXPECTED_CANDIDATES[0]: "Circular ONCAE-004-2026",
                    EXPECTED_CANDIDATES[1]: "texto general",
                    EXPECTED_CANDIDATES[2]: "otro texto",
                },
            )
            result = resolve(ocr_root, root / "out")
            self.assertFalse(result["facts"])
            self.assertTrue(any(row["value"] == "ONCAE-004-2026" for row in result["abstentions"]))

    def test_resolver_replay_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = "Circular ONCAE-004-2026, 14 de julio de 2026, ONCAE"
            ocr_root = self._make_ocr_root(root, {name: common for name in EXPECTED_CANDIDATES})
            resolve(ocr_root, root / "a")
            resolve(ocr_root, root / "b")
            self.assertEqual((root / "a/candidate-facts.json").read_bytes(), (root / "b/candidate-facts.json").read_bytes())


class OracleTests(unittest.TestCase):
    def test_oracle_independently_extracts_body_facts(self) -> None:
        facts = extract_oracle_facts(
            "Circular ONCAE 004-2026\nTegucigalpa 14 de julio del 2026\nONCAE\ninfo@oncae.gob.hn\nTel: 2230-1234"
        )
        self.assertIn(fact_key("circular_id", "ONCAE-004-2026"), facts)
        self.assertIn(fact_key("date", "2026-07-14"), facts)
        self.assertIn(fact_key("institution", "hn:institution:oncae"), facts)

    def test_short_native_text_blocks_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native.txt"
            native.write_text("ONCAE", encoding="utf-8")
            result = build_oracle(native, "b" * 64, root / "oracle")
            self.assertEqual(result["verdict"], "BLOCKED_NO_NATIVE_ORACLE")

    def test_oracle_replay_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native.txt"
            native.write_text((CandidateExtractionTests.SAMPLE + "\n") * 3, encoding="utf-8")
            build_oracle(native, "b" * 64, root / "a")
            build_oracle(native, "b" * 64, root / "b")
            self.assertEqual((root / "a/oracle-facts.json").read_bytes(), (root / "b/oracle-facts.json").read_bytes())


class SourceBindingTests(unittest.TestCase):
    HTML = """
    <html><body>
      <h1>Circular ONCAE-004-2026</h1><time>Jul 14, 2026</time>
      <a href="/wp-content/uploads/2026/07/Circular-ONCAE-004-2026.pdf">Descarga</a>
    </body></html>
    """

    def test_discovers_one_allowlisted_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html = root / "landing.html"
            html.write_text(self.HTML, encoding="utf-8")
            result = discover(
                html,
                "https://oncae.gob.hn/2026/07/14/circular-oncae-004-2026/",
                "Circular ONCAE-004-2026",
                "2026-07-14",
                ("oncae.gob.hn", "www.oncae.gob.hn"),
                root / "binding.json",
            )
            self.assertEqual(result["pdf_url"], "https://oncae.gob.hn/wp-content/uploads/2026/07/Circular-ONCAE-004-2026.pdf")
            self.assertFalse(result["metadata_injected_as_document_facts"])

    def test_multiple_pdf_bindings_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html = root / "landing.html"
            html.write_text(self.HTML.replace("</body>", '<a href="/other.pdf">Descarga</a></body>'), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "authority gate failed"):
                discover(
                    html,
                    "https://oncae.gob.hn/2026/07/14/circular-oncae-004-2026/",
                    "Circular ONCAE-004-2026",
                    "2026-07-14",
                    ("oncae.gob.hn",),
                    root / "binding.json",
                )


class TransportSecurityTests(unittest.TestCase):
    def test_url_allowlist_and_https(self) -> None:
        validate_url("https://oncae.gob.hn/file.pdf", ("oncae.gob.hn",))
        with self.assertRaises(FetchValidationError):
            validate_url("http://oncae.gob.hn/file.pdf", ("oncae.gob.hn",))
        with self.assertRaises(FetchValidationError):
            validate_url("https://evil.example/file.pdf", ("oncae.gob.hn",))

    def test_dns_rejects_mixed_public_private_answers(self) -> None:
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]
        with patch("secure_fetch.socket.getaddrinfo", return_value=answers):
            with self.assertRaisesRegex(FetchValidationError, "non-public"):
                resolve_public_addresses("oncae.gob.hn")

    def test_dns_returns_sorted_public_addresses(self) -> None:
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]
        with patch("secure_fetch.socket.getaddrinfo", return_value=answers):
            self.assertEqual(resolve_public_addresses("oncae.gob.hn"), ("93.184.216.34", "93.184.216.35"))

    def test_pinned_connection_uses_validated_ip_and_original_sni(self) -> None:
        raw_socket = Mock()
        wrapped_socket = Mock()
        context = Mock()
        context.wrap_socket.return_value = wrapped_socket
        connection = PinnedHTTPSConnection(
            "oncae.gob.hn",
            pinned_addresses=("93.184.216.34",),
            context=context,
            timeout=7.0,
        )
        with patch("secure_fetch.socket.create_connection", return_value=raw_socket) as create:
            connection.connect()
        create.assert_called_once_with(("93.184.216.34", 443), 7.0, None)
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="oncae.gob.hn")
        self.assertIs(connection.sock, wrapped_socket)


class AdjudicationTests(unittest.TestCase):
    def _write_json(self, path: Path, value: dict) -> None:
        path.write_bytes(canonical_json_bytes(value))

    def _fixture(self, root: Path, *, extra_candidate: bool = False, oracle_verdict: str = "ORACLE_SEALED") -> dict[str, Path]:
        freeze = json.loads((Path(__file__).with_name("FREEZE.json")).read_text(encoding="utf-8"))
        paths = {name: root / name for name in ("freeze.json", "landing.json", "binding.json", "pdf.json", "candidate.json", "candidate.sha256", "oracle.json", "result.json")}
        self._write_json(paths["freeze.json"], freeze)
        landing_sha = "1" * 64
        pdf_sha = "2" * 64
        landing = {
            "verdict": "PASS",
            "requested_url": freeze["source_discovery"]["official_landing_page"],
            "final_url": freeze["source_discovery"]["official_landing_page"],
            "final_host": "oncae.gob.hn",
            "sha256": landing_sha,
        }
        binding = {
            "verdict": "PASS",
            "landing_sha256": landing_sha,
            "visible_title": freeze["source_discovery"]["visible_title"],
            "visible_publication_date": freeze["source_discovery"]["visible_publication_date"],
            "pdf_url": "https://oncae.gob.hn/file.pdf",
            "metadata_injected_as_document_facts": False,
            "checks": {"a": True, "b": True},
        }
        pdf = {
            "verdict": "PASS",
            "requested_url": binding["pdf_url"],
            "final_url": binding["pdf_url"],
            "final_host": "oncae.gob.hn",
            "sha256": pdf_sha,
            "bytes": 100000,
            "magic": "%PDF-",
        }
        facts = [
            {"fact_type": "circular_id", "value": "ONCAE-004-2026"},
            {"fact_type": "date", "value": "2026-07-14"},
            {"fact_type": "institution", "value": "hn:institution:oncae"},
        ]
        candidate_facts = list(facts)
        if extra_candidate:
            candidate_facts.append({"fact_type": "money", "value": "HNL:999"})
        candidate = {
            "schema": "data-science-pipeline/identity-aware-candidate/1",
            "verdict": "CANDIDATE_SEALED",
            "source_pdf_sha256": pdf_sha,
            "native_text_used": False,
            "minimum_support": 2,
            "facts": candidate_facts,
            "checks": {"a": True, "b": True},
        }
        oracle = {
            "schema": "data-science-pipeline/native-text-oracle/1",
            "verdict": oracle_verdict,
            "source_pdf_sha256": pdf_sha,
            "facts": facts if oracle_verdict == "ORACLE_SEALED" else [],
        }
        for name, value in (("landing.json", landing), ("binding.json", binding), ("pdf.json", pdf), ("candidate.json", candidate), ("oracle.json", oracle)):
            self._write_json(paths[name], value)
        digest = sha256_file(paths["candidate.json"])
        paths["candidate.sha256"].write_text(f"{digest}  candidate.json\n", encoding="utf-8")
        return paths

    def _run(self, paths: dict[str, Path]) -> dict:
        return adjudicate(
            paths["freeze.json"],
            paths["landing.json"],
            paths["binding.json"],
            paths["pdf.json"],
            paths["candidate.json"],
            paths["candidate.sha256"],
            paths["oracle.json"],
            paths["result.json"],
        )

    def test_passes_exact_high_recall_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(self._fixture(Path(directory)))
            self.assertEqual(result["verdict"], "PASS_EXTERNAL_RESOLUTION")
            self.assertEqual(result["metrics"]["precision"], 1.0)
            self.assertEqual(result["metrics"]["recall"], 1.0)

    def test_extra_candidate_fact_is_hallucination_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(self._fixture(Path(directory), extra_candidate=True))
            self.assertEqual(result["verdict"], "FAIL_HALLUCINATION")

    def test_missing_native_oracle_is_blocked_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(self._fixture(Path(directory), oracle_verdict="BLOCKED_NO_NATIVE_ORACLE"))
            self.assertEqual(result["verdict"], "BLOCKED_NO_NATIVE_ORACLE")

    def test_tampered_candidate_receipt_fails_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._fixture(Path(directory))
            paths["candidate.sha256"].write_text(f"{'0' * 64}  candidate.json\n", encoding="utf-8")
            result = self._run(paths)
            self.assertEqual(result["verdict"], "FAIL_CANDIDATE_INTEGRITY")

    def test_adjudication_replay_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._fixture(root)
            self._run(paths)
            first = paths["result.json"].read_bytes()
            paths["result.json"] = root / "result-b.json"
            self._run(paths)
            self.assertEqual(first, paths["result.json"].read_bytes())


if __name__ == "__main__":
    unittest.main()
