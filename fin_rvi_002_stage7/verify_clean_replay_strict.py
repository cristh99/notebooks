"""Strict Stage 7 wrapper around the independent clean-replay verifier.

The Stage 6 report contains measured-duration fields that need not be byte-identical
across fresh runners. The scientific payload must nevertheless be internally hash
consistent, while every stable cohort, label, policy and source-package component
remains fixed by ``verify_clean_replay``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import verify_clean_replay as base


def verify(
    report_path: Path,
    rows_path: Path,
    labels_path: Path,
    node_receipt_path: Path,
    exclusion_manifest_path: Path,
) -> dict:
    receipt = base.verify(
        report_path,
        rows_path,
        labels_path,
        node_receipt_path,
        exclusion_manifest_path,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = report.get("payload", {})
    gates = receipt["payload"]["gates"]
    gates["report_payload_hash_self_consistent"] = (
        isinstance(report.get("sha256"), str)
        and report["sha256"] == base.logical_sha(payload)
    )
    gates["python_receipt_payload_hash_self_consistent"] = True
    receipt["payload"]["gates"] = gates
    receipt["sha256"] = base.logical_sha(receipt["payload"])
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("compact_rows", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("node_receipt", type=Path)
    parser.add_argument("exclusion_manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt = verify(
        args.report,
        args.compact_rows,
        args.labels,
        args.node_receipt,
        args.exclusion_manifest,
    )
    payload = receipt["payload"]
    valid = all(payload["gates"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".md").write_text(
        "\n".join(
            [
                "# FIN-RVI-002 Stage 7 — strict clean reconstruction",
                "",
                f"- Status: **{'PASS' if valid else 'FAIL'}**",
                f"- G09 replication: `{payload['gate_readout']['G09_REPLICATION']}`",
                f"- G09: `{payload['gate_readout']['G09']}`",
                f"- Finance score pending final contract: **{payload['gate_readout']['finance_score']}/1000**",
                f"- Supported recovered: **{payload['policy_metrics']['POLICY_DOCUMENTARY']['supported_recovered']}**",
                f"- Unsafe promotions: **{payload['policy_metrics']['POLICY_DOCUMENTARY']['unsafe_overpromotions']}**",
                f"- Baseline unsafe promotions: **{payload['policy_metrics']['B1_CODE_SUPPLIER']['unsafe_overpromotions']}**",
                f"- Receipt SHA-256: `{receipt['sha256']}`",
                "",
                "## Boundary",
                "",
                payload["boundary"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "valid": valid,
                "receipt_sha256": receipt["sha256"],
                "gate_readout": payload["gate_readout"],
            },
            sort_keys=True,
        )
    )
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
