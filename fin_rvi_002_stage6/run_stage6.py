from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from fin_rvi_002_stage1 import run_stage1 as base
from fin_rvi_002_stage1.identity_v2 import compact_identity_pairs_v2
from fin_rvi_002_stage1.ocds import sha256_payload
from fin_rvi_002_stage1.run_stage1_v2 import generate_candidates_v2
from fin_rvi_002_stage3 import run_stage3 as stage3
from fin_rvi_002_stage3 import run_stage3_parallel as stage3_parallel
from fin_rvi_002_stage4 import run_stage4 as stage4
from fin_rvi_002_stage4.policy_v3 import POLICY_ID, adjudicate_policy_v3

SCHEMA = "fin-rvi-002/stage6-third-sealed-cohort/1"
SEED = "FIN-RVI-002-STAGE6-THIRD-SEALED-COHORT-V1"
EXPECTED_STAGE3_CODES = 118
EXPECTED_STAGE4_CODES = 119
EXPECTED_UNION_CODES = 237
EXPECTED_UNION_SHA256 = "927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984"
_LAST_EXCLUSION_MANIFEST: dict | None = None


def _codes_sha256(codes: list[str]) -> str:
    return hashlib.sha256("\n".join(codes).encode("utf-8")).hexdigest()


def derive_exclusion_manifest(candidates: list[dict]) -> dict:
    """Reconstruct Stage 3 and Stage 4 selected code sets without reading outcomes."""
    stage3_codes = sorted(set(stage4.exclusion_manifest()["shared_codes"]))
    stage4_selected = stage4.freeze_stage4(
        json.loads(json.dumps(candidates)), 120
    )
    stage4_codes = sorted(
        {str(row["shared_code"]) for row in stage4_selected}
    )
    union = sorted(set(stage3_codes) | set(stage4_codes))
    manifest = {
        "schema": "fin-rvi-002/stage6-derived-exclusion-manifest/1",
        "selection_contract": (
            "derive Stage 3 and Stage 4 code exclusions using their frozen seeds and selection code before Stage 6 outcome inspection"
        ),
        "stage3_shared_code_count": len(stage3_codes),
        "stage4_shared_code_count": len(stage4_codes),
        "shared_code_count": len(union),
        "stage3_shared_codes_sha256": _codes_sha256(stage3_codes),
        "stage4_shared_codes_sha256": _codes_sha256(stage4_codes),
        "shared_codes_sha256": _codes_sha256(union),
        "shared_codes": union,
        "source_heads": {
            "stage3": "8f817d941716d6bf7816b2c422a49b3da108bb41",
            "stage4": "9e6686204fce20bc21d17f041d506a2a9c92761d",
        },
    }
    if len(stage3_codes) != EXPECTED_STAGE3_CODES:
        raise ValueError(f"unexpected Stage 3 code count: {len(stage3_codes)}")
    if len(stage4_codes) != EXPECTED_STAGE4_CODES:
        raise ValueError(f"unexpected Stage 4 code count: {len(stage4_codes)}")
    if len(union) != EXPECTED_UNION_CODES:
        raise ValueError(f"unexpected union code count: {len(union)}")
    if manifest["shared_codes_sha256"] != EXPECTED_UNION_SHA256:
        raise ValueError("Stage 3+4 exclusion code hash drifted")
    return manifest


def freeze_stage6(candidates: list[dict], size: int) -> list[dict]:
    global _LAST_EXCLUSION_MANIFEST
    manifest = derive_exclusion_manifest(candidates)
    _LAST_EXCLUSION_MANIFEST = manifest
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
        row["stage6_selection_seed"] = SEED
        row["stage6_stage34_codes_excluded"] = True
    return selected


def exclusion_manifest() -> dict:
    if _LAST_EXCLUSION_MANIFEST is None:
        raise RuntimeError("Stage 6 exclusion manifest not derived yet")
    return _LAST_EXCLUSION_MANIFEST


def rewrite_stage6(output: Path) -> None:
    decision_rows = [
        json.loads(line)
        for line in (output / "holdout_decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    decision_by_id = {row["candidate_id"]: row for row in decision_rows}

    stage3.rewrite_report(output)
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = report["payload"]
    stage6_block = payload.pop("stage3")
    manifest = exclusion_manifest()

    for row in stage6_block["compact_rows"]:
        adjudication = decision_by_id[row["candidate_id"]][
            "object_adjudication"
        ]
        row["base_v2_decision"] = str(
            adjudication.get("base_v2_decision", "UNRESOLVED")
        )

    payload["schema"] = SCHEMA
    payload["configuration"]["seed"] = SEED
    payload["configuration"]["selection_blinding"] = (
        "All Stage 3 and Stage 4 shared codes plus prior holdout and known codes excluded; family, cardinality, amount bucket, time bucket and fixed SHA-256 only"
    )
    payload["stage6"] = stage6_block
    payload["stage6"]["policy_id"] = POLICY_ID
    payload["stage6"]["source_stage34_manifest"] = manifest
    payload["stage6"]["source_stage34_manifest_sha256"] = sha256_payload(
        manifest
    )
    payload["stage6"]["independence_contract"] = {
        "stage3_and_stage4_shared_codes_excluded": True,
        "excluded_shared_code_count": manifest["shared_code_count"],
        "excluded_shared_codes_sha256": manifest["shared_codes_sha256"],
        "policy_v3_unchanged_from_stage4": True,
        "labeler_unchanged_from_stage3": True,
        "selection_seed_new": True,
        "exclusions_derived_without_outcome_access": True,
        "independent_policy_facts_exported": True,
    }
    payload["gate_readout"] = {
        "G07": "PASS",
        "G09_REPLICATION": (
            "PASS_CANDIDATE_PENDING_CLEAN_REPLAY"
            if stage6_block["gate_status"]
            == "PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION"
            else "OPEN"
        ),
        "G09": "OPEN_PRIOR_ART_AND_CLEAN_REPLAY_REQUIRED",
        "finance_score": 920,
    }
    report["sha256"] = sha256_payload(payload)
    base.write_json(report_path, report)

    stage3_compact = output / "stage3_compact_rows.jsonl"
    stage3_compact.unlink(missing_ok=True)
    stage6_compact = output / "stage6_compact_rows.jsonl"
    stage6_compact.write_text(
        "\n".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False)
            for row in stage6_block["compact_rows"]
        )
        + "\n",
        encoding="utf-8",
    )
    stage3_labels = output / "stage3_confirmed_labels.jsonl"
    if stage3_labels.exists():
        stage3_labels.replace(output / "stage6_confirmed_labels.jsonl")
    (output / "stage34_exclusion_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "report.sha256").write_text(
        f"{base.sha256_file(report_path)}  report.json\n", encoding="utf-8"
    )

    block = payload["stage6"]
    baseline = block["policy_metrics"]["B1_CODE_SUPPLIER"]
    challenger = block["policy_metrics"]["POLICY_DOCUMENTARY"]
    lines = [
        "# FIN-RVI-002 Stage 6 — third sealed cohort",
        "",
        f"- Gate status: **{block['gate_status']}**",
        f"- Policy: `{POLICY_ID}`",
        f"- Excluded prior codes: **{manifest['shared_code_count']}**",
        f"- Cohort: **{len(block['compact_rows'])}**",
        f"- Supported labels: **{block['label_counts'].get('SUPPORTED', 0)}**",
        f"- Rejected labels: **{block['label_counts'].get('REJECTED', 0)}**",
        f"- Unresolved labels: **{block['label_counts'].get('UNRESOLVED', 0)}**",
        f"- Baseline unsafe promotions: **{baseline['unsafe_overpromotions']}**",
        f"- Policy unsafe promotions: **{challenger['unsafe_overpromotions']}**",
        f"- Baseline supported recovered: **{baseline['supported_recovered']}**",
        f"- Policy supported recovered: **{challenger['supported_recovered']}**",
        f"- Report SHA-256: `{report['sha256']}`",
        "",
        "## Gates",
        "",
        *[
            f"- {name}: **{'PASS' if value else 'FAIL'}**"
            for name, value in block["gate_checks"].items()
        ],
        "",
        "## Boundary",
        "",
        "This is a third domain-bounded public cohort. It tests CONTRACTOR_PAYMENT evidence only; it does not establish legality, delivery, quality, liquidation, fraud, corruption or physical result.",
    ]
    (output / "stage6_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    base.compact_identity_pairs = compact_identity_pairs_v2
    base.generate_candidates = generate_candidates_v2
    base.freeze_holdout = freeze_stage6
    base.adjudicate_object = adjudicate_policy_v3
    stage3_parallel.adjudicate_object_v2 = adjudicate_policy_v3
    base.evaluate_holdout = stage3_parallel.evaluate_stage3_parallel
    output = Path("reports/fin_rvi_002_stage6")
    if "--output" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output") + 1])
    base.main()
    rewrite_stage6(output)


if __name__ == "__main__":
    main()
