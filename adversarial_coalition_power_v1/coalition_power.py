"""Exact finite calculus for authority-bounded adversarial coalition power.

Collective power is counted only when a coalition can create distinct value while
preserving delegation attenuation, identity uniqueness, evaluator independence,
trace provenance, coalition stability, and safe dissolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from math import factorial
from typing import Iterable, Mapping, Sequence
import hashlib
import json


def F(value: int | str | float | Fraction | tuple[int, int]) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, tuple):
        return Fraction(value[0], value[1])
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(value)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True, order=True)
class Agent:
    name: str
    root_identity: str
    capabilities: tuple[str, ...] = ()
    independent: bool = True

    def __init__(self, name: str, root_identity: str, capabilities: Iterable[str] = (), independent: bool = True):
        object.__setattr__(self, "name", str(name))
        object.__setattr__(self, "root_identity", str(root_identity))
        object.__setattr__(self, "capabilities", tuple(sorted(set(map(str, capabilities)))))
        object.__setattr__(self, "independent", bool(independent))


@dataclass(frozen=True)
class DelegationToken:
    issuer: str
    subject: str
    root_principal: str
    scopes: tuple[str, ...]
    depth_remaining: int
    parent_digest: str | None
    nonce: str
    signature: str

    @staticmethod
    def _body(
        issuer: str,
        subject: str,
        root_principal: str,
        scopes: Iterable[str],
        depth_remaining: int,
        parent_digest: str | None,
        nonce: str,
    ) -> dict[str, object]:
        return {
            "issuer": str(issuer),
            "subject": str(subject),
            "root_principal": str(root_principal),
            "scopes": sorted(set(map(str, scopes))),
            "depth_remaining": int(depth_remaining),
            "parent_digest": parent_digest,
            "nonce": str(nonce),
        }

    @classmethod
    def issue_root(
        cls,
        *,
        principal: str,
        subject: str,
        scopes: Iterable[str],
        max_depth: int,
        nonce: str,
    ) -> "DelegationToken":
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        body = cls._body(principal, subject, principal, scopes, max_depth, None, nonce)
        return cls(signature=digest(body), **{**body, "scopes": tuple(body["scopes"])})

    def token_digest(self) -> str:
        return digest({
            "issuer": self.issuer,
            "subject": self.subject,
            "root_principal": self.root_principal,
            "scopes": list(self.scopes),
            "depth_remaining": self.depth_remaining,
            "parent_digest": self.parent_digest,
            "nonce": self.nonce,
            "signature": self.signature,
        })

    def valid_signature(self) -> bool:
        body = self._body(
            self.issuer,
            self.subject,
            self.root_principal,
            self.scopes,
            self.depth_remaining,
            self.parent_digest,
            self.nonce,
        )
        return self.signature == digest(body)

    def delegate(self, *, subject: str, scopes: Iterable[str], nonce: str) -> "DelegationToken":
        child_scopes = tuple(sorted(set(map(str, scopes))))
        if self.depth_remaining <= 0:
            raise ValueError("delegation depth exhausted")
        if not set(child_scopes) <= set(self.scopes):
            raise ValueError("delegation cannot expand scopes")
        body = self._body(
            self.subject,
            subject,
            self.root_principal,
            child_scopes,
            self.depth_remaining - 1,
            self.token_digest(),
            nonce,
        )
        return DelegationToken(signature=digest(body), **{**body, "scopes": tuple(body["scopes"])})

    def authorizes(self, required_scopes: Iterable[str]) -> bool:
        return self.valid_signature() and set(map(str, required_scopes)) <= set(self.scopes)


@dataclass(frozen=True, order=True)
class Approval:
    agent: str
    root_identity: str
    token_digest: str
    action_digest: str


@dataclass(frozen=True)
class JointAction:
    name: str
    required_scopes: tuple[str, ...]
    high_impact: bool = False
    evaluator_change: bool = False

    def __init__(self, name: str, required_scopes: Iterable[str], high_impact: bool = False, evaluator_change: bool = False):
        object.__setattr__(self, "name", str(name))
        object.__setattr__(self, "required_scopes", tuple(sorted(set(map(str, required_scopes)))))
        object.__setattr__(self, "high_impact", bool(high_impact))
        object.__setattr__(self, "evaluator_change", bool(evaluator_change))

    def action_digest(self) -> str:
        return digest({
            "name": self.name,
            "required_scopes": list(self.required_scopes),
            "high_impact": self.high_impact,
            "evaluator_change": self.evaluator_change,
        })


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    distinct_roots: tuple[str, ...]


class CoalitionAuthorizer:
    def __init__(
        self,
        *,
        agents: Mapping[str, Agent],
        tokens: Mapping[str, DelegationToken],
        threshold: int,
        evaluator_roots: Iterable[str] = (),
        high_impact_threshold: int | None = None,
    ) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self.agents = dict(agents)
        self.tokens = dict(tokens)
        self.threshold = int(threshold)
        self.high_impact_threshold = int(high_impact_threshold or threshold)
        self.evaluator_roots = frozenset(map(str, evaluator_roots))

    def approve(self, agent_name: str, action: JointAction) -> Approval:
        agent = self.agents[agent_name]
        token = self.tokens[agent_name]
        return Approval(agent.name, agent.root_identity, token.token_digest(), action.action_digest())

    def authorize(self, action: JointAction, approvals: Iterable[Approval]) -> AuthorizationDecision:
        approvals = tuple(approvals)
        valid_roots: set[str] = set()
        independent_evaluator = False
        for approval in approvals:
            agent = self.agents.get(approval.agent)
            token = self.tokens.get(approval.agent)
            if agent is None or token is None:
                continue
            if approval.root_identity != agent.root_identity:
                continue
            if approval.token_digest != token.token_digest():
                continue
            if approval.action_digest != action.action_digest():
                continue
            if token.subject != agent.name or not token.authorizes(action.required_scopes):
                continue
            valid_roots.add(agent.root_identity)
            if agent.independent and agent.root_identity in self.evaluator_roots:
                independent_evaluator = True
        required = self.high_impact_threshold if action.high_impact else self.threshold
        if len(valid_roots) < required:
            return AuthorizationDecision(False, "INSUFFICIENT_DISTINCT_ROOTS", tuple(sorted(valid_roots)))
        if action.evaluator_change and not independent_evaluator:
            return AuthorizationDecision(False, "MISSING_INDEPENDENT_EVALUATOR", tuple(sorted(valid_roots)))
        return AuthorizationDecision(True, "AUTHORIZED", tuple(sorted(valid_roots)))


Coalition = frozenset[str]


class CoalitionGame:
    def __init__(self, players: Iterable[str], values: Mapping[Iterable[str], int | str | float | Fraction | tuple[int, int]]):
        self.players = tuple(sorted(set(map(str, players))))
        self.values: dict[Coalition, Fraction] = {frozenset(map(str, c)): F(v) for c, v in values.items()}
        self.values.setdefault(frozenset(), Fraction())
        for p in self.players:
            self.values.setdefault(frozenset({p}), Fraction())

    def value(self, coalition: Iterable[str]) -> Fraction:
        return self.values.get(frozenset(map(str, coalition)), Fraction())

    def shapley(self) -> dict[str, Fraction]:
        n = len(self.players)
        if n == 0:
            return {}
        result: dict[str, Fraction] = {}
        for player in self.players:
            others = tuple(p for p in self.players if p != player)
            total = Fraction()
            for size in range(len(others) + 1):
                for subset in combinations(others, size):
                    before = self.value(subset)
                    after = self.value((*subset, player))
                    weight = Fraction(factorial(size) * factorial(n - size - 1), factorial(n))
                    total += weight * (after - before)
            result[player] = total
        return result

    def blocking_coalitions(self, allocation: Mapping[str, int | str | float | Fraction | tuple[int, int]]) -> tuple[Coalition, ...]:
        pay = {p: F(allocation[p]) for p in self.players}
        blockers: list[Coalition] = []
        for size in range(1, len(self.players) + 1):
            for subset in combinations(self.players, size):
                coalition = frozenset(subset)
                if self.value(coalition) > sum((pay[p] for p in coalition), Fraction()):
                    blockers.append(coalition)
        return tuple(sorted(blockers, key=lambda c: (len(c), tuple(sorted(c)))))

    def in_core(self, allocation: Mapping[str, int | str | float | Fraction | tuple[int, int]]) -> bool:
        pay = {p: F(allocation[p]) for p in self.players}
        efficient = sum(pay.values(), Fraction()) == self.value(self.players)
        individually_rational = all(pay[p] >= self.value({p}) for p in self.players)
        return efficient and individually_rational and not self.blocking_coalitions(pay)

    @staticmethod
    def _partitions(items: tuple[str, ...]) -> tuple[tuple[Coalition, ...], ...]:
        if not items:
            return ((),)
        first = items[0]
        rest = CoalitionGame._partitions(items[1:])
        out: set[tuple[Coalition, ...]] = set()
        for partition in rest:
            out.add(tuple(sorted((frozenset({first}), *partition), key=lambda c: tuple(sorted(c)))))
            for index in range(len(partition)):
                merged = list(partition)
                merged[index] = frozenset(set(merged[index]) | {first})
                out.add(tuple(sorted(merged, key=lambda c: tuple(sorted(c)))))
        return tuple(sorted(out, key=lambda part: (len(part), tuple(tuple(sorted(c)) for c in part))))

    def optimal_partition(self) -> tuple[tuple[Coalition, ...], Fraction]:
        best_partition: tuple[Coalition, ...] = ()
        best_value: Fraction | None = None
        for partition in self._partitions(self.players):
            welfare = sum((self.value(c) for c in partition), Fraction())
            key = (welfare, -len(partition), tuple(tuple(sorted(c)) for c in partition))
            best_key = None if best_value is None else (best_value, -len(best_partition), tuple(tuple(sorted(c)) for c in best_partition))
            if best_key is None or key > best_key:
                best_partition, best_value = partition, welfare
        return best_partition, best_value or Fraction()


class RobustCoalitionGame:
    def __init__(self, worlds: Mapping[str, CoalitionGame]):
        if not worlds:
            raise ValueError("at least one world is required")
        player_sets = {game.players for game in worlds.values()}
        if len(player_sets) != 1:
            raise ValueError("worlds must share the same players")
        self.worlds = dict(sorted(worlds.items()))
        self.players = next(iter(player_sets))

    def nominal_value(self, coalition: Iterable[str], world: str) -> Fraction:
        return self.worlds[world].value(coalition)

    def robust_value(self, coalition: Iterable[str]) -> Fraction:
        return min(game.value(coalition) for game in self.worlds.values())

    def robust_optimal_partition(self) -> tuple[tuple[Coalition, ...], Fraction]:
        partitions = CoalitionGame._partitions(self.players)
        best: tuple[tuple[object, ...], tuple[Coalition, ...], Fraction] | None = None
        for partition in partitions:
            world_values = [sum((game.value(c) for c in partition), Fraction()) for game in self.worlds.values()]
            worst = min(world_values)
            key = (worst, -len(partition), tuple(tuple(sorted(c)) for c in partition))
            if best is None or key > best[0]:
                best = (key, partition, worst)
        assert best is not None
        return best[1], best[2]


@dataclass(frozen=True, order=True)
class MessageEvent:
    sender: str
    channel: str
    declared_goal: str
    hidden_goal: str | None = None


@dataclass(frozen=True, order=True)
class ActionEvent:
    actor: str
    action: str
    principal_value: Fraction
    coalition_private_value: Fraction

    def __init__(self, actor: str, action: str, principal_value: int | str | float | Fraction, coalition_private_value: int | str | float | Fraction):
        object.__setattr__(self, "actor", str(actor))
        object.__setattr__(self, "action", str(action))
        object.__setattr__(self, "principal_value", F(principal_value))
        object.__setattr__(self, "coalition_private_value", F(coalition_private_value))


@dataclass(frozen=True)
class CollusionAudit:
    textual_collusion: bool
    action_collusion: bool
    principal_regret: Fraction
    private_gain: Fraction
    colluding_agents: tuple[str, ...]


def audit_collusion(
    *,
    messages: Iterable[MessageEvent],
    actions: Iterable[ActionEvent],
    cooperative_optimum: int | str | float | Fraction,
) -> CollusionAudit:
    messages = tuple(messages)
    actions = tuple(actions)
    hidden = tuple(sorted({m.sender for m in messages if m.hidden_goal is not None and m.hidden_goal != m.declared_goal}))
    textual = bool(hidden)
    actual = sum((a.principal_value for a in actions), Fraction())
    private_gain = sum((a.coalition_private_value for a in actions), Fraction())
    regret = max(F(cooperative_optimum) - actual, Fraction())
    action_agents = tuple(sorted({a.actor for a in actions if a.coalition_private_value > 0 and a.principal_value < 0}))
    action_collusion = bool(action_agents) and regret > 0 and private_gain > 0
    return CollusionAudit(textual, action_collusion, regret, private_gain, tuple(sorted(set(hidden) | set(action_agents))))


@dataclass(frozen=True, order=True)
class Claim:
    agent: str
    proposition: str
    value: str
    evidence_digest: str | None


def audit_claims(claims: Iterable[Claim]) -> dict[str, object]:
    claims = tuple(claims)
    unsupported = tuple(sorted((c.agent, c.proposition) for c in claims if not c.evidence_digest))
    grouped: dict[str, set[str]] = {}
    for claim in claims:
        grouped.setdefault(claim.proposition, set()).add(claim.value)
    contradictions = tuple(sorted(prop for prop, values in grouped.items() if len(values) > 1))
    valid = not unsupported and not contradictions
    return {"valid": valid, "unsupported": unsupported, "contradictions": contradictions}


@dataclass(frozen=True)
class DissolutionDecision:
    proceed: bool
    rollback: bool
    reason: str


def safe_dissolution(
    *,
    action: JointAction,
    authorizer: CoalitionAuthorizer,
    approvals: Iterable[Approval],
    withdrawn_agents: Iterable[str],
    rollback_available: bool,
) -> DissolutionDecision:
    withdrawn = set(map(str, withdrawn_agents))
    remaining = tuple(a for a in approvals if a.agent not in withdrawn)
    decision = authorizer.authorize(action, remaining)
    if decision.allowed:
        return DissolutionDecision(True, False, "REAUTHORIZED_WITH_REMAINING_COALITION")
    if rollback_available:
        return DissolutionDecision(False, True, "HALT_AND_ROLLBACK")
    return DissolutionDecision(False, False, "HALT_UNRECOVERABLE")


def coalition_receipt(payload: Mapping[str, object]) -> dict[str, object]:
    body = {"schema": "adversarial-coalition-power/receipt/1", "payload": payload}
    return {**body, "sha256": digest(body)}


def verify_coalition_receipt(receipt: Mapping[str, object]) -> bool:
    if receipt.get("schema") != "adversarial-coalition-power/receipt/1":
        return False
    body = {"schema": receipt["schema"], "payload": receipt.get("payload")}
    return receipt.get("sha256") == digest(body)
