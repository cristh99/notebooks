from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

EXPECTED_WEIGHTS = {
    "WORLD_SOTA_SUPERIORITY": 250,
    "HISTORICAL_ORIGINALITY": 200,
    "CROSS_DOMAIN_GENERALITY": 150,
    "TRUTH_RIGOR_REPRODUCIBILITY": 150,
    "EXTERNAL_VALIDATION_AND_IMPACT": 150,
    "AUTONOMOUS_RECURSIVE_GROWTH": 100,
}
EXPECTED_SCORES = {
    "WORLD_SOTA_SUPERIORITY": 35,
    "HISTORICAL_ORIGINALITY": 45,
    "CROSS_DOMAIN_GENERALITY": 90,
    "TRUTH_RIGOR_REPRODUCIBILITY": 125,
    "EXTERNAL_VALIDATION_AND_IMPACT": 48,
    "AUTONOMOUS_RECURSIVE_GROWTH": 80,
}
EXPECTED_SCORE = 423
EXPECTED_ACTION = "parallel_benchmark_deployment_discovery"


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def minimax_regret(actions: Mapping[str, Mapping[str, int]]) -> tuple[str, dict[str, int]]:
    if not actions:
        raise ValueError("actions are required")
    states = set(next(iter(actions.values())))
    if not states:
        raise ValueError("states are required")
    for utility in actions.values():
        if set(utility) != states:
            raise ValueError("all actions must cover identical states")
    best_by_state = {
        state: max(utility[state] for utility in actions.values())
        for state in states
    }
    regrets = {
        action: max(best_by_state[state] - utility[state] for state in states)
        for action, utility in actions.items()
    }
    selected = min(regrets, key=lambda action: (regrets[action], action))
    return selected, regrets


def verify(scorecard: Mapping[str, Any]) -> dict[str, Any]:
    dimensions = scorecard.get("dimensions")
    dimension_map = {
        item.get("id"): item
        for item in dimensions
        if isinstance(item, Mapping)
    } if isinstance(dimensions, list) else {}
    weights = {
        name: int(item.get("weight", -1))
        for name, item in dimension_map.items()
    }
    scores = {
        name: int(item.get("score", -1))
        for name, item in dimension_map.items()
    }
    actions = scorecard.get("problem_ir", {}).get("actions", {})
    try:
        selected, regrets = minimax_regret(actions)
    except Exception:
        selected, regrets = None, {}
    bounded = scorecard.get("bounded_result", {})
    demotions = scorecard.get("superseded_interpretations", {})

    gates = {
        "schema": scorecard.get("schema") == "finance-absolute-level-god-score/1",
        "cut_date": scorecard.get("cut_date") == "2026-08-03",
        "dimension_set": set(dimension_map) == set(EXPECTED_WEIGHTS),
        "weights_exact": weights == EXPECTED_WEIGHTS,
        "weights_sum_1000": sum(weights.values()) == 1000,
        "scores_exact": scores == EXPECTED_SCORES,
        "scores_sum_423": sum(scores.values()) == EXPECTED_SCORE,
        "declared_score_423": scorecard.get("absolute_score") == EXPECTED_SCORE,
        "not_falsely_solved": scorecard.get("terminal_status") == "BLOCKED",
        "open_points_577": 1000 - int(scorecard.get("absolute_score", -1)) == 577,
        "maximum_claim_bounded": "domain-bounded" in str(scorecard.get("maximum_claim", "")),
        "internal_scores_demoted": (
            "not absolute world SOTA" in str(demotions.get("775", ""))
            and "not absolute world SOTA" in str(demotions.get("820", ""))
            and "not all of finance" in str(demotions.get("1000", ""))
        ),
        "fin_rvi_scope_bounded": (
            bounded.get("claim_id") == "FIN-RVI-002-C1"
            and "Honduras ONCAE-SEFIN" in str(bounded.get("scope", ""))
            and "global finance SOTA" in set(bounded.get("does_not_imply", []))
        ),
        "fin_rvi_metrics_preserved": (
            bounded.get("baseline_unsafe_promotions") == 20
            and bounded.get("challenger_unsafe_promotions") == 0
            and bounded.get("baseline_supported_recovered") == 58
            and bounded.get("challenger_supported_recovered") == 58
        ),
        "minimax_recomputed": selected == EXPECTED_ACTION,
        "selected_action_exact": scorecard.get("selected_action") == EXPECTED_ACTION,
        "more_theory_not_selected": selected != "more_internal_theory",
        "partial_unknown_problem": (
            scorecard.get("problem_ir", {}).get("uncertainty") == "UNKNOWN"
            and scorecard.get("problem_ir", {}).get("model_status") == "PARTIAL"
        ),
        "next_program_complete": set(scorecard.get("next_program", [])) == {
            "FIN-ABS-001 sealed cross-domain external benchmark",
            "FIN-ABS-002 real-data engine deployment and stress validation",
            "FIN-ABS-003 independent replication and historical-priority audit",
        },
    }
    valid = all(gates.values())
    payload = {
        "schema": "finance-absolute-level-god-receipt/1",
        "scorecard_sha256": digest(scorecard),
        "valid": valid,
        "absolute_score": scorecard.get("absolute_score"),
        "terminal_status": scorecard.get("terminal_status"),
        "selected_action": selected,
        "minimax_regrets": regrets,
        "gates": gates,
        "boundary": (
            "423/1000 is the broad absolute score. FIN-RVI-002 remains a "
            "domain-bounded empirical result and cannot establish universal Finance SOTA."
        ),
    }
    return {"payload": payload, "sha256": digest(payload)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scorecard", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scorecard = json.loads(args.scorecard.read_text(encoding="utf-8"))
    receipt = verify(scorecard)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md = args.output.with_suffix(".md")
    md.write_text(
        "\n".join(
            [
                "# Finance — absolute Level-God recalibration",
                "",
                f"- Valid: **{receipt['payload']['valid']}**",
                f"- Absolute score: **{receipt['payload']['absolute_score']}/1000**",
                f"- Status: `{receipt['payload']['terminal_status']}`",
                f"- Selected action: `{receipt['payload']['selected_action']}`",
                f"- Receipt SHA-256: `{receipt['sha256']}`",
                "",
                receipt["payload"]["boundary"],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "valid": receipt["payload"]["valid"],
        "score": receipt["payload"]["absolute_score"],
        "selected_action": receipt["payload"]["selected_action"],
        "receipt_sha256": receipt["sha256"],
    }, sort_keys=True))
    return 0 if receipt["payload"]["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
