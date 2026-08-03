from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXPERIMENT_COST = {
    "observe_XY": Fraction(1),
    "do_X_0": Fraction(3),
    "do_X_1": Fraction(3),
}


def fdata(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bit(code: int, index: int) -> int:
    return (code >> index) & 1


def enumerate_models() -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for x_code in range(4):
        for y_code in range(16):
            observational = [Fraction(0) for _ in range(4)]
            do0 = [Fraction(0), Fraction(0)]
            do1 = [Fraction(0), Fraction(0)]
            for latent in (0, 1):
                probability = Fraction(1, 2)
                x_value = bit(x_code, latent)
                y_value = bit(y_code, 2 * x_value + latent)
                observational[2 * x_value + y_value] += probability
                do0[bit(y_code, latent)] += probability
                do1[bit(y_code, 2 + latent)] += probability
            effect = do1[1] - do0[1]
            models.append(
                {
                    "name": f"fx{x_code:02d}_fy{y_code:02d}",
                    "x_mechanism": [bit(x_code, 0), bit(x_code, 1)],
                    "y_mechanism": [
                        bit(y_code, index) for index in range(4)
                    ],
                    "observe_XY": tuple(observational),
                    "do_X_0": tuple(do0),
                    "do_X_1": tuple(do1),
                    "effect": effect,
                    "positive_effect": effect > 0,
                }
            )
    return models


def signature(law: tuple[Fraction, ...]) -> str:
    return "|".join(
        f"{value.numerator}/{value.denominator}" for value in law
    )


def conflict_pairs(
    hypotheses: tuple[str, ...], target: dict[str, bool]
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (left, right)
        for left, right in combinations(sorted(hypotheses), 2)
        if target[left] != target[right]
    )


def separates(
    laws: dict[str, dict[str, str]],
    experiment: str,
    pair: tuple[str, str],
) -> bool:
    return laws[experiment][pair[0]] != laws[experiment][pair[1]]


def obstruction(
    hypotheses: tuple[str, ...],
    target: dict[str, bool],
    laws: dict[str, dict[str, str]],
    experiments: tuple[str, ...],
    belief: frozenset[str] | None = None,
) -> tuple[str, str] | None:
    candidates = sorted(hypotheses if belief is None else belief)
    for left, right in combinations(candidates, 2):
        if target[left] == target[right]:
            continue
        if not any(
            separates(laws, experiment, (left, right))
            for experiment in experiments
        ):
            return left, right
    return None


def exact_fixed_basis(
    hypotheses: tuple[str, ...],
    target: dict[str, bool],
    laws: dict[str, dict[str, str]],
    experiments: tuple[str, ...],
) -> tuple[Fraction, tuple[str, ...]] | None:
    conflicts = conflict_pairs(hypotheses, target)
    best: tuple[Fraction, int, tuple[str, ...]] | None = None
    for size in range(1, len(experiments) + 1):
        for selected in combinations(sorted(experiments), size):
            if all(
                any(
                    separates(laws, experiment, pair)
                    for experiment in selected
                )
                for pair in conflicts
            ):
                candidate = (
                    sum(
                        (EXPERIMENT_COST[name] for name in selected),
                        Fraction(0),
                    ),
                    size,
                    selected,
                )
                if best is None or candidate < best:
                    best = candidate
    if best is None:
        return None
    return best[0], best[2]


def optimal_policy(
    hypotheses: tuple[str, ...],
    target: dict[str, bool],
    laws: dict[str, dict[str, str]],
    experiments: tuple[str, ...],
) -> dict[str, object]:
    prior = {
        hypothesis: Fraction(1, len(hypotheses))
        for hypothesis in hypotheses
    }

    def mass(belief: frozenset[str]) -> Fraction:
        return sum((prior[hypothesis] for hypothesis in belief), Fraction(0))

    @lru_cache(maxsize=None)
    def solve(
        belief: frozenset[str],
    ) -> tuple[bool, Fraction, Fraction, dict[str, object]]:
        values = {target[hypothesis] for hypothesis in belief}
        if len(values) == 1:
            return (
                True,
                Fraction(0),
                Fraction(0),
                {
                    "belief": sorted(belief),
                    "status": "TRUE" if True in values else "FALSE",
                },
            )

        belief_mass = mass(belief)
        candidates: list[
            tuple[Fraction, Fraction, str, dict[str, object]]
        ] = []
        for experiment in sorted(experiments):
            groups: dict[str, frozenset[str]] = {}
            for hypothesis in belief:
                observation = laws[experiment][hypothesis]
                groups.setdefault(observation, frozenset())
                groups[observation] = groups[observation] | {
                    hypothesis
                }
            if len(groups) <= 1:
                continue
            children: dict[str, dict[str, object]] = {}
            child_worst: list[Fraction] = []
            expected = EXPERIMENT_COST[experiment]
            exact = True
            for observation in sorted(groups):
                child_belief = groups[observation]
                child_exact, worst, child_expected, node = solve(
                    child_belief
                )
                if not child_exact:
                    exact = False
                    break
                children[observation] = node
                child_worst.append(worst)
                expected += (
                    mass(child_belief) / belief_mass * child_expected
                )
            if exact:
                worst = EXPERIMENT_COST[experiment] + max(
                    child_worst, default=Fraction(0)
                )
                candidates.append(
                    (
                        worst,
                        expected,
                        experiment,
                        {
                            "belief": sorted(belief),
                            "status": "UNKNOWN",
                            "experiment": experiment,
                            "children": children,
                        },
                    )
                )
        if candidates:
            worst, expected, _, tree = min(
                candidates, key=lambda item: item[:3]
            )
            return True, worst, expected, tree
        witness = obstruction(
            hypotheses, target, laws, experiments, belief
        )
        return (
            False,
            Fraction(0),
            Fraction(0),
            {
                "belief": sorted(belief),
                "status": "IMPOSSIBLE",
                "obstruction": None
                if witness is None
                else list(witness),
            },
        )

    exact, worst, expected, tree = solve(frozenset(hypotheses))
    return {
        "exact": exact,
        "worst_cost": fdata(worst),
        "expected_cost": fdata(expected),
        "tree": tree,
    }


def build_certificate() -> dict[str, object]:
    models = enumerate_models()
    hypotheses = tuple(str(model["name"]) for model in models)
    target = {
        str(model["name"]): bool(model["positive_effect"])
        for model in models
    }
    laws = {
        experiment: {
            str(model["name"]): signature(model[experiment])
            for model in models
        }
        for experiment in EXPERIMENT_COST
    }
    observational_experiments = ("observe_XY",)
    all_experiments = tuple(EXPERIMENT_COST)
    observational_witness = obstruction(
        hypotheses,
        target,
        laws,
        observational_experiments,
    )
    fixed = exact_fixed_basis(
        hypotheses, target, laws, all_experiments
    )
    policy = optimal_policy(
        hypotheses, target, laws, all_experiments
    )
    if observational_witness is None or fixed is None:
        raise AssertionError("expected obstruction and exact basis")
    effect_counts: dict[str, int] = {}
    for model in models:
        key = str(model["effect"])
        effect_counts[key] = effect_counts.get(key, 0) + 1
    payload = {
        "schema": (
            "inference-power-compiler/"
            "finite-scm-public-independent-certificate/1"
        ),
        "models": [
            {
                "name": model["name"],
                "x_mechanism": model["x_mechanism"],
                "y_mechanism": model["y_mechanism"],
                "observe_XY": signature(model["observe_XY"]),
                "do_X_0": signature(model["do_X_0"]),
                "do_X_1": signature(model["do_X_1"]),
                "effect": str(model["effect"]),
                "positive_effect": model["positive_effect"],
            }
            for model in models
        ],
        "analysis": {
            "model_count": len(models),
            "effect_counts": dict(sorted(effect_counts.items())),
            "positive_effect_models": sum(target.values()),
            "nonpositive_effect_models": len(models) - sum(target.values()),
            "conflict_pairs": len(conflict_pairs(hypotheses, target)),
            "observational_obstruction": list(
                observational_witness
            ),
            "fixed_basis": list(fixed[1]),
            "fixed_basis_cost": fdata(fixed[0]),
            "optimal_policy": policy,
        },
    }
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(
    certificate: dict[str, object]
) -> list[str]:
    payload = certificate.get("payload")
    certificate_hash = certificate.get("sha256")
    if not isinstance(payload, dict) or not isinstance(
        certificate_hash, str
    ):
        return ["certificate-shape"]
    if digest(payload) != certificate_hash:
        return ["payload-hash"]
    rebuilt = build_certificate()
    if canonical_json(rebuilt["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []


def main() -> None:
    certificate = build_certificate()
    errors = verify_certificate(certificate)
    if errors:
        raise AssertionError(f"certificate replay failed: {errors}")
    analysis = certificate["payload"]["analysis"]
    expected = {
        "model_count": 64,
        "effect_counts": {
            "-1": 4,
            "-1/2": 16,
            "0": 24,
            "1": 4,
            "1/2": 16,
        },
        "positive_effect_models": 20,
        "nonpositive_effect_models": 44,
        "conflict_pairs": 880,
        "observational_obstruction": [
            "fx00_fy00",
            "fx00_fy04",
        ],
        "fixed_basis": ["do_X_0", "do_X_1"],
        "fixed_basis_cost": [6, 1],
    }
    for key, value in expected.items():
        if analysis[key] != value:
            raise AssertionError(
                f"{key}: expected {value!r}, got {analysis[key]!r}"
            )
    policy = analysis["optimal_policy"]
    if (
        policy["tree"]["experiment"] != "do_X_0"
        or policy["worst_cost"] != [6, 1]
        or policy["expected_cost"] != [21, 4]
    ):
        raise AssertionError("adaptive causal policy mismatch")

    tampered = copy.deepcopy(certificate)
    tampered["payload"]["models"][0]["positive_effect"] = True
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("tampered SCM certificate was accepted")

    report = {
        "schema": (
            "inference-power-compiler/"
            "finite-scm-public-independent-report/1"
        ),
        "model_class": (
            "all 64 deterministic binary X->Y SCMs with shared "
            "binary latent U"
        ),
        "query": (
            "P(Y=1|do(X=1))-P(Y=1|do(X=0))>0"
        ),
        "analysis": {
            **analysis,
            "expected_cost_reduction": [1, 8],
            "expected_cost_reduction_percent": 12.5,
        },
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "boundary": (
            "finite deterministic binary SCMs with exact rational "
            "latent law; no continuous variables, graph discovery, "
            "general do-calculus, or finite-sample causal estimation"
        ),
    }
    report["sha256"] = digest(report)
    (ROOT / "FINITE_SCM_PUBLIC_CERTIFICATE.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ROOT / "FINITE_SCM_PUBLIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
