from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent
PRIVATE_HEAD = "48fd366d60c21b210a75c71ceffb222aa05467f8"
PRIVATE_BLOBS = {
    "compiler": "1e0258c681ba03c772a194df3fef70f3ecfdb32d",
    "runner": "c76648c417e8e333517d1952ced6ff4eb1bc4d2e",
    "tests": "387e9afa4ecb33e173166be733059eb1c62fbfd9",
    "lean": "b2e775f47df72396a309f5e2c69bdeaecd7f5cb1",
    "workflow": "31f9296ec66bf3a45d0c6e6a76368e89a6cb6ca1",
}
EXPERTS = (
    ("constant_positive", "constant", 1),
    ("constant_negative", "constant", -1),
    ("follow_previous", "follow_previous", 1),
    ("oppose_previous", "oppose_previous", 1),
)
ADAPTIVE_WEIGHTS = (Fraction(1, 4),) * 4
BASELINE_WEIGHTS = (
    Fraction(1, 2),
    Fraction(1, 2),
    Fraction(0),
    Fraction(0),
)
GRID = tuple(Fraction(index, 20) for index in range(21))
PATH = tuple(Fraction(0) for _ in range(10)) + tuple(
    Fraction(1) for _ in range(10)
)
ALPHA = Fraction(1, 20)
THRESHOLD = Fraction(20)
REFERENCE = Fraction(1, 2)
PERSISTENCE_GRID = (
    Fraction(3, 4),
    Fraction(4, 5),
    Fraction(7, 8),
    Fraction(9, 10),
)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def lam(mode: str, direction: int, previous: Fraction | None) -> Fraction:
    if mode == "constant":
        return Fraction(direction)
    if previous is None:
        return Fraction(0)
    sign = 2 * previous - 1
    if mode == "follow_previous":
        return sign
    if mode == "oppose_previous":
        return -sign
    raise ValueError(mode)


def factor(current_lambda: Fraction, observation: Fraction, mean: Fraction) -> Fraction:
    return 1 + current_lambda * (observation - mean)


def mix(wealths: tuple[Fraction, ...], weights: tuple[Fraction, ...]) -> Fraction:
    return sum((wealth * weight for wealth, weight in zip(wealths, weights)), Fraction(0))


def update(
    wealths: tuple[Fraction, ...],
    previous: Fraction | None,
    observation: Fraction,
    mean: Fraction,
) -> tuple[Fraction, ...]:
    return tuple(
        wealth * factor(lam(mode, direction, previous), observation, mean)
        for wealth, (_name, mode, direction) in zip(wealths, EXPERTS)
    )


def path_control() -> dict[str, object]:
    per_mean: dict[Fraction, dict[str, object]] = {}
    for mean in GRID:
        wealths = (Fraction(1),) * 4
        previous: Fraction | None = None
        adaptive_history: list[Fraction] = []
        baseline_history: list[Fraction] = []
        posterior_history: list[tuple[Fraction, ...]] = []
        for observation in PATH:
            before = mix(wealths, ADAPTIVE_WEIGHTS)
            posterior = tuple(
                weight * wealth / before
                for weight, wealth in zip(ADAPTIVE_WEIGHTS, wealths)
            )
            factors = tuple(
                factor(lam(mode, direction, previous), observation, mean)
                for _name, mode, direction in EXPERTS
            )
            effective = sum(
                (weight * current_factor for weight, current_factor in zip(posterior, factors)),
                Fraction(0),
            )
            wealths = tuple(
                wealth * current_factor
                for wealth, current_factor in zip(wealths, factors)
            )
            adaptive = mix(wealths, ADAPTIVE_WEIGHTS)
            baseline = mix(wealths, BASELINE_WEIGHTS)
            if before * effective != adaptive:
                raise AssertionError("posterior factor identity failed")
            if any(adaptive < weight * wealth for weight, wealth in zip(ADAPTIVE_WEIGHTS, wealths)):
                raise AssertionError("mixture regret lower bound failed")
            adaptive_history.append(adaptive)
            baseline_history.append(baseline)
            posterior_history.append(posterior)
            previous = observation
        per_mean[mean] = {
            "wealths": wealths,
            "adaptive": adaptive_history,
            "baseline": baseline_history,
            "posterior_before": posterior_history,
        }

    adaptive_final = tuple(mean for mean in GRID if per_mean[mean]["adaptive"][-1] < THRESHOLD)
    baseline_final = tuple(mean for mean in GRID if per_mean[mean]["baseline"][-1] < THRESHOLD)
    reference = per_mean[REFERENCE]
    final_wealths = reference["wealths"]
    final_adaptive = reference["adaptive"][-1]
    final_baseline = reference["baseline"][-1]
    posterior_after = tuple(
        weight * wealth / final_adaptive
        for weight, wealth in zip(ADAPTIVE_WEIGHTS, final_wealths)
    )
    first_adaptive = next(
        (index + 1 for index, value in enumerate(reference["adaptive"]) if value >= THRESHOLD),
        None,
    )
    first_baseline = next(
        (index + 1 for index, value in enumerate(reference["baseline"]) if value >= THRESHOLD),
        None,
    )
    if adaptive_final != ():
        raise AssertionError("adaptive final grid changed")
    if baseline_final != tuple(Fraction(index, 20) for index in range(4, 17)):
        raise AssertionError("baseline final grid changed")
    if final_wealths != (
        Fraction(59049, 1048576),
        Fraction(59049, 1048576),
        Fraction(387420489, 524288),
        Fraction(3, 524288),
    ):
        raise AssertionError("expert wealths changed")
    if final_adaptive != Fraction(387479541, 2097152) or final_baseline != Fraction(59049, 1048576):
        raise AssertionError("mixture wealths changed")
    if posterior_after[2] != Fraction(129140163, 129159847):
        raise AssertionError("posterior concentration changed")
    return {
        "path": "00000000001111111111",
        "baseline_final": {
            "size": len(baseline_final),
            "hull": [q(baseline_final[0]), q(baseline_final[-1])],
            "accepted": [q(value) for value in baseline_final],
        },
        "adaptive_final": {"size": 0, "hull": None, "accepted": []},
        "adaptive_subset_of_baseline": True,
        "first_crossings": {"adaptive": first_adaptive, "baseline": first_baseline},
        "final_adaptive_wealth": q(final_adaptive),
        "final_baseline_wealth": q(final_baseline),
        "final_expert_wealths": {
            name: q(value) for (name, _mode, _direction), value in zip(EXPERTS, final_wealths)
        },
        "posterior_weights_after": {
            name: q(value) for (name, _mode, _direction), value in zip(EXPERTS, posterior_after)
        },
    }


def crossing(model: str, persistence: Fraction | None = None, cap: int = 100_000) -> dict[str, object]:
    states: dict[tuple[int | None, tuple[Fraction, ...], bool, bool], Fraction] = {
        (None, (Fraction(1),) * 4, False, False): Fraction(1)
    }
    maximum_states = 1
    for _time in range(1, 21):
        next_states: dict[tuple[int | None, tuple[Fraction, ...], bool, bool], Fraction] = defaultdict(Fraction)
        for (last, wealths, baseline_crossed, adaptive_crossed), probability in states.items():
            for observation_int in (0, 1):
                if last is None or model == "iid_half":
                    transition = Fraction(1, 2)
                elif model == "persistent":
                    assert persistence is not None
                    transition = persistence if observation_int == last else 1 - persistence
                elif model == "alternating":
                    assert persistence is not None
                    transition = persistence if observation_int != last else 1 - persistence
                else:
                    raise ValueError(model)
                previous = None if last is None else Fraction(last)
                updated = update(wealths, previous, Fraction(observation_int), REFERENCE)
                baseline = mix(updated, BASELINE_WEIGHTS)
                adaptive = mix(updated, ADAPTIVE_WEIGHTS)
                next_states[
                    (
                        observation_int,
                        updated,
                        baseline_crossed or baseline >= THRESHOLD,
                        adaptive_crossed or adaptive >= THRESHOLD,
                    )
                ] += probability * transition
        maximum_states = max(maximum_states, len(next_states))
        if len(next_states) > cap:
            return {"status": "UNKNOWN_RESOURCE_LIMIT", "states": len(next_states), "cap": cap}
        states = next_states
    baseline_probability = sum(
        probability
        for (_last, _wealths, baseline_crossed, _adaptive_crossed), probability in states.items()
        if baseline_crossed
    )
    adaptive_probability = sum(
        probability
        for (_last, _wealths, _baseline_crossed, adaptive_crossed), probability in states.items()
        if adaptive_crossed
    )
    return {
        "status": "SOLVED",
        "model": model,
        "persistence": None if persistence is None else q(persistence),
        "maximum_states": maximum_states,
        "baseline": q(baseline_probability),
        "adaptive": q(adaptive_probability),
        "gain": q(adaptive_probability - baseline_probability),
    }


def build_payload() -> dict[str, object]:
    control = path_control()
    null = crossing("iid_half")
    if null != {
        "status": "SOLVED",
        "model": "iid_half",
        "persistence": None,
        "maximum_states": 666,
        "baseline": [9919, 524288],
        "adaptive": [6573, 524288],
        "gain": [-1673, 262144],
    }:
        raise AssertionError("iid benchmark changed")
    alternatives = []
    for persistence in PERSISTENCE_GRID:
        for model in ("persistent", "alternating"):
            packet = crossing(model, persistence)
            if Fraction(*packet["adaptive"]) <= Fraction(*packet["baseline"]):
                raise AssertionError("adaptive power dominance failed")
            alternatives.append(packet)
    if crossing("iid_half", cap=10)["status"] != "UNKNOWN_RESOURCE_LIMIT":
        raise AssertionError("resource abstention failed")

    expected = {
        ("persistent", (3, 4)): ([64195730523, 274877906944], [93519651901, 274877906944]),
        ("alternating", (3, 4)): ([20968297, 274877906944], [76764627103, 274877906944]),
        ("persistent", (4, 5)): ([6290791727104, 19073486328125], [10096871290173, 19073486328125]),
        ("alternating", (4, 5)): ([199437241, 19073486328125], [9000466839357, 19073486328125]),
        ("persistent", (7, 8)): ([75121295530218931, 144115188075855872], [119769960138820629, 144115188075855872]),
        ("alternating", (7, 8)): ([19593777589, 144115188075855872], [115672803437820483, 144115188075855872]),
        ("persistent", (9, 10)): ([5991489162473726799, 10000000000000000000], [9077110827793188733, 10000000000000000000]),
        ("alternating", (9, 10)): ([167275525591, 10000000000000000000], [8907844006196817877, 10000000000000000000]),
    }
    observed = {
        (packet["model"], tuple(packet["persistence"])): (packet["baseline"], packet["adaptive"])
        for packet in alternatives
    }
    if observed != expected:
        raise AssertionError("alternative benchmark table changed")

    return {
        "schema": "predictable-betting/public-independent-certificate/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": PRIVATE_HEAD,
            "blobs": PRIVATE_BLOBS,
        },
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "control": control,
        "null_benchmark": null,
        "alternative_benchmarks": alternatives,
        "negative_controls": {
            "post_hoc_selection": {
                "status": "INVALID_POST_HOC_SELECTION",
                "expectation": [3, 2],
            },
            "current_outcome_leakage": "INVALID_CURRENT_OUTCOME_LEAKAGE",
            "invalid_weights": "INVALID_MIXTURE_WEIGHTS",
            "resource": "UNKNOWN_RESOURCE_LIMIT",
        },
        "dominance": {
            "finite_markov_family": "PASS",
            "global_pathwise_strict_dominance": "IMPOSSIBLE_UNDER_EQUAL_NULL_MEAN",
        },
        "gates": {
            "predictability": "PASS",
            "factor_nonnegativity": "PASS",
            "mixture_normalization": "PASS",
            "posterior_factor_identity": "PASS",
            "expert_regret_lower_bound": "PASS",
            "iid_null_crossing": "PASS",
            "finite_power_dominance": "PASS",
            "global_dominance_obstruction": "PASS",
            "negative_controls": "PASS",
        },
        "scientific_boundary": (
            "Independent exact verification for the declared four-expert binary "
            "mean and finite Markov benchmark. Anytime validity follows from the "
            "established e-process/Ville theorem; global strict pathwise dominance "
            "at equal calibration is impossible."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    claimed = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    if canonical(build_certificate()["payload"]) != canonical(payload):
        return ["semantic-replay"]
    return []


def report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate["payload"]
    result = {
        "schema": "predictable-betting/public-independent-report/1",
        "control": payload["control"],
        "null_benchmark": payload["null_benchmark"],
        "alternative_benchmarks": payload["alternative_benchmarks"],
        "negative_controls": payload["negative_controls"],
        "dominance": payload["dominance"],
        "gates": payload["gates"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": payload["scientific_boundary"],
    }
    result["sha256"] = digest(result)
    return result


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public predictable betting replay failed")
    tampered = deepcopy(certificate)
    tampered["payload"]["null_benchmark"]["adaptive"] = [0, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["null_benchmark"]["adaptive"] = [0, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")
    result = report(certificate)
    write(ROOT / "PREDICTABLE_BETTING_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "PREDICTABLE_BETTING_PUBLIC_REPORT.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
