from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from typing import Mapping, Sequence
ROOT = Path(__file__).resolve().parent
MECHANISMS = ('0000', '0101', '1010', '0110')
MIXES = (Fraction(1, 4), Fraction(3, 4))
FREE = 'source_stratified_trial'
COST = {'target_covariate_mix': Fraction(1), 'mechanism_invariance_audit': Fraction(2), 'target_population_trial': Fraction(8)}
PAID = tuple(sorted(COST))
BUDGETS = tuple((Fraction(value) for value in (0, 2, 3, 8, 10)))
Policy = tuple[object, ...]

def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()

def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]

def effects(mechanism: str) -> tuple[int, int]:
    if len(mechanism) != 4 or any((bit not in '01' for bit in mechanism)):
        raise ValueError('bad mechanism')
    return (int(mechanism[1]) - int(mechanism[0]), int(mechanism[3]) - int(mechanism[2]))

def ace(mechanism: str, p1: Fraction) -> Fraction:
    effect0, effect1 = effects(mechanism)
    return (1 - p1) * effect0 + p1 * effect1

def policy_data(policy: Policy) -> object:
    if policy[0] == 'stop':
        return ['stop']
    return ['ask', policy[1], [[observation, policy_data(child)] for observation, child in policy[2]]]

@dataclass(frozen=True)
class Candidate:
    worst_width: Fraction
    expected_width: Fraction
    worst_cost: Fraction
    expected_cost: Fraction
    policy: Policy

    def metrics(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        return (self.worst_width, self.expected_width, self.worst_cost, self.expected_cost)

    def data(self) -> dict[str, object]:
        encoded = policy_data(self.policy)
        return {'worst_width': q(self.worst_width), 'expected_width': q(self.expected_width), 'worst_cost': q(self.worst_cost), 'expected_cost': q(self.expected_cost), 'policy': encoded, 'policy_sha256': digest(encoded)}

def dominates(left: Candidate, right: Candidate) -> bool:
    a, b = (left.metrics(), right.metrics())
    return all((x <= y for x, y in zip(a, b))) and any((x < y for x, y in zip(a, b)))

def pareto(candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
    by_metrics: dict[tuple[Fraction, ...], Candidate] = {}
    for candidate in candidates:
        key = candidate.metrics()
        incumbent = by_metrics.get(key)
        if incumbent is None or canonical(policy_data(candidate.policy)) < canonical(policy_data(incumbent.policy)):
            by_metrics[key] = candidate
    unique = tuple(by_metrics.values())
    frontier = [candidate for candidate in unique if not any((other is not candidate and dominates(other, candidate) for other in unique))]
    return tuple(sorted(frontier, key=lambda item: (item.expected_width, item.worst_width, item.expected_cost, item.worst_cost, canonical(policy_data(item.policy)))))

class Planner:

    def __init__(self, *, invariant_only: bool=False, include_target_trial: bool=True) -> None:
        worlds: list[str] = []
        target: dict[str, Fraction] = {}
        prior: dict[str, Fraction] = {}
        observations: dict[str, dict[str, str]] = {FREE: {}, 'target_covariate_mix': {}, 'mechanism_invariance_audit': {}}
        if include_target_trial:
            observations['target_population_trial'] = {}
        for source, target_mechanism, p1 in product(MECHANISMS, MECHANISMS, MIXES):
            if invariant_only and source != target_mechanism:
                continue
            name = f'S{source}_T{target_mechanism}_P{p1.numerator}{p1.denominator}'
            invariant = source == target_mechanism
            worlds.append(name)
            target[name] = ace(target_mechanism, p1)
            prior[name] = Fraction(1, len(MECHANISMS)) * Fraction(1, len(MIXES)) * (Fraction(3, 4) if invariant else Fraction(1, 12))
            observations[FREE][name] = source
            observations['target_covariate_mix'][name] = f'P_target_Z1={p1.numerator}/{p1.denominator}'
            observations['mechanism_invariance_audit'][name] = 'INVARIANT' if invariant else 'SHIFT'
            if include_target_trial:
                value = target[name]
                observations['target_population_trial'][name] = f'ACE={value.numerator}/{value.denominator}'
        total = sum(prior.values(), Fraction(0))
        self.worlds = tuple(worlds)
        self.target = target
        self.prior = {world: weight / total for world, weight in prior.items()}
        self.observations = observations
        self.paid = tuple(sorted((name for name in observations if name != FREE)))

    def mass(self, belief: Sequence[str]) -> Fraction:
        return sum((self.prior[world] for world in belief), Fraction(0))

    def interval(self, belief: Sequence[str]) -> tuple[Fraction, Fraction]:
        values = [self.target[world] for world in belief]
        return (min(values), max(values))

    def partition(self, belief: Sequence[str], experiment: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        groups: dict[str, list[str]] = {}
        for world in belief:
            groups.setdefault(self.observations[experiment][world], []).append(world)
        return tuple(((observation, tuple(sorted(group))) for observation, group in sorted(groups.items())))

    def state_frontier(self, belief: Sequence[str], available: Sequence[str], budget: Fraction) -> tuple[Candidate, ...]:

        @lru_cache(maxsize=None)
        def solve(current: tuple[str, ...], remaining: tuple[str, ...], resource: Fraction) -> tuple[Candidate, ...]:
            lower, upper = self.interval(current)
            width = upper - lower
            candidates = [Candidate(width, width, Fraction(0), Fraction(0), ('stop',))]
            current_mass = self.mass(current)
            for experiment in remaining:
                cost = COST[experiment]
                if cost > resource:
                    continue
                groups = self.partition(current, experiment)
                if len(groups) <= 1:
                    continue
                next_remaining = tuple((name for name in remaining if name != experiment))
                child_frontiers = tuple((solve(group, next_remaining, resource - cost) for _observation, group in groups))
                for children in product(*child_frontiers):
                    candidates.append(Candidate(max((child.worst_width for child in children)), sum((self.mass(group) / current_mass * child.expected_width for (_observation, group), child in zip(groups, children))), cost + max((child.worst_cost for child in children)), cost + sum((self.mass(group) / current_mass * child.expected_cost for (_observation, group), child in zip(groups, children))), ('ask', experiment, tuple(((observation, child.policy) for (observation, _group), child in zip(groups, children))))))
            return pareto(candidates)
        return solve(tuple(sorted(belief)), tuple(sorted(available)), budget)

    def frontier(self, budget: Fraction, paid: Sequence[str] | None=None) -> tuple[Candidate, ...]:
        available = self.paid if paid is None else tuple(paid)
        groups = self.partition(self.worlds, FREE)
        child_frontiers = tuple((self.state_frontier(group, available, budget) for _observation, group in groups))
        candidates = []
        for children in product(*child_frontiers):
            candidates.append(Candidate(max((child.worst_width for child in children)), sum((self.mass(group) * child.expected_width for (_observation, group), child in zip(groups, children))), max((child.worst_cost for child in children)), sum((self.mass(group) * child.expected_cost for (_observation, group), child in zip(groups, children))), ('free', FREE, tuple(((observation, child.policy) for (observation, _group), child in zip(groups, children))))))
        return pareto(candidates)

    def replay(self, candidate: Candidate, budget: Fraction, paid: Sequence[str] | None=None) -> Candidate:
        available = frozenset(self.paid if paid is None else paid)

        def visit(policy: Policy, belief: tuple[str, ...], remaining: frozenset[str], resource: Fraction) -> Candidate:
            lower, upper = self.interval(belief)
            width = upper - lower
            if policy == ('stop',):
                return Candidate(width, width, Fraction(0), Fraction(0), policy)
            if len(policy) != 3 or policy[0] != 'ask' or policy[1] not in remaining:
                raise AssertionError('invalid transport policy')
            experiment = policy[1]
            cost = COST[experiment]
            if cost > resource:
                raise AssertionError('transport policy exceeds budget')
            groups = self.partition(belief, experiment)
            children = policy[2]
            if tuple((observation for observation, _child in children)) != tuple((observation for observation, _group in groups)):
                raise AssertionError('transport policy support mismatch')
            replayed = tuple((visit(child, group, remaining - {experiment}, resource - cost) for (observation, child), (_expected, group) in zip(children, groups)))
            current_mass = self.mass(belief)
            return Candidate(max((child.worst_width for child in replayed)), sum((self.mass(group) / current_mass * child.expected_width for (_observation, group), child in zip(groups, replayed))), cost + max((child.worst_cost for child in replayed)), cost + sum((self.mass(group) / current_mass * child.expected_cost for (_observation, group), child in zip(groups, replayed))), policy)
        policy = candidate.policy
        groups = self.partition(self.worlds, FREE)
        if len(policy) != 3 or policy[0] != 'free' or policy[1] != FREE:
            raise AssertionError('missing free source-trial root')
        children = policy[2]
        if tuple((observation for observation, _child in children)) != tuple((observation for observation, _group in groups)):
            raise AssertionError('free transport root mismatch')
        replayed = tuple((visit(child, group, available, budget) for (observation, child), (_expected, group) in zip(children, groups)))
        rebuilt = Candidate(max((child.worst_width for child in replayed)), sum((self.mass(group) * child.expected_width for (_observation, group), child in zip(groups, replayed))), max((child.worst_cost for child in replayed)), sum((self.mass(group) * child.expected_cost for (_observation, group), child in zip(groups, replayed))), policy)
        if rebuilt.metrics() != candidate.metrics():
            raise AssertionError('claimed transport metrics do not replay')
        return rebuilt

    def obstruction(self, experiments: Sequence[str]) -> dict[str, object] | None:
        candidates = []
        for left, right in combinations(sorted(self.worlds), 2):
            if self.target[left] == self.target[right]:
                continue
            if all((self.observations[name][left] == self.observations[name][right] for name in experiments)):
                candidates.append({'left': left, 'right': right, 'left_target': q(self.target[left]), 'right_target': q(self.target[right]), 'signatures': {name: self.observations[name][left] for name in experiments}})
        return None if not candidates else min(candidates, key=lambda item: (item['left'], item['right']))

def best(frontier: Sequence[Candidate]) -> Candidate:
    return min(frontier, key=lambda item: (item.expected_width, item.worst_width, item.expected_cost, item.worst_cost, canonical(policy_data(item.policy))))

def minimum_exact(frontier: Sequence[Candidate], *, worst: bool) -> Candidate | None:
    exact = [item for item in frontier if item.worst_width == 0 and item.expected_width == 0]
    if not exact:
        return None
    if worst:
        return min(exact, key=lambda item: (item.worst_cost, item.expected_cost, canonical(policy_data(item.policy))))
    return min(exact, key=lambda item: (item.expected_cost, item.worst_cost, canonical(policy_data(item.policy))))

def build_payload() -> dict[str, object]:
    full = Planner()
    expected = {Fraction(0): (1, (Fraction(2), Fraction(2), Fraction(0), Fraction(0))), Fraction(2): (5, (Fraction(2), Fraction(5, 8), Fraction(2), Fraction(2))), Fraction(3): (15, (Fraction(2), Fraction(13, 32), Fraction(3), Fraction(37, 16))), Fraction(8): (24, (Fraction(0), Fraction(0), Fraction(8), Fraction(8))), Fraction(10): (47, (Fraction(0), Fraction(0), Fraction(10), Fraction(67, 16)))}
    packets = []
    for budget in BUDGETS:
        current = full.frontier(budget)
        selected = best(current)
        full.replay(selected, budget)
        expected_size, expected_metrics = expected[budget]
        if len(current) != expected_size or selected.metrics() != expected_metrics:
            raise AssertionError(f'public transport budget {budget} changed')
        exact_expected = minimum_exact(current, worst=False)
        exact_worst = minimum_exact(current, worst=True)
        packets.append({'budget': q(budget), 'frontier_metrics': [[q(metric) for metric in item.metrics()] for item in current], 'selected': selected.data(), 'minimum_expected_cost_exact': None if exact_expected is None else exact_expected.data(), 'minimum_worst_cost_exact': None if exact_worst is None else exact_worst.data()})
    frontier10 = full.frontier(Fraction(10))
    exact_expected = minimum_exact(frontier10, worst=False)
    exact_worst = minimum_exact(frontier10, worst=True)
    if exact_expected is None or exact_worst is None:
        raise AssertionError('public exact transport policies missing')
    if exact_expected.metrics() != (Fraction(0), Fraction(0), Fraction(10), Fraction(67, 16)):
        raise AssertionError('public adaptive exact transport changed')
    if exact_worst.metrics() != (Fraction(0), Fraction(0), Fraction(8), Fraction(8)):
        raise AssertionError('public fixed exact transport changed')
    forged_policy = Candidate(exact_expected.worst_width, exact_expected.expected_width, exact_expected.worst_cost, Fraction(0), exact_expected.policy)
    try:
        full.replay(forged_policy, Fraction(10))
    except AssertionError:
        policy_tamper = 'REJECTED:semantic-replay'
    else:
        raise AssertionError('public forged transport metrics accepted')
    no_trial = Planner(include_target_trial=False)
    obstruction = no_trial.obstruction((FREE, 'target_covariate_mix', 'mechanism_invariance_audit'))
    if obstruction is None or (obstruction['left'], obstruction['right']) != ('S0000_T0101_P14', 'S0000_T0110_P14'):
        raise AssertionError(f'public transport obstruction changed: {obstruction}')
    invariant = Planner(invariant_only=True, include_target_trial=False)
    invariant_before = best(invariant.frontier(Fraction(0), ('target_covariate_mix',)))
    invariant_frontier = invariant.frontier(Fraction(1), ('target_covariate_mix',))
    invariant_exact = minimum_exact(invariant_frontier, worst=False)
    if invariant_before.metrics() != (Fraction(1), Fraction(1, 4), Fraction(0), Fraction(0)):
        raise AssertionError('public invariant pre-mix boundary changed')
    if invariant_exact is None or invariant_exact.metrics() != (Fraction(0), Fraction(0), Fraction(1), Fraction(1, 4)):
        raise AssertionError('public invariant exact transport changed')
    invariant.replay(invariant_exact, Fraction(1), ('target_covariate_mix',))
    return {'schema': 'inference-power-compiler/finite-transportability-public-certificate/1', 'family': {'worlds': len(full.worlds), 'mechanisms': list(MECHANISMS), 'target_mixes': [q(value) for value in MIXES], 'invariance_prior': [3, 4], 'mechanism_encoding': 'Y0(z=0),Y1(z=0),Y0(z=1),Y1(z=1)'}, 'budget_frontier': packets, 'exact_pareto_budget_10': {'minimum_expected_cost': exact_expected.data(), 'minimum_worst_cost': exact_worst.data(), 'non_dominance': 'PASS'}, 'invariance_closure': {'before_target_mix': invariant_before.data(), 'exact_policy': invariant_exact.data(), 'transport_formula': 'ACE_target=(1-p_target)·effect_source(z=0)+p_target·effect_source(z=1)', 'status': 'POINT_IDENTIFIED'}, 'mechanism_shift_boundary': {'status': 'NOT_POINT_IDENTIFIED_WITHOUT_TARGET_TRIAL', 'obstruction': obstruction}, 'power_gain': {'fixed_target_trial_expected_cost': [8, 1], 'adaptive_exact_expected_cost': [67, 16], 'adaptive_exact_worst_cost': [10, 1], 'expected_saving': [61, 16], 'expected_saving_fraction': [61, 128], 'invariant_exact_expected_cost': [1, 4]}, 'gates': {'complete_world_enumeration': 'PASS', 'transport_formula_under_invariance': 'PASS', 'mechanism_shift_obstruction': 'PASS', 'complete_finite_policy_search': 'PASS', 'pareto_frontier': 'PASS', 'selected_policy_replay': 'PASS', 'policy_tamper_rejection': policy_tamper}, 'scientific_boundary': 'Independent exact replay inside a finite binary mechanism family and no-repeat evidence grammar; not a general transportability or selection-diagram algorithm for arbitrary causal models.'}

def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {'payload': payload, 'sha256': digest(payload)}

def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload, claimed = (certificate.get('payload'), certificate.get('sha256'))
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ['shape']
    if digest(payload) != claimed:
        return ['payload-hash']
    if canonical(build_certificate()['payload']) != canonical(payload):
        return ['semantic-replay']
    return []

def build_report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate['payload']
    report = {'schema': 'inference-power-compiler/finite-transportability-public-report/1', 'family': payload['family'], 'budget_frontier': [{'budget': packet['budget'], 'frontier_size': len(packet['frontier_metrics']), 'selected': {key: packet['selected'][key] for key in ('worst_width', 'expected_width', 'worst_cost', 'expected_cost', 'policy_sha256')}, 'exact_available': packet['minimum_expected_cost_exact'] is not None} for packet in payload['budget_frontier']], 'exact_pareto_budget_10': payload['exact_pareto_budget_10'], 'invariance_closure': payload['invariance_closure'], 'mechanism_shift_boundary': payload['mechanism_shift_boundary'], 'power_gain': payload['power_gain'], 'gates': payload['gates'], 'certificate_sha256': certificate['sha256'], 'semantic_replay': 'PASS', 'tampered_certificate': 'REJECTED:payload-hash', 'forged_certificate': 'REJECTED:semantic-replay', 'scientific_boundary': payload['scientific_boundary']}
    report['sha256'] = digest(report)
    return report

def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError('public transport certificate failed self replay')
    tampered = deepcopy(certificate)
    tampered['payload']['power_gain']['adaptive_exact_expected_cost'] = [0, 1]
    if verify_certificate(tampered) != ['payload-hash']:
        raise AssertionError('public transport hash tamper accepted')
    forged = deepcopy(certificate)
    forged['payload']['power_gain']['adaptive_exact_expected_cost'] = [0, 1]
    forged['sha256'] = digest(forged['payload'])
    if verify_certificate(forged) != ['semantic-replay']:
        raise AssertionError('public transport semantic forgery accepted')
    report = build_report(certificate)
    write(ROOT / 'TRANSPORTABILITY_PUBLIC_CERTIFICATE.json', certificate)
    write(ROOT / 'TRANSPORTABILITY_PUBLIC_REPORT.json', report)
    print(json.dumps(report, indent=2, sort_keys=True))
if __name__ == '__main__':
    main()
