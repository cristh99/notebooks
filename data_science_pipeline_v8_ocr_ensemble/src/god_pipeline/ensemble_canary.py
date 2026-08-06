from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ensemble_extract import EnsembleExtractDocument
from .extract_canary import select_raw_pdf
from .ledger import AppendOnlyLedger
from .models import Stage, sha256_json
from .orchestrator import Orchestrator


def run(root: Path, acquisition_manifest: Path, config_path: Path) -> dict[str, object]:
    raw = select_raw_pdf(acquisition_manifest)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    orchestrator = Orchestrator(
        pipeline_version="data-science-pipeline/8-ocr-ensemble",
        workspace=root / "workspace",
        ledger=AppendOnlyLedger(root / "evidence/ledger.jsonl"),
    )
    manifest = orchestrator.run(
        run_id="fresh-conceptos-pacc-ocr-ensemble-v1",
        source_snapshot=sha256_json({"raw_artifact": raw.to_dict(), "config": config}),
        initial_artifacts=(raw,),
        handlers=(EnsembleExtractDocument(),),
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
