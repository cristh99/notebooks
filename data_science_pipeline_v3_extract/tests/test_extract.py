from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from god_pipeline.extract import (
    ExtractConfig,
    ExtractDocument,
    _normalized_text,
    _parse_pdf_pages,
    _png_dimensions,
    parse_tsv,
    token_recall,
)
from god_pipeline.models import Artifact, ArtifactState, ContractViolation, Stage


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + b"\x00\x00\x00d\x00\x00\x00\xc8" + b"rest"
TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t90.5\tONCAE\n"
    "5\t1\t1\t1\t1\t2\t50\t20\t60\t40\t80.5\tDIRECTA\n"
)


class FakeRunner:
    def __init__(self, *, low_confidence: bool = False):
        self.commands = []
        self.low_confidence = low_confidence

    def __call__(self, command):
        self.commands.append(tuple(command))
        name = command[0]
        if name == "pdfinfo":
            return subprocess.CompletedProcess(command, 0, b"Pages:          3\n", b"")
        if name == "pdftoppm":
            prefix = Path(command[-1])
            prefix.with_suffix(".png").write_bytes(PNG)
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if name == "pdftotext":
            return subprocess.CompletedProcess(command, 0, b"ONCAE CONTRATACION DIRECTA NOVIEMBRE 2024\n", b"")
        if name == "tesseract" and command[-1] == "tsv":
            tsv = TSV.replace("90.5", "10.0").replace("80.5", "10.0") if self.low_confidence else TSV
            return subprocess.CompletedProcess(command, 0, tsv.encode(), b"")
        if name == "tesseract":
            return subprocess.CompletedProcess(command, 0, b"ONCAE CONTRATACION DIRECTA NOVIEMBRE 2024\n", b"")
        raise AssertionError(command)


def raw_artifact(path: Path) -> Artifact:
    return Artifact.from_path(
        path=path,
        artifact_id="oncae:guide:raw",
        stage=Stage.PRESERVE_RAW,
        state=ArtifactState.RAW,
        schema_version="raw/1",
        source_id="oncae",
        observed_at="2026-08-05T00:00:00Z",
        media_type="application/pdf",
    )


class ExtractUnitTests(unittest.TestCase):
    def test_config_rejects_unknown_field(self):
        with self.assertRaises(ContractViolation):
            ExtractConfig.from_mapping({"unknown": 1})

    def test_config_bounds(self):
        with self.assertRaises(ContractViolation):
            ExtractConfig.from_mapping({"dpi": 50})

    def test_text_normalization_removes_accents(self):
        self.assertEqual(_normalized_text("Contratación directa"), "CONTRATACION DIRECTA")

    def test_token_recall(self):
        self.assertEqual(token_recall("ONCAE contratación directa", "ONCAE DIRECTA"), 2 / 3)

    def test_parse_pdf_pages(self):
        self.assertEqual(_parse_pdf_pages(b"Title: x\nPages: 27\n"), 27)

    def test_png_dimensions(self):
        self.assertEqual(_png_dimensions(PNG), (100, 200))

    def test_parse_tsv_mean_and_boxes(self):
        rows, mean = parse_tsv(TSV)
        self.assertEqual(len(rows), 2)
        self.assertEqual(mean, 85.5)
        self.assertEqual(rows[0]["left"], 10)

    def test_success_rasterizes_every_declared_page_and_emits_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "guide.pdf"
            pdf.write_bytes(b"%PDF-fake")
            runner = FakeRunner()
            output = ExtractDocument(runner=runner, verify_tools=False).execute(
                (raw_artifact(pdf),),
                workspace=root / "workspace",
                config={"max_pages": 3, "min_mean_confidence": 55, "min_native_token_recall": 0.55},
            )
            self.assertEqual(output.input_dispositions["oncae:guide:raw"], ArtifactState.ACCEPTED)
            self.assertFalse(output.quarantined)
            self.assertEqual(output.metrics["pages_rasterized"], 3)
            self.assertEqual(output.metrics["pages_ocr"], 3)
            self.assertEqual(len([cmd for cmd in runner.commands if cmd[0] == "pdftoppm"]), 3)
            manifests = [item for item in output.accepted if item.schema_version == "ocr-document-manifest/1"]
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(Path(manifests[0].uri.removeprefix("file://")).read_text())
            self.assertTrue(manifest["rasterization_mandatory"])
            self.assertTrue(manifest["native_text_non_authoritative"])

    def test_low_confidence_is_materially_quarantined(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "guide.pdf"
            pdf.write_bytes(b"%PDF-fake")
            output = ExtractDocument(runner=FakeRunner(low_confidence=True), verify_tools=False).execute(
                (raw_artifact(pdf),),
                workspace=root / "workspace",
                config={"max_pages": 1, "min_mean_confidence": 55},
            )
            self.assertEqual(output.input_dispositions["oncae:guide:raw"], ArtifactState.QUARANTINED)
            self.assertEqual(len(output.quarantined), 1)
            self.assertTrue(Path(output.quarantined[0].uri.removeprefix("file://")).is_file())

    def test_non_pdf_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "not.pdf"
            path.write_bytes(b"not a pdf")
            output = ExtractDocument(runner=FakeRunner(), verify_tools=False).execute(
                (raw_artifact(path),), workspace=root / "workspace", config={"max_pages": 1}
            )
            self.assertEqual(len(output.quarantined), 1)
            self.assertIn("not a PDF", output.quarantined[0].reason_detail)


if __name__ == "__main__":
    unittest.main()
