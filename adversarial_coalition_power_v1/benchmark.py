"""Preregistered benchmark for adversarial coalition power."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any
import csv
import hashlib
import json

from coalition_power import (
    ActionEvent,
    Agent,
    Claim,
    CoalitionAuthorizer,
    CoalitionGame,
    DelegationToken,
    JointAction,
    MessageEvent,
    RobustCoalitionGame,
    audit_claims,
    audit_collusion,
    canonical_json,
    coalition_receipt,
    digest,
    safe_dissolution,
)

DOMAINS = ("research", "software", "finance", "logistics", "physical", "governance")
ARCHETYPES = (
    "sybil_resistant_quorum",
    "delegation_attenuation",
    "joint_authority",
    "robust_coalition_value",
    "core_stability",
    "shapley_efficiency",
    "shapley_core_distinction",
    "action_collusion_audit",
    "collusion_on_paper",
    "evaluator_independence",
    "claim_provenance",
    "safe_dissolution",
)


def q(domain: str, name: str) -> str:
    return f"{domain}:{name}"


def authorizer_fixture(domain: str) -> tuple[CoalitionAuthorizer, dict[str, object]]:
    scope = q(domain, "execute")
    eval_scope = q(domain, "evaluate")
    agents = {
        q(domain, "alice"): Agent(q(domain, "alice"), q(domain, "root_a"), [scope]),
        q(domain, "alice_clone"): Agent(q(domain, "alice_clone"), q(domain, "root_a"), [scope]),
        q(domain, "bob"): Agent(q(domain, "bob"), q(domain, "root_b"), [scope]),
        q(domain, "auditor"): Agent(q(domain, "auditor"), q(domain, "root_c"), [scope, eval_scope], independent=True),
    }
    roots = {
        name: DelegationToken.issue_root(
            principal=agent.root_identity,
            subject=agent.name,
            scopes=agent.capabilities,
            max_depth=2,
            nonce=f"{domain}:{index}",
        )
        for index, (name, agent) in enumerate(agents.items())
    }
    authorizer = CoalitionAuthorizer(
        agents=agents,
        tokens=roots,
        threshold=2,
        high_impact_threshold=3,
        evaluator_roots=[q(domain, "root_c")],
    )
    return authorizer, {"scope": scope, "eval_scope": eval_scope, "agents": agents, "tokens": roots}


def stable_game(domain: str) -> CoalitionGame:
    a, b, c = q(domain, "a"), q(domain, "b"), q(domain, "c")
    return CoalitionGame(
        [a, b, c],
        {
            (): 0,
            (a,): 1,
            (b,): 1,
            (c,): 1,
            (a, b): 5,
            (a, c): 4,
            (b, c): 4,
            (a, b, c): 9,
        },
    )


def unstable_shapley_game(domain: str) -> CoalitionGame:
    a, b, c = q(domain, "u_a"), q(domain, "u_b"), q(domain, "u_c")
    return CoalitionGame(
        [a, b, c],
        {
            (): 0,
            (a,): 0,
            (b,): 0,
            (c,): 0,
            (a, b): 10,
            (a, c): 0,
            (b, c): 0,
            (a, b, c): 9,
        },
    )


def robust_fixture(domain: str) -> RobustCoalitionGame:
    a, b, c = q(domain, "r_a"), q(domain, "r_b"), q(domain, "r_c")
    clear = CoalitionGame(
        [a, b, c],
        {(): 0, (a,): 1, (b,): 1, (c,): 1, (a, b): 10, (a, c): 5, (b, c): 5, (a, b, c): 12},
    )
    adverse = CoalitionGame(
        [a, b, c],
        {(): 0, (a,): 1, (b,): 1, (c,): 1, (a, b): 2, (a, c): 6, (b, c): 6, (a, b, c): 8},
    )
    return RobustCoalitionGame({q(domain, "clear"): clear, q(domain, "adverse"): adverse})


def check_domain(domain: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(archetype: str, passed: bool, observed: object, expected: object) -> None:
        rows.append({"domain": domain, "archetype": archetype, "passed": bool(passed), "observed": observed, "expected": expected})

    auth, ctx = authorizer_fixture(domain)
    scope = ctx["scope"]
    tokens = ctx["tokens"]
    action = JointAction(q(domain, "joint_action"), [scope])
    alice = q(domain, "alice")
    clone = q(domain, "alice_clone")
    bob = q(domain, "bob")
    auditor = q(domain, "auditor")

    sybil = auth.authorize(action, [auth.approve(alice, action), auth.approve(clone, action)])
    honest = auth.authorize(action, [auth.approve(alice, action), auth.approve(bob, action)])
    add("sybil_resistant_quorum", not sybil.allowed and honest.allowed, {"sybil": sybil.reason, "honest": honest.reason}, "two distinct roots required")

    parent = tokens[alice]
    child = parent.delegate(subject=q(domain, "worker"), scopes=[scope], nonce=q(domain, "child"))
    expansion_rejected = False
    try:
        parent.delegate(subject=q(domain, "bad_worker"), scopes=[scope, q(domain, "admin")], nonce=q(domain, "bad"))
    except ValueError:
        expansion_rejected = True
    add("delegation_attenuation", child.authorizes([scope]) and child.depth_remaining == parent.depth_remaining - 1 and expansion_rejected, {"child_scopes": child.scopes, "depth": child.depth_remaining}, "scope subset and depth attenuation")

    high = JointAction(q(domain, "high_action"), [scope], high_impact=True)
    two_roots = auth.authorize(high, [auth.approve(alice, high), auth.approve(bob, high)])
    three_roots = auth.authorize(high, [auth.approve(alice, high), auth.approve(bob, high), auth.approve(auditor, high)])
    add("joint_authority", not two_roots.allowed and three_roots.allowed, {"two": two_roots.reason, "three": three_roots.reason}, "high impact requires three roots")

    robust = robust_fixture(domain)
    pair_ab = {q(domain, "r_a"), q(domain, "r_b")}
    grand = set(robust.players)
    partition, robust_welfare = robust.robust_optimal_partition()
    add("robust_coalition_value", robust.nominal_value(pair_ab, q(domain, "clear")) == 10 and robust.robust_value(pair_ab) == 2 and robust.robust_value(grand) == 8 and robust_welfare == 8, {"pair_nominal": str(robust.nominal_value(pair_ab, q(domain, "clear"))), "pair_robust": str(robust.robust_value(pair_ab)), "grand_robust": str(robust.robust_value(grand)), "partition": [sorted(c) for c in partition]}, "robust grand coalition value 8")

    game = stable_game(domain)
    allocation = {q(domain, "a"): 3, q(domain, "b"): 3, q(domain, "c"): 3}
    add("core_stability", game.in_core(allocation), {"blockers": [sorted(c) for c in game.blocking_coalitions(allocation)]}, "no blocking coalition")

    shapley = game.shapley()
    add("shapley_efficiency", sum(shapley.values(), Fraction()) == game.value(game.players), {k: str(v) for k, v in shapley.items()}, "sum equals grand value")

    unstable = unstable_shapley_game(domain)
    unstable_shapley = unstable.shapley()
    blockers = unstable.blocking_coalitions(unstable_shapley)
    add("shapley_core_distinction", sum(unstable_shapley.values(), Fraction()) == unstable.value(unstable.players) and not unstable.in_core(unstable_shapley) and frozenset({q(domain, "u_a"), q(domain, "u_b")}) in blockers, {"shapley": {k: str(v) for k, v in unstable_shapley.items()}, "blockers": [sorted(c) for c in blockers]}, "fair attribution can be unstable")

    collusive = audit_collusion(
        messages=[
            MessageEvent(alice, q(domain, "secret"), "serve_principal", "secondary_goal"),
            MessageEvent(bob, q(domain, "secret"), "serve_principal", "secondary_goal"),
        ],
        actions=[
            ActionEvent(alice, q(domain, "divert"), -3, 4),
            ActionEvent(bob, q(domain, "conceal"), -2, 3),
        ],
        cooperative_optimum=5,
    )
    add("action_collusion_audit", collusive.textual_collusion and collusive.action_collusion and collusive.principal_regret == 10 and collusive.private_gain == 7, {"regret": str(collusive.principal_regret), "private_gain": str(collusive.private_gain)}, "harmful coordinated actions detected")

    paper_only = audit_collusion(
        messages=[MessageEvent(alice, q(domain, "secret"), "serve_principal", "secondary_goal")],
        actions=[ActionEvent(alice, q(domain, "cooperate"), 5, 0)],
        cooperative_optimum=5,
    )
    add("collusion_on_paper", paper_only.textual_collusion and not paper_only.action_collusion and paper_only.principal_regret == 0, {"text": paper_only.textual_collusion, "action": paper_only.action_collusion, "regret": str(paper_only.principal_regret)}, "text intent differs from action collusion")

    evaluator_action = JointAction(q(domain, "change_evaluator"), [scope], evaluator_change=True)
    no_auditor = auth.authorize(evaluator_action, [auth.approve(alice, evaluator_action), auth.approve(bob, evaluator_action)])
    with_auditor = auth.authorize(evaluator_action, [auth.approve(alice, evaluator_action), auth.approve(auditor, evaluator_action)])
    add("evaluator_independence", not no_auditor.allowed and no_auditor.reason == "MISSING_INDEPENDENT_EVALUATOR" and with_auditor.allowed, {"without": no_auditor.reason, "with": with_auditor.reason}, "independent evaluator root required")

    evidence = digest({"domain": domain, "fact": "true"})
    good_claims = [Claim(alice, q(domain, "fact"), "true", evidence), Claim(bob, q(domain, "fact"), "true", evidence)]
    bad_claims = [Claim(alice, q(domain, "fact"), "true", evidence), Claim(bob, q(domain, "fact"), "false", None)]
    good_audit = audit_claims(good_claims)
    bad_audit = audit_claims(bad_claims)
    add("claim_provenance", good_audit["valid"] and not bad_audit["valid"] and bad_audit["unsupported"] and bad_audit["contradictions"], {"good": good_audit, "bad": bad_audit}, "unsupported contradiction rejected")

    approvals = [auth.approve(alice, action), auth.approve(bob, action), auth.approve(auditor, action)]
    continue_decision = safe_dissolution(action=action, authorizer=auth, approvals=approvals, withdrawn_agents=[alice], rollback_available=True)
    rollback_decision = safe_dissolution(action=high, authorizer=auth, approvals=[auth.approve(alice, high), auth.approve(bob, high), auth.approve(auditor, high)], withdrawn_agents=[auditor], rollback_available=True)
    add("safe_dissolution", continue_decision.proceed and not continue_decision.rollback and not rollback_decision.proceed and rollback_decision.rollback, {"continue": continue_decision.reason, "rollback": rollback_decision.reason}, "reauthorize or rollback")

    assert tuple(row["archetype"] for row in rows) == ARCHETYPES
    return rows


def run_benchmark(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [row for domain in DOMAINS for row in check_domain(domain)]
    passed = sum(1 for row in rows if row["passed"])
    manifest = {
        "schema": "adversarial-coalition-power/manifest/1",
        "domains": list(DOMAINS),
        "archetypes": list(ARCHETYPES),
        "scenario_ids": [f"{r['domain']}::{r['archetype']}" for r in rows],
    }
    summary = {
        "schema": "adversarial-coalition-power/benchmark-summary/1",
        "scenario_count": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "exact_conformance": passed / len(rows),
        "rows_sha256": digest(rows),
    }
    matrix = out / "benchmark_matrix.csv"
    with matrix.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("domain", "archetype", "passed", "observed", "expected"))
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "observed": json.dumps(row["observed"], sort_keys=True, ensure_ascii=False, default=str),
                "expected": json.dumps(row["expected"], sort_keys=True, ensure_ascii=False, default=str),
            })
    (out / "scenario_manifest.json").write_bytes(canonical_json(manifest) + b"\n")
    (out / "benchmark_summary.json").write_bytes(canonical_json(summary) + b"\n")
    body = {
        "status": "PASS" if passed == len(rows) else "FAIL",
        "scenario_count": len(rows),
        "passed": passed,
        "manifest_sha256": hashlib.sha256((out / "scenario_manifest.json").read_bytes()).hexdigest(),
        "summary_sha256": hashlib.sha256((out / "benchmark_summary.json").read_bytes()).hexdigest(),
        "matrix_sha256": hashlib.sha256(matrix.read_bytes()).hexdigest(),
    }
    receipt = coalition_receipt(body)
    (out / "benchmark_receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return {"rows": rows, "manifest": manifest, "summary": summary, "receipt": receipt}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()
    result = run_benchmark(args.output)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
