from __future__ import annotations

from fractions import Fraction
import tempfile
import unittest

from coalition_power import (
    ActionEvent,
    Claim,
    DelegationToken,
    MessageEvent,
    audit_claims,
    audit_collusion,
    digest,
    verify_coalition_receipt,
)
from benchmark import ARCHETYPES, DOMAINS, authorizer_fixture, check_domain, run_benchmark, stable_game, unstable_shapley_game


class AdversarialCoalitionPowerTests(unittest.TestCase):
    def test_all_preregistered_scenarios_pass(self) -> None:
        rows = [r for d in DOMAINS for r in check_domain(d)]
        self.assertEqual(len(rows), 72)
        self.assertTrue(all(r["passed"] for r in rows))

    def test_each_domain_has_all_archetypes_once(self) -> None:
        for domain in DOMAINS:
            rows = check_domain(domain)
            self.assertEqual(tuple(r["archetype"] for r in rows), ARCHETYPES)
            self.assertEqual(len({r["archetype"] for r in rows}), 12)

    def test_sybil_roots_are_deduplicated(self) -> None:
        auth, ctx = authorizer_fixture("research")
        from coalition_power import JointAction
        action = JointAction("research:act", [ctx["scope"]])
        decision = auth.authorize(action, [auth.approve("research:alice", action), auth.approve("research:alice_clone", action)])
        self.assertFalse(decision.allowed)
        self.assertEqual(len(decision.distinct_roots), 1)

    def test_scope_expansion_is_rejected(self) -> None:
        token = DelegationToken.issue_root(principal="p", subject="a", scopes=["read"], max_depth=1, nonce="n")
        with self.assertRaises(ValueError):
            token.delegate(subject="b", scopes=["read", "write"], nonce="x")

    def test_shapley_is_efficient_in_stable_game(self) -> None:
        game = stable_game("software")
        shapley = game.shapley()
        self.assertEqual(sum(shapley.values(), Fraction()), game.value(game.players))

    def test_shapley_can_lie_outside_core(self) -> None:
        game = unstable_shapley_game("finance")
        shapley = game.shapley()
        self.assertFalse(game.in_core(shapley))
        self.assertTrue(game.blocking_coalitions(shapley))

    def test_collusion_requires_harmful_action_not_text_only(self) -> None:
        text_only = audit_collusion(
            messages=[MessageEvent("a", "secret", "serve", "divert")],
            actions=[ActionEvent("a", "serve", 5, 0)],
            cooperative_optimum=5,
        )
        harmful = audit_collusion(
            messages=[MessageEvent("a", "secret", "serve", "divert")],
            actions=[ActionEvent("a", "divert", -1, 2)],
            cooperative_optimum=5,
        )
        self.assertTrue(text_only.textual_collusion)
        self.assertFalse(text_only.action_collusion)
        self.assertTrue(harmful.action_collusion)

    def test_claim_provenance_rejects_unsupported_contradiction(self) -> None:
        evidence = digest({"x": 1})
        audit = audit_claims([Claim("a", "p", "true", evidence), Claim("b", "p", "false", None)])
        self.assertFalse(audit["valid"])
        self.assertTrue(audit["unsupported"])
        self.assertEqual(audit["contradictions"], ("p",))

    def test_optimal_partition_is_exact(self) -> None:
        game = stable_game("logistics")
        partition, value = game.optimal_partition()
        self.assertEqual(value, 9)
        self.assertEqual(partition, (frozenset(game.players),))

    def test_receipt_is_deterministic_and_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = run_benchmark(a)["receipt"]
            second = run_benchmark(b)["receipt"]
            self.assertEqual(first, second)
            self.assertTrue(verify_coalition_receipt(first))
            tampered = dict(first)
            payload = dict(tampered["payload"])
            payload["passed"] = 71
            tampered["payload"] = payload
            self.assertFalse(verify_coalition_receipt(tampered))

    def test_manifest_order_is_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            result = run_benchmark(folder)
            ids = result["manifest"]["scenario_ids"]
            expected = [f"{d}::{a}" for d in DOMAINS for a in ARCHETYPES]
            self.assertEqual(ids, expected)
            self.assertEqual(len(ids), len(set(ids)))

    def test_evaluator_change_requires_independent_root(self) -> None:
        auth, ctx = authorizer_fixture("governance")
        from coalition_power import JointAction
        action = JointAction("governance:eval", [ctx["scope"]], evaluator_change=True)
        denied = auth.authorize(action, [auth.approve("governance:alice", action), auth.approve("governance:bob", action)])
        allowed = auth.authorize(action, [auth.approve("governance:alice", action), auth.approve("governance:auditor", action)])
        self.assertFalse(denied.allowed)
        self.assertTrue(allowed.allowed)


if __name__ == "__main__":
    unittest.main()
