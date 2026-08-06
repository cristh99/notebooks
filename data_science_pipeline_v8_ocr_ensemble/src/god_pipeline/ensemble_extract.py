from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse

from .extract import ExtractDocument, _quarantine_artifact, _require_tools
from .models import (
    Artifact,
    ArtifactState,
    QualityGate,
    Stage,
    StageContract,
    StageOutput,
    utc_now,
)

CANDIDATES: tuple[dict[str, Any], ...] = (
    {"name": "balanced_200_psm6", "dpi": 200, "psm": 6},
    {"name": "sparse_300_psm11", "dpi": 300, "psm": 11},
    {"name": "auto_300_psm3", "dpi": 300, "psm": 3},
)


def _path_from_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise RuntimeError(f"candidate artifact is not local: {uri}")
    return Path(unquote(parsed.path))


def deterministic_tar_gz(source_dir: Path, target: Path) -> str:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source_dir)
            info = archive.gettarinfo(str(path), arcname=str(relative))
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            with path.open("rb") as handle:
                archive.addfile(info, handle)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(buffer.getvalue())
    return hashlib.sha256(target.read_bytes()).hexdigest()


def candidate_word_count(candidate_dir: Path) -> int:
    manifests = list(candidate_dir.rglob("document.manifest.json"))
    if len(manifests) != 1:
        return 0
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    return sum(int(page.get("word_count", 0)) for page in payload.get("pages", []))


def candidate_score(metrics: Mapping[str, Any], word_count: int) -> float:
    return (
        float(metrics.get("mean_confidence", 0.0))
        + 20.0 * float(metrics.get("native_token_recall", 0.0))
        + max(word_count, 0) / (1.0 + max(word_count, 0))
    )


def _mapped_artifact(artifact: Artifact, source_root: Path, target_root: Path, candidate_name: str) -> Artifact:
    source = _path_from_uri(artifact.uri)
    relative = source.relative_to(source_root)
    target = target_root / relative
    data = target.read_bytes()
    return replace(
        artifact,
        uri=target.resolve().as_uri(),
        sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
        created_at=utc_now(),
        metadata={**dict(artifact.metadata), "ensemble_candidate": candidate_name},
    )


class EnsembleExtractDocument:
    contract = StageContract(
        stage=Stage.EXTRACT,
        handler_version="ensemble-extract-document/1",
        allowed_input_stages=(Stage.PRESERVE_RAW,),
        allowed_input_states=(ArtifactState.RAW,),
        allowed_output_states=(ArtifactState.ACCEPTED, ArtifactState.QUARANTINED),
        gate=QualityGate(
            min_acceptance_rate=1.0,
            max_quarantine_rate=0.0,
            max_rejection_rate=0.0,
            require_nonempty_output=True,
            required_metrics=(
                "documents",
                "candidate_count",
                "eligible_candidates",
                "pages_rasterized",
                "pages_ocr",
                "mean_confidence",
                "native_token_recall",
                "required_tokens_found",
                "selected_score",
                "cost_usd",
            ),
        ),
        description="Run multiple OCR strategies and deterministically select the strongest eligible evidence package.",
    )

    def __init__(self, *, runner=None, verify_tools: bool = True) -> None:
        self.runner = runner
        self.verify_tools = verify_tools

    def execute(self, artifacts: Sequence[Artifact], *, workspace: Path, config: Mapping[str, Any]) -> StageOutput:
        if self.verify_tools:
            _require_tools(("pdfinfo", "pdftoppm", "pdftotext", "tesseract"))
        base_config = {
            "max_pages": int(config.get("max_pages", 3)),
            "languages": str(config.get("languages", "spa+eng")),
            "min_mean_confidence": float(config.get("min_mean_confidence", 55.0)),
            "min_native_token_recall": float(config.get("min_native_token_recall", 0.55)),
            "required_tokens": list(config.get("required_tokens", ["PACC"])),
        }
        if not base_config["required_tokens"]:
            raise ValueError("required_tokens must not be empty")

        accepted: list[Artifact] = []
        quarantined: list[Artifact] = []
        dispositions: dict[str, ArtifactState] = {}
        selected_metrics: list[Mapping[str, Any]] = []
        selected_scores: list[float] = []
        eligible_total = 0

        for parent in artifacts:
            parent_candidate_root = workspace / "_ensemble_candidates" / parent.sha256
            archive_root = workspace / "ensemble_evidence" / parent.sha256
            canonical_root = workspace / "extract" / parent.sha256
            shutil.rmtree(parent_candidate_root, ignore_errors=True)
            shutil.rmtree(canonical_root, ignore_errors=True)
            summaries: list[dict[str, Any]] = []
            eligible: list[tuple[float, str, StageOutput, Path, int]] = []

            for spec in CANDIDATES:
                name = str(spec["name"])
                candidate_workspace = parent_candidate_root / name
                handler = ExtractDocument(runner=self.runner, verify_tools=False) if self.runner else ExtractDocument(verify_tools=False)
                candidate_config = {
                    **base_config,
                    "dpi": int(spec["dpi"]),
                    "psm": int(spec["psm"]),
                }
                output = handler.execute((parent,), workspace=candidate_workspace, config=candidate_config)
                candidate_dir = candidate_workspace / "extract" / parent.sha256
                word_count = candidate_word_count(candidate_dir)
                score = candidate_score(output.metrics, word_count)
                disposition = output.input_dispositions.get(parent.artifact_id)
                is_eligible = disposition == ArtifactState.ACCEPTED and not output.quarantined
                if is_eligible:
                    eligible.append((score, name, output, candidate_dir, word_count))
                archive_path = archive_root / f"{name}.tar.gz"
                archive_hash = deterministic_tar_gz(candidate_dir, archive_path) if candidate_dir.exists() else None
                summaries.append({
                    "name": name,
                    "dpi": spec["dpi"],
                    "psm": spec["psm"],
                    "eligible": is_eligible,
                    "score": score,
                    "word_count": word_count,
                    "metrics": dict(output.metrics),
                    "quarantine_reasons": [item.reason_detail for item in output.quarantined],
                    "archive_path": str(archive_path.relative_to(workspace)) if archive_hash else None,
                    "archive_sha256": archive_hash,
                })

            eligible_total += len(eligible)
            if not eligible:
                detail = "no OCR candidate satisfied frozen quality and semantic gates"
                metrics = {
                    "candidate_count": len(CANDIDATES),
                    "eligible_candidates": 0,
                    "candidates": summaries,
                }
                quarantined.append(
                    _quarantine_artifact(
                        path=workspace / "extract" / parent.sha256 / "quarantine.json",
                        parent=parent,
                        detail=detail,
                        metrics=metrics,
                    )
                )
                dispositions[parent.artifact_id] = ArtifactState.QUARANTINED
                continue

            score, selected_name, selected_output, selected_candidate_dir, selected_word_count = sorted(
                eligible, key=lambda item: (-item[0], item[1])
            )[0]
            canonical_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(selected_candidate_dir, canonical_root)
            for artifact in selected_output.accepted:
                accepted.append(_mapped_artifact(artifact, selected_candidate_dir, canonical_root, selected_name))

            selection = {
                "schema": "data-science-pipeline/ocr-ensemble-selection/1",
                "parent_artifact_id": parent.artifact_id,
                "parent_sha256": parent.sha256,
                "candidate_count": len(CANDIDATES),
                "eligible_candidates": len(eligible),
                "selected_candidate": selected_name,
                "selected_score": score,
                "selected_word_count": selected_word_count,
                "selection_rule": "highest mean_confidence + 20*native_token_recall + word_count/(1+word_count); lexical name tie-break",
                "native_text_non_authoritative": True,
                "candidates": summaries,
                "cost_usd": 0.0,
            }
            selection_path = canonical_root / "ensemble.selection.json"
            selection_path.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            data = selection_path.read_bytes()
            accepted.append(
                Artifact(
                    artifact_id=f"{parent.artifact_id}:ensemble:selection",
                    stage=Stage.EXTRACT,
                    state=ArtifactState.ACCEPTED,
                    uri=selection_path.resolve().as_uri(),
                    sha256=hashlib.sha256(data).hexdigest(),
                    schema_version="ocr-ensemble-selection/1",
                    source_id=parent.source_id,
                    observed_at=parent.observed_at,
                    created_at=utc_now(),
                    media_type="application/json",
                    byte_count=len(data),
                    parent_ids=(parent.artifact_id,),
                    metadata={"selected_candidate": selected_name, "candidate_count": len(CANDIDATES)},
                )
            )
            dispositions[parent.artifact_id] = ArtifactState.ACCEPTED
            selected_metrics.append(selected_output.metrics)
            selected_scores.append(score)
            shutil.rmtree(parent_candidate_root, ignore_errors=True)

        def average(name: str) -> float:
            return sum(float(item.get(name, 0.0)) for item in selected_metrics) / len(selected_metrics) if selected_metrics else 0.0

        return StageOutput(
            input_dispositions=dispositions,
            accepted=tuple(accepted),
            quarantined=tuple(quarantined),
            metrics={
                "documents": len(artifacts),
                "candidate_count": len(artifacts) * len(CANDIDATES),
                "eligible_candidates": eligible_total,
                "pages_rasterized": sum(int(item.get("pages_rasterized", 0)) for item in selected_metrics),
                "pages_ocr": sum(int(item.get("pages_ocr", 0)) for item in selected_metrics),
                "mean_confidence": average("mean_confidence"),
                "native_token_recall": average("native_token_recall"),
                "required_tokens_found": sum(int(item.get("required_tokens_found", 0)) for item in selected_metrics),
                "selected_score": sum(selected_scores) / len(selected_scores) if selected_scores else 0.0,
                "cost_usd": 0.0,
            },
            notes=("Every OCR strategy was hash-summarized; only the deterministic winner populated canonical outputs.",),
        )
