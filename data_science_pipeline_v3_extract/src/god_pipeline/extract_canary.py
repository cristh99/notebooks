from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from .extract import ExtractDocument
from .ledger import AppendOnlyLedger
from .models import Artifact, ArtifactState, Stage, sha256_json
from .orchestrator import Orchestrator


def artifact_from_dict(value: dict[str, object]) -> Artifact:
    return Artifact(
        artifact_id=str(value["artifact_id"]),
        stage=Stage(str(value["stage"])),
        state=ArtifactState(str(value["state"])),
        uri=str(value["uri"]),
        sha256=str(value["sha256"]),
        schema_version=str(value["schema_version"]),
        source_id=str(value["source_id"]),
        observed_at=str(value["observed_at"]),
        created_at=str(value["created_at"]),
        media_type=str(value.get("media_type") or "application/octet-stream"),
        byte_count=int(value["byte_count"]) if value.get("byte_count") is not None else None,
        parent_ids=tuple(str(item) for item in value.get("parent_ids", [])),
        metadata=dict(value.get("metadata") or {}),
    )


def select_raw_pdf(acquisition_manifest: Path) -> Artifact:
    payload = json.loads(acquisition_manifest.read_text(encoding="utf-8"))
    candidates = [
        artifact_from_dict(item)
        for item in payload.get("artifacts", [])
        if item.get("stage") == Stage.PRESERVE_RAW.value
        and item.get("state") == ArtifactState.RAW.value
        and item.get("media_type") == "application/pdf"
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one preserved raw PDF, got {len(candidates)}")
    path = Path(unquote(urlparse(candidates[0].uri).path))
    if not path.is_file() or path.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError("preserved raw artifact is missing or not a PDF")
    return candidates[0]


def run(root: Path, acquisition_manifest: Path, config_path: Path) -> dict[str, object]:
    raw = select_raw_pdf(acquisition_manifest)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    ledger = AppendOnlyLedger(root / "evidence/ledger.jsonl")
    orchestrator = Orchestrator(
        pipeline_version="data-science-pipeline/3-extract",
        workspace=root / "workspace",
        ledger=ledger,
    )
    manifest = orchestrator.run(
        run_id="oncae-direct-contracting-guide-extract-v1",
        source_snapshot=sha256_json({"raw_artifact": raw.to_dict(), "config": config}),
        initial_artifacts=(raw,),
        handlers=(ExtractDocument(),),
        configs={Stage.EXTRACT: config},
        manifest_path=root / "evidence/manifest.json",
    )
    return manifest.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--acquisition-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.acquisition_manifest, args.config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
