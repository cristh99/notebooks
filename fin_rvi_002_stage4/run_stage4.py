from __future__ import annotations

import json
import sys
from pathlib import Path

from fin_rvi_002_stage1 import run_stage1 as base
from fin_rvi_002_stage1.identity_v2 import compact_identity_pairs_v2
from fin_rvi_002_stage1.ocds import sha256_payload
from fin_rvi_002_stage1.run_stage1_v2 import generate_candidates_v2
from fin_rvi_002_stage3 import run_stage3 as stage3
from fin_rvi_002_stage3 import run_stage3_parallel as stage3_parallel
from fin_rvi_002_stage4.policy_v3 import POLICY_ID, adjudicate_policy_v3

SCHEMA = "fin-rvi-002/stage4-independent-policy-v3/1"
SEED = "FIN-RVI-002-STAGE4-INDEPENDENT-POLICY-V3-V1"
MANIFEST_PATH = Path("fin_rvi_002_stage4/stage3_exclusion_manifest.json")


def exclusion_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def freeze_stage4(candidates: list[dict], size: int) -> list[dict]:
    manifest = exclusion_manifest()
    excluded_codes = set(manifest["shared_codes"])
    filtered = [
        candidate
        for candidate in candidates
        if candidate.get("shared_code") not in excluded_codes
    ]
    previous_seed = stage3.SEED
    stage3.SEED = SEED
    try:
        selected = stage3.freeze_stage3(filtered, size)
    finally:
        stage3.SEED = previous_seed
    for row in selected:
        row["stage4_selection_seed"] = SEED
        row["stage4_stage3_codes_excluded"] = True
    return selected


def rewrite_stage4(output: Path) -> None:
    stage3.rewrite_report(output)
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = report["payload"]
    stage4_block = payload.pop("stage3")
    payload["schema"] = SCHEMA
    payload["configuration"]["seed"] = SEED
    payload["configuration"]["selection_blinding"] = (
        "Stage 3 shared codes plus prior holdout and known codes excluded; family, cardinality, amount bucket, time bucket and fixed SHA-256 only"
    )
    payload["stage4"] = stage4_block
    payload["stage4"]["policy_id"] = POLICY_ID
    payload["stage4"]["source_stage3_manifest"] = exclusion_manifest()
    payload["stage4"]["source_stage3_manifest_sha256"] = sha256_payload(
        exclusion_manifest()
    )
    payload["stage4"]["independence_contract"] = {
        "stage3_shared_codes_excluded": True,
        "stage3_report_sha256": exclusion_manifest()["source_report_sha256"],
        "policy_fixed_before_stage4_outcomes": True,
        "labeler_unchanged_from_stage3": True,
    }
    payload["gate_readout"] = {
        "G07": payload["stage4"]["gate_status"],
        "G09": "OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED",
    }
    report["sha256"] = sha256_payload(payload)
    base.write_json(report_path, report)

    stage3_compact = output / "stage3_compact_rows.jsonl"
    stage3_labels = output / "stage3_confirmed_labels.jsonl"
    if stage3_compact.exists():
        stage3_compact.replace(output / "stage4_compact_rows.jsonl")
    if stage3_labels.exists():
        stage3_labels.replace(output / "stage4_confirmed_labels.jsonl")
    (output / "report.sha256").write_text(
        f"{base.sha256_file(report_path)}  report.json\n", encoding="utf-8"
    )

    block = payload["stage4"]
    baseline = block["policy_metrics"]["B1_CODE_SUPPLIER"]
    challenger = block["policy_metrics"]["POLICY_DOCUMENTARY"]
    lines = [
        "# FIN-RVI-002 Stage 4 — independent policy v3 validation",
        "",
        f"- Gate status: **{block['gate_status']}**",
        f"- Policy: `{POLICY_ID}`",
        f"- Cohort: **{len(block['compact_rows'])}**",
        f"- Supported labels: **{block['label_counts'].get('SUPPORTED', 0)}**",
        f"- Rejected labels: **{block['label_counts'].get('REJECTED', 0)}**",
        f"- Unresolved labels: **{block['label_counts'].get('UNRESOLVED', 0)}**",
        f"- Baseline unsafe promotions: **{baseline['unsafe_overpromotions']}**",
        f"- V3 unsafe promotions: **{challenger['unsafe_overpromotions']}**",
        f"- Baseline supported recovered: **{baseline['supported_recovered']}**",
        f"- V3 supported recovered: **{challenger['supported_recovered']}**",
        f"- Report SHA-256: `{report['sha256']}`",
        "",
        "## Gates",
        "",
        *[
            f"- {name}: **{'PASS' if value else 'FAIL'}**"
            for name, value in block["gate_checks"].items()
        ],
        "",
        "## Independence",
        "",
        "All Stage 3 shared codes were excluded before Stage 4 selection. The policy was fixed from Stage 3 counterexamples; the conservative evidence labeler was not changed.",
    ]
    (output / "stage4_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    base.compact_identity_pairs = compact_identity_pairs_v2
    base.generate_candidates = generate_candidates_v2
    base.freeze_holdout = freeze_stage4
    base.adjudicate_object = adjudicate_policy_v3
    stage3_parallel.adjudicate_object_v2 = adjudicate_policy_v3
    base.evaluate_holdout = stage3_parallel.evaluate_stage3_parallel
    output = Path("reports/fin_rvi_002_stage4")
    if "--output" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output") + 1])
    base.main()
    rewrite_stage4(output)


if __name__ == "__main__":
    main()
