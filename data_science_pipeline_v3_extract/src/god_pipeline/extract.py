from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote, urlparse

from .models import (
    Artifact,
    ArtifactState,
    ContractViolation,
    QualityGate,
    ReasonCode,
    Stage,
    StageContract,
    StageOutput,
    sha256_bytes,
    utc_now,
)

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[bytes]]


@dataclass(frozen=True)
class ExtractConfig:
    max_pages: int = 3
    dpi: int = 200
    languages: str = "spa+eng"
    psm: int = 6
    min_mean_confidence: float = 55.0
    min_native_token_recall: float = 0.55
    required_tokens: tuple[str, ...] = (
        "ONCAE",
        "CONTRATACION",
        "DIRECTA",
        "NOVIEMBRE",
        "2024",
    )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExtractConfig":
        allowed = {
            "max_pages",
            "dpi",
            "languages",
            "psm",
            "min_mean_confidence",
            "min_native_token_recall",
            "required_tokens",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ContractViolation(f"unknown extract config fields: {unknown}")
        config = cls(
            max_pages=int(value.get("max_pages", 3)),
            dpi=int(value.get("dpi", 200)),
            languages=str(value.get("languages", "spa+eng")),
            psm=int(value.get("psm", 6)),
            min_mean_confidence=float(value.get("min_mean_confidence", 55.0)),
            min_native_token_recall=float(value.get("min_native_token_recall", 0.55)),
            required_tokens=tuple(str(item) for item in value.get("required_tokens", cls.required_tokens)),
        )
        if not 1 <= config.max_pages <= 50:
            raise ContractViolation("max_pages must be between 1 and 50")
        if not 100 <= config.dpi <= 600:
            raise ContractViolation("dpi must be between 100 and 600")
        if not 3 <= config.psm <= 13:
            raise ContractViolation("psm must be between 3 and 13")
        if not 0 <= config.min_mean_confidence <= 100:
            raise ContractViolation("min_mean_confidence must be between 0 and 100")
        if not 0 <= config.min_native_token_recall <= 1:
            raise ContractViolation("min_native_token_recall must be between 0 and 1")
        if not config.languages.strip() or not config.required_tokens:
            raise ContractViolation("languages and required_tokens are required")
        return config


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(list(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _require_tools(names: Sequence[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise ContractViolation(f"required OCR tools missing: {missing}")


def _file_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ContractViolation("extract only accepts local file:// raw artifacts")
    path = Path(unquote(parsed.path))
    if not path.is_file():
        raise ContractViolation(f"raw artifact path does not exist: {path}")
    return path


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", ascii_text.upper()).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in _normalized_text(value).split() if len(token) >= 3 or token.isdigit()}


def token_recall(reference: str, candidate: str) -> float:
    expected = _tokens(reference)
    if not expected:
        return 1.0
    return len(expected & _tokens(candidate)) / len(expected)


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ContractViolation("renderer did not produce a valid PNG")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise ContractViolation("PNG dimensions are invalid")
    return width, height


def _parse_pdf_pages(output: bytes) -> int:
    text = output.decode("utf-8", errors="replace")
    match = re.search(r"^Pages:\s*(\d+)\s*$", text, re.MULTILINE)
    if not match:
        raise ContractViolation("pdfinfo did not report page count")
    pages = int(match.group(1))
    if pages <= 0:
        raise ContractViolation("PDF has no pages")
    return pages


def parse_tsv(tsv_text: str) -> tuple[list[dict[str, Any]], float]:
    lines = tsv_text.splitlines()
    if not lines:
        return [], 0.0
    header = lines[0].split("\t")
    required = {"left", "top", "width", "height", "conf", "text"}
    if not required.issubset(header):
        raise ContractViolation("Tesseract TSV header is incomplete")
    rows: list[dict[str, Any]] = []
    confidences: list[float] = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        record = dict(zip(header, cells))
        text = record.get("text", "").strip()
        try:
            confidence = float(record.get("conf", "-1"))
        except ValueError:
            confidence = -1.0
        if not text or confidence < 0:
            continue
        word = {
            "text": text,
            "confidence": confidence,
            "left": int(record["left"]),
            "top": int(record["top"]),
            "width": int(record["width"]),
            "height": int(record["height"]),
            "block_num": int(record.get("block_num") or 0),
            "par_num": int(record.get("par_num") or 0),
            "line_num": int(record.get("line_num") or 0),
            "word_num": int(record.get("word_num") or 0),
        }
        rows.append(word)
        confidences.append(confidence)
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return rows, mean


def _command_or_raise(runner: CommandRunner, command: Sequence[str], label: str) -> subprocess.CompletedProcess[bytes]:
    result = runner(command)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-1000:]
        raise ContractViolation(f"{label} failed with exit {result.returncode}: {detail}")
    return result


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _artifact_from_path(*, path: Path, artifact_id: str, parent: Artifact, media_type: str, schema_version: str, metadata: Mapping[str, Any]) -> Artifact:
    return Artifact.from_path(
        path=path,
        artifact_id=artifact_id,
        stage=Stage.EXTRACT,
        state=ArtifactState.ACCEPTED,
        schema_version=schema_version,
        source_id=parent.source_id,
        observed_at=parent.observed_at,
        media_type=media_type,
        parent_ids=(parent.artifact_id,),
        metadata=metadata,
    )


def _quarantine_artifact(*, path: Path, parent: Artifact, detail: str, metrics: Mapping[str, Any]) -> Artifact:
    payload = {
        "schema": "data-science-pipeline/extract-quarantine/1",
        "parent_artifact_id": parent.artifact_id,
        "parent_sha256": parent.sha256,
        "reason_code": ReasonCode.QUALITY_GATE.value,
        "reason_detail": detail,
        "metrics": dict(metrics),
        "recorded_at": utc_now(),
    }
    _write_json(path, payload)
    data = path.read_bytes()
    return Artifact(
        artifact_id=f"{parent.artifact_id}:extract:quarantine",
        stage=Stage.EXTRACT,
        state=ArtifactState.QUARANTINED,
        uri=path.resolve().as_uri(),
        sha256=sha256_bytes(data),
        schema_version="extract-quarantine/1",
        source_id=parent.source_id,
        observed_at=parent.observed_at,
        created_at=utc_now(),
        media_type="application/json",
        byte_count=len(data),
        parent_ids=(parent.artifact_id,),
        reason_code=ReasonCode.QUALITY_GATE,
        reason_detail=detail,
        metadata={"metrics": dict(metrics)},
    )


class ExtractDocument:
    contract = StageContract(
        stage=Stage.EXTRACT,
        handler_version="extract-document/1",
        allowed_input_stages=(Stage.PRESERVE_RAW,),
        allowed_input_states=(ArtifactState.RAW,),
        allowed_output_states=(ArtifactState.ACCEPTED, ArtifactState.QUARANTINED),
        gate=QualityGate(
            min_acceptance_rate=1.0,
            max_quarantine_rate=0.0,
            max_rejection_rate=0.0,
            require_nonempty_output=True,
            required_metrics=("documents", "pages_rasterized", "pages_ocr", "mean_confidence", "native_token_recall", "required_tokens_found", "cost_usd"),
        ),
        description="Rasterize PDFs and run mandatory OCR with page-level evidence.",
    )

    def __init__(self, *, runner: CommandRunner = _run, verify_tools: bool = True) -> None:
        self.runner = runner
        self.verify_tools = verify_tools

    def execute(self, artifacts: Sequence[Artifact], *, workspace: Path, config: Mapping[str, Any]) -> StageOutput:
        cfg = ExtractConfig.from_mapping(config)
        if self.verify_tools:
            _require_tools(("pdfinfo", "pdftoppm", "pdftotext", "tesseract"))

        accepted: list[Artifact] = []
        quarantined: list[Artifact] = []
        dispositions: dict[str, ArtifactState] = {}
        aggregate_confidences: list[float] = []
        aggregate_recalls: list[float] = []
        pages_rasterized = 0
        pages_ocr = 0
        required_found_total = 0

        for parent in artifacts:
            document_dir = workspace / "extract" / parent.sha256
            document_dir.mkdir(parents=True, exist_ok=True)
            metrics: dict[str, Any] = {"pages_rasterized": 0, "pages_ocr": 0, "mean_confidence": 0.0, "native_token_recall": 0.0, "required_tokens_found": 0}
            try:
                pdf_path = _file_uri_to_path(parent.uri)
                if pdf_path.read_bytes()[:5] != b"%PDF-":
                    raise ContractViolation("raw artifact is not a PDF by magic bytes")
                pdfinfo = _command_or_raise(self.runner, ("pdfinfo", str(pdf_path)), "pdfinfo")
                total_pages = _parse_pdf_pages(pdfinfo.stdout)
                page_limit = min(total_pages, cfg.max_pages)
                native_texts: list[str] = []
                ocr_texts: list[str] = []
                page_manifests: list[dict[str, Any]] = []
                page_artifacts: list[Artifact] = []

                for page_number in range(1, page_limit + 1):
                    page_prefix = document_dir / f"page_{page_number:04d}"
                    _command_or_raise(self.runner, ("pdftoppm", "-f", str(page_number), "-l", str(page_number), "-r", str(cfg.dpi), "-png", "-singlefile", str(pdf_path), str(page_prefix)), f"pdftoppm page {page_number}")
                    image_path = page_prefix.with_suffix(".png")
                    image_data = image_path.read_bytes()
                    width, height = _png_dimensions(image_data)
                    metrics["pages_rasterized"] += 1

                    text_result = _command_or_raise(self.runner, ("tesseract", str(image_path), "stdout", "-l", cfg.languages, "--psm", str(cfg.psm)), f"tesseract text page {page_number}")
                    tsv_result = _command_or_raise(self.runner, ("tesseract", str(image_path), "stdout", "-l", cfg.languages, "--psm", str(cfg.psm), "tsv"), f"tesseract TSV page {page_number}")
                    native_result = _command_or_raise(self.runner, ("pdftotext", "-f", str(page_number), "-l", str(page_number), "-layout", str(pdf_path), "-"), f"pdftotext page {page_number}")
                    ocr_text = text_result.stdout.decode("utf-8", errors="replace").strip()
                    native_text = native_result.stdout.decode("utf-8", errors="replace").strip()
                    words, mean_confidence = parse_tsv(tsv_result.stdout.decode("utf-8", errors="replace"))
                    recall = token_recall(native_text, ocr_text)
                    if not ocr_text or not words:
                        raise ContractViolation(f"page {page_number} produced empty OCR")
                    aggregate_confidences.append(mean_confidence)
                    aggregate_recalls.append(recall)
                    ocr_texts.append(ocr_text)
                    native_texts.append(native_text)
                    metrics["pages_ocr"] += 1

                    text_path = page_prefix.with_suffix(".txt")
                    tsv_path = page_prefix.with_suffix(".tsv")
                    layout_path = page_prefix.with_suffix(".layout.json")
                    native_path = page_prefix.with_suffix(".native.txt")
                    text_path.write_text(ocr_text + "\n", encoding="utf-8")
                    tsv_path.write_bytes(tsv_result.stdout)
                    native_path.write_text(native_text + ("\n" if native_text else ""), encoding="utf-8")
                    layout = {"schema": "data-science-pipeline/ocr-page-layout/1", "page_number": page_number, "dpi": cfg.dpi, "width": width, "height": height, "languages": cfg.languages, "psm": cfg.psm, "mean_confidence": mean_confidence, "native_token_recall": recall, "word_count": len(words), "words": words}
                    _write_json(layout_path, layout)
                    common = {"page_number": page_number, "document_sha256": parent.sha256}
                    page_artifacts.extend((
                        _artifact_from_path(path=image_path, artifact_id=f"{parent.artifact_id}:page:{page_number}:image", parent=parent, media_type="image/png", schema_version="ocr-raster/1", metadata={**common, "dpi": cfg.dpi, "width": width, "height": height}),
                        _artifact_from_path(path=text_path, artifact_id=f"{parent.artifact_id}:page:{page_number}:text", parent=parent, media_type="text/plain", schema_version="ocr-text/1", metadata={**common, "mean_confidence": mean_confidence, "native_token_recall": recall}),
                        _artifact_from_path(path=tsv_path, artifact_id=f"{parent.artifact_id}:page:{page_number}:tsv", parent=parent, media_type="text/tab-separated-values", schema_version="ocr-tsv/1", metadata={**common, "word_count": len(words)}),
                        _artifact_from_path(path=layout_path, artifact_id=f"{parent.artifact_id}:page:{page_number}:layout", parent=parent, media_type="application/json", schema_version="ocr-layout/1", metadata=common),
                        _artifact_from_path(path=native_path, artifact_id=f"{parent.artifact_id}:page:{page_number}:native-control", parent=parent, media_type="text/plain", schema_version="native-text-control/1", metadata={**common, "non_authoritative": True}),
                    ))
                    page_manifests.append({"page_number": page_number, "image_sha256": sha256_bytes(image_data), "ocr_text_sha256": sha256_bytes(text_path.read_bytes()), "tsv_sha256": sha256_bytes(tsv_path.read_bytes()), "layout_sha256": sha256_bytes(layout_path.read_bytes()), "native_text_sha256": sha256_bytes(native_path.read_bytes()), "mean_confidence": mean_confidence, "native_token_recall": recall, "word_count": len(words)})

                combined_ocr = "\n".join(ocr_texts)
                combined_native = "\n".join(native_texts)
                normalized_ocr = _normalized_text(combined_ocr)
                required = [_normalized_text(token) for token in cfg.required_tokens]
                found = [token for token in required if token and token in normalized_ocr]
                mean_confidence = sum(item["mean_confidence"] for item in page_manifests) / len(page_manifests)
                native_recall = token_recall(combined_native, combined_ocr)
                metrics.update({"mean_confidence": mean_confidence, "native_token_recall": native_recall, "required_tokens_found": len(found)})
                failures: list[str] = []
                if mean_confidence < cfg.min_mean_confidence:
                    failures.append(f"mean_confidence={mean_confidence:.3f} < {cfg.min_mean_confidence:.3f}")
                if native_recall < cfg.min_native_token_recall:
                    failures.append(f"native_token_recall={native_recall:.6f} < {cfg.min_native_token_recall:.6f}")
                missing = sorted(set(required) - set(found))
                if missing:
                    failures.append(f"required tokens missing: {missing}")
                if metrics["pages_ocr"] != page_limit:
                    failures.append("not every declared page was OCRed")
                if failures:
                    raise ContractViolation("; ".join(failures))

                combined_path = document_dir / "document.ocr.txt"
                combined_path.write_text(combined_ocr + "\n", encoding="utf-8")
                manifest_path = document_dir / "document.manifest.json"
                _write_json(manifest_path, {"schema": "data-science-pipeline/ocr-document-manifest/1", "source_artifact_id": parent.artifact_id, "source_sha256": parent.sha256, "source_bytes": parent.byte_count, "total_pdf_pages": total_pages, "processed_pages": page_limit, "page_limit_declared": cfg.max_pages, "partial_document": page_limit < total_pages, "rasterization_mandatory": True, "native_text_non_authoritative": True, "renderer": "pdftoppm", "ocr_engine": "tesseract", "languages": cfg.languages, "psm": cfg.psm, "dpi": cfg.dpi, "mean_confidence": mean_confidence, "native_token_recall": native_recall, "required_tokens": required, "required_tokens_found": found, "cost_usd": 0.0, "pages": page_manifests})
                accepted.extend([*page_artifacts, _artifact_from_path(path=combined_path, artifact_id=f"{parent.artifact_id}:document:text", parent=parent, media_type="text/plain", schema_version="ocr-document-text/1", metadata={"processed_pages": page_limit, "partial_document": page_limit < total_pages}), _artifact_from_path(path=manifest_path, artifact_id=f"{parent.artifact_id}:document:manifest", parent=parent, media_type="application/json", schema_version="ocr-document-manifest/1", metadata={"processed_pages": page_limit, "total_pdf_pages": total_pages, "partial_document": page_limit < total_pages})])
                dispositions[parent.artifact_id] = ArtifactState.ACCEPTED
            except Exception as exc:
                quarantined.append(_quarantine_artifact(path=document_dir / "quarantine.json", parent=parent, detail=str(exc), metrics=metrics))
                dispositions[parent.artifact_id] = ArtifactState.QUARANTINED

            pages_rasterized += int(metrics["pages_rasterized"])
            pages_ocr += int(metrics["pages_ocr"])
            required_found_total += int(metrics["required_tokens_found"])

        return StageOutput(
            input_dispositions=dispositions,
            accepted=tuple(accepted),
            quarantined=tuple(quarantined),
            metrics={"documents": len(artifacts), "pages_rasterized": pages_rasterized, "pages_ocr": pages_ocr, "mean_confidence": sum(aggregate_confidences) / len(aggregate_confidences) if aggregate_confidences else 0.0, "native_token_recall": sum(aggregate_recalls) / len(aggregate_recalls) if aggregate_recalls else 0.0, "required_tokens_found": required_found_total, "cost_usd": 0.0},
            notes=("Every processed PDF page was rasterized before OCR.",),
        )
