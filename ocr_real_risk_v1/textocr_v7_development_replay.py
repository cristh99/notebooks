"""Reproduce the opened TextOCR development diagnostic for v7.

The input is the terminal evidence artifact from TextOCR v6. This replay is
engineering evidence only: TextOCR outcomes were already visible before v7 was
defined, so no metric here receives external scientific credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .core import canonical_json, sha256_bytes
from .numeric_consensus_policy_v7 import predict_v7_claim_verifier

REPORT_COUNT = 12
SELECTED_COUNT = 4674
TERMINAL_ARTIFACT_ID = 8961886770
TERMINAL_ARTIFACT_ZIP_SHA256 = (
    "899732a43cfc7f3889d441a8a639993eef58bc2e21d250e51a3a6c93f1b47921"
)
TERMINAL_AGGREGATE_SHA256 = (
    "2bfb3a50a148ccad8c56a001c5dffe1e9d4240f4e63ebf9778c66d4ce3a1ad2e"
)
TERMINAL_RUN_RECORD_SHA256 = (
    "0fdf7c30d052fc697fca45436915388bccfb4817bf5c07773490be8af5ee1ecb"
)


def stable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("stable_payload_sha256", None)
    result["stable_payload_sha256"] = sha256_bytes(
        canonical_json(result).encode("utf-8")
    )
    return result


def _observations(root: Path) -> Iterable[dict[str, Any]]:
    reports = sorted(
        root.glob("partition-reports/p*/partition_report.json")
    )
    if len(reports) != REPORT_COUNT:
        raise RuntimeError(
            f"expected {REPORT_COUNT} partition reports, found {len(reports)}"
        )
    for path in reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        for observation in report.get("observations") or []:
            yield dict(observation)


def _policy_row(
    observation: dict[str, Any], *, counterfactual: bool
) -> dict[str, Any]:
    candidate = observation["candidate"]
    source = (
        observation["counterfactual"]
        if counterfactual
        else candidate
    )
    return {
        "candidate": {
            "claim": source.get("claim"),
            "prediction": source.get("forest_prediction"),
            "minimum_mean_probability": source.get(
                "minimum_mean_probability"
            ),
            "matched": candidate.get("matched"),
            "guard": candidate.get("guard"),
        }
    }


def replay(root: Path) -> dict[str, Any]:
    aggregate = root / "aggregate/textocr_external_aggregate.json"
    terminal = root / "terminal_run_record.json"
    if hashlib.sha256(aggregate.read_bytes()).hexdigest() != (
        TERMINAL_AGGREGATE_SHA256
    ):
        raise RuntimeError("TextOCR aggregate SHA-256 mismatch")
    if hashlib.sha256(terminal.read_bytes()).hexdigest() != (
        TERMINAL_RUN_RECORD_SHA256
    ):
        raise RuntimeError("TextOCR terminal record SHA-256 mismatch")
    rows = list(_observations(root))
    if len(rows) != SELECTED_COUNT:
        raise RuntimeError(
            f"expected {SELECTED_COUNT} observations, found {len(rows)}"
        )
    image_hashes = {str(row["image_sha256"]) for row in rows}
    if len(image_hashes) != len(rows):
        raise RuntimeError("duplicate encoded-image SHA-256 in TextOCR replay")

    v7_outputs = [
        predict_v7_claim_verifier(_policy_row(row, counterfactual=False))
        for row in rows
    ]
    v7_counterfactual_outputs = [
        predict_v7_claim_verifier(_policy_row(row, counterfactual=True))
        for row in rows
    ]
    v7_accepted = sum(output is not None for output in v7_outputs)
    report = {
        "schema": "ocr-textocr-v7-development-replay/1",
        "source": {
            "terminal_artifact_id": TERMINAL_ARTIFACT_ID,
            "terminal_artifact_zip_sha256": (
                TERMINAL_ARTIFACT_ZIP_SHA256
            ),
            "terminal_aggregate_sha256": TERMINAL_AGGREGATE_SHA256,
            "terminal_run_record_sha256": TERMINAL_RUN_RECORD_SHA256,
            "partition_reports": REPORT_COUNT,
            "selected_observations": len(rows),
            "unique_encoded_image_sha256": len(image_hashes),
        },
        "v6_terminal": {
            "accepted": sum(
                bool(row["candidate"].get("accepted")) for row in rows
            ),
            "false_accepted": sum(
                bool(row["candidate"].get("false_accept")) for row in rows
            ),
            "counterfactual_outputs": sum(
                bool(row["counterfactual"].get("accepted"))
                for row in rows
            ),
            "truth_length_oracle_abstentions": sum(
                row["candidate"].get("reason")
                == "LENGTH_MISMATCH_OUTSIDE_SUBSTITUTION_SCOPE"
                for row in rows
            ),
            "accepted_below_declared_probability_0_25": sum(
                bool(row["candidate"].get("accepted"))
                and float(
                    row["candidate"].get(
                        "minimum_mean_probability"
                    )
                    or 0.0
                )
                < 0.25
                for row in rows
            ),
        },
        "v7_opened_development_diagnostic": {
            "accepted": v7_accepted,
            "false_accepted": sum(
                output is not None
                and output != str(row["truth"])
                for output, row in zip(v7_outputs, rows)
            ),
            "counterfactual_outputs": sum(
                output is not None
                for output in v7_counterfactual_outputs
            ),
            "acceptance_rate_over_selected": (
                v7_accepted / len(rows)
            ),
            "acceptance_decisions_changed_from_v6": sum(
                (output is not None)
                != bool(row["candidate"].get("accepted"))
                for output, row in zip(v7_outputs, rows)
            ),
            "truth_length_oracle_removed_in_source": True,
            "probability_threshold_0_25_effective_in_source": True,
        },
        "limitations": {
            "textocr_outcomes_opened_before_v7": True,
            "scientific_credit": False,
            "production_credit": False,
            "truth_length_oracle_cases_missing_downstream_channels": 337,
            "fresh_untouched_corpus_required": True,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    return stable_payload(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = replay(args.evidence_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
