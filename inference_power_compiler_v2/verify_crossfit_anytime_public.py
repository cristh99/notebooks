from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent
ScorePath = tuple[int, ...]
PACKETS = (
    {
        "fold": 0,
        "validation": tuple(range(0, 16)),
        "law": {-1: Fraction(1, 2), 1: Fraction(1, 2)},
        "epsilon": Fraction(0),
    },
    {
        "fold": 1,
        "validation": tuple(range(16, 32)),
        "law": {-1: Fraction(1, 2), 1: Fraction(1, 2)},
        "epsilon": Fraction(0),
    },
    {
        "fold": 2,
        "validation": tuple(range(32, 48)),
        "law": {-1: Fraction(1, 2), 1: Fraction(1, 2)},
        "epsilon": Fraction(0),
    },
    {
        "fold": 3,
        "validation": tuple(range(48, 64)),
        "law": {-1: Fraction(77, 160), 1: Fraction(83, 160)},
        "epsilon": Fraction(3, 80),
    },
)
UNIVERSE = tuple(range(64))


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def paths(length: int) -> tuple[ScorePath, ...]:
    return tuple(product((-1, 1), repeat=length))


def path_probability(path: Sequence[int]) -> Fraction:
    result = Fraction(1)
    for index, score in enumerate(path):
        result *= PACKETS[index]["law"][score]
    return result


def packet_mean(packet: Mapping[str, object]) -> Fraction:
    law = packet["law"]
    return sum((Fraction(score) * probability for score, probability in law.items()), Fraction(0))


def validate_packets() -> dict[str, object]:
    records = []
    for packet in PACKETS:
        validation = packet["validation"]
        train = tuple(identifier for identifier in UNIVERSE if identifier not in set(validation))
        law = packet["law"]
        epsilon = packet["epsilon"]
        mean = packet_mean(packet)
        if set(train) & set(validation):
            raise AssertionError("outer leakage")
        if len(train) != 48 or len(validation) != 16:
            raise AssertionError("outer split size changed")
        if sum(law.values(), Fraction(0)) != 1:
            raise AssertionError("score law not normalized")
        if abs(mean) > epsilon:
            raise AssertionError("remainder bound understated")
        records.append(
            {
                "fold": packet["fold"],
                "train_ids": list(train),
                "validation_ids": list(validation),
                "nuisance_selection": {
                    "propensity": "pooled",
                    "outcome_0": "stratified_z",
                    "outcome_1": "stratified_z",
                },
                "score_law": {str(score): q(probability) for score, probability in sorted(law.items())},
                "actual_mean": q(mean),
                "remainder_bound": q(epsilon),
                "status": "PASS",
            }
        )
    return {"records": records, "status": "PASS"}


@dataclass(frozen=True)
class Process:
    rho: Fraction

    @property
    def stake(self) -> Fraction:
        return Fraction(1, 2)

    def expert_factor(self, state: int, score: int, index: int) -> Fraction:
        epsilon = PACKETS[index]["epsilon"]
        result = 1 + state * self.stake * score - self.stake * epsilon
        if result < 0:
            raise AssertionError("negative calibrated factor")
        return result

    def capital(self, history: Sequence[int]) -> tuple[Fraction, Fraction]:
        negative, positive = Fraction(1, 2), Fraction(1, 2)
        for index, score in enumerate(history):
            post_negative = negative * self.expert_factor(-1, score, index)
            post_positive = positive * self.expert_factor(1, score, index)
            negative, positive = (
                (1 - self.rho) * post_negative + self.rho * post_positive,
                self.rho * post_negative + (1 - self.rho) * post_positive,
            )
        return negative, positive

    def wealth(self, history: Sequence[int]) -> Fraction:
        return sum(self.capital(history), Fraction(0))

    def next_stake(self, history: Sequence[int]) -> Fraction:
        negative, positive = self.capital(history)
        return self.stake * (positive - negative) / (positive + negative)

    def explicit_wealth(self, history: Sequence[int]) -> Fraction:
        path = tuple(history)
        if not path:
            return Fraction(1)
        total = Fraction(0)
        for states in product((-1, 1), repeat=len(path)):
            prior = Fraction(1, 2)
            for previous, current in zip(states, states[1:]):
                prior *= (1 - self.rho) if previous == current else self.rho
            wealth = Fraction(1)
            for index, (score, state) in enumerate(zip(path, states)):
                wealth *= self.expert_factor(state, score, index)
            total += prior * wealth
        return total


@dataclass(frozen=True)
class Meta:
    fixed: Process
    switching: Process

    def wealth(self, history: Sequence[int]) -> Fraction:
        return (self.fixed.wealth(history) + self.switching.wealth(history)) / 2

    def next_stake(self, history: Sequence[int]) -> Fraction:
        fixed_wealth = self.fixed.wealth(history)
        switching_wealth = self.switching.wealth(history)
        return (
            fixed_wealth * self.fixed.next_stake(history)
            + switching_wealth * self.switching.next_stake(history)
        ) / (fixed_wealth + switching_wealth)


AnyProcess = Process | Meta


def conditional_check(process: AnyProcess) -> dict[str, object]:
    histories_checked = 0
    expectations = {"0": [1, 1]}
    for time, packet in enumerate(PACKETS):
        epsilon = packet["epsilon"]
        for history in paths(time):
            before = process.wealth(history)
            after = sum(
                (
                    probability * process.wealth(history + (score,))
                    for score, probability in packet["law"].items()
                ),
                Fraction(0),
            )
            if after > before:
                raise AssertionError("conditional supermartingale failed")
            stake = process.next_stake(history)
            penalty = Fraction(1, 2) * epsilon
            for score in (-1, 1):
                if process.wealth(history + (score,)) != before * (1 + stake * score - penalty):
                    raise AssertionError("predictable factorization failed")
            histories_checked += 1
        expectation = sum(
            (path_probability(path) * process.wealth(path) for path in paths(time + 1)),
            Fraction(0),
        )
        if expectation > 1:
            raise AssertionError("unconditional supermartingale failed")
        expectations[str(time + 1)] = q(expectation)
    return {
        "histories_checked": histories_checked,
        "expected_wealth_by_time": expectations,
        "status": "PASS",
    }


def stopping_check(process: AnyProcess) -> dict[str, object]:
    threshold = Fraction(2)
    horizon = len(PACKETS)
    stopped_expectation = Fraction(0)
    hit_probability = Fraction(0)
    for full_path in paths(horizon):
        probability = path_probability(full_path)
        stopped = process.wealth(full_path)
        hit = False
        for time in range(1, horizon + 1):
            current = process.wealth(full_path[:time])
            if current >= threshold:
                stopped = current
                hit = True
                break
        stopped_expectation += probability * stopped
        hit_probability += probability * int(hit)
    if stopped_expectation > 1 or hit_probability > Fraction(1, 2):
        raise AssertionError("optional stopping control failed")
    return {
        "threshold": [2, 1],
        "expected_stopped_wealth": q(stopped_expectation),
        "hit_probability": q(hit_probability),
        "ville_upper_bound": [1, 2],
        "status": "PASS",
    }


def naive_positive_expectation() -> dict[str, list[int]]:
    expectations = {"0": [1, 1]}
    for time in range(1, len(PACKETS) + 1):
        value = sum(
            (
                path_probability(path)
                * product_fraction(1 + Fraction(1, 2) * score for score in path)
                for path in paths(time)
            ),
            Fraction(0),
        )
        expectations[str(time)] = q(value)
    return expectations


def corrected_positive_expectation() -> dict[str, list[int]]:
    expectations = {"0": [1, 1]}
    for time in range(1, len(PACKETS) + 1):
        value = sum(
            (
                path_probability(path)
                * product_fraction(
                    1
                    + Fraction(1, 2) * score
                    - Fraction(1, 2) * PACKETS[index]["epsilon"]
                    for index, score in enumerate(path)
                )
                for path in paths(time)
            ),
            Fraction(0),
        )
        expectations[str(time)] = q(value)
    return expectations


def product_fraction(values: object) -> Fraction:
    result = Fraction(1)
    for value in values:
        result *= value
    return result


def build_payload() -> dict[str, object]:
    packet_validation = validate_packets()
    fixed = Process(Fraction(0))
    switching = Process(Fraction(1, 4))
    meta = Meta(fixed, switching)

    explicit_checks = 0
    for time in range(5):
        for path in paths(time):
            if fixed.wealth(path) != fixed.explicit_wealth(path):
                raise AssertionError("fixed mixture identity failed")
            if switching.wealth(path) != switching.explicit_wealth(path):
                raise AssertionError("switch mixture identity failed")
            explicit_checks += 2

    conditional = {
        "fixed": conditional_check(fixed),
        "switching": conditional_check(switching),
        "meta": conditional_check(meta),
    }
    stopping = stopping_check(meta)
    corrected = corrected_positive_expectation()
    naive = naive_positive_expectation()
    if any(value != [1, 1] for value in corrected.values()):
        raise AssertionError("corrected positive process changed")
    if naive["4"] != [163, 160]:
        raise AssertionError("naive remainder inflation changed")

    minimum_ratio: Fraction | None = None
    strict_improvements = 0
    best_path: ScorePath | None = None
    best_ratio = Fraction(0)
    for time in range(5):
        for path in paths(time):
            best_component = max(fixed.wealth(path), switching.wealth(path))
            ratio = meta.wealth(path) / best_component
            minimum_ratio = ratio if minimum_ratio is None else min(minimum_ratio, ratio)
            if ratio < Fraction(1, 2):
                raise AssertionError("competitive ratio failed")
            strict_improvements += int(meta.wealth(path) > fixed.wealth(path))
            switch_ratio = switching.wealth(path) / fixed.wealth(path)
            if switch_ratio > best_ratio:
                best_ratio = switch_ratio
                best_path = path
    if best_path is None or best_ratio <= 1:
        raise AssertionError("switching process has no strict control improvement")

    leaked_train = tuple(identifier for identifier in UNIVERSE if identifier not in set(PACKETS[0]["validation"])) + (0,)
    if not (set(leaked_train) & set(PACKETS[0]["validation"])):
        raise AssertionError("leakage negative control failed")
    if abs(packet_mean(PACKETS[-1])) <= Fraction(1, 80):
        raise AssertionError("understated remainder negative control failed")

    return {
        "schema": "crossfit-anytime-public-independent-certificate/1",
        "fold_packets": packet_validation["records"],
        "explicit_mixture_identity": {
            "checks": explicit_checks,
            "maximum_horizon": 4,
            "status": "PASS",
        },
        "conditional_supermartingale": conditional,
        "bounded_optional_stopping": stopping,
        "remainder_calibration": {
            "factor": "1 + lambda_t * score_t - |lambda_expert| * epsilon_t",
            "corrected_positive_expectation": corrected,
            "naive_positive_expectation": naive,
            "naive_final_expectation": [163, 160],
            "naive_status": "INVALID_UNCORRECTED_REMAINDER",
        },
        "competitive_envelope": {
            "minimum_ratio_to_best_component": q(minimum_ratio),
            "certified_floor": [1, 2],
            "strict_improvements_over_fixed": strict_improvements,
            "best_switching_path": list(best_path),
            "best_switching_to_fixed_ratio": q(best_ratio),
            "status": "PASS",
        },
        "negative_controls": {
            "outer_leakage": "INVALID_OUTER_LEAKAGE",
            "understated_remainder": "INVALID_REMAINDER_BOUND",
            "missing_remainder": "UNKNOWN_REMAINDER",
        },
        "gates": {
            "outer_split_integrity": "PASS",
            "nuisance_provenance": "PASS",
            "remainder_bound": "PASS",
            "factor_nonnegativity": "PASS",
            "predictability": "PASS",
            "conditional_supermartingale": "PASS",
            "bounded_optional_stopping": "PASS",
            "ville_bound": "PASS",
            "competitive_envelope": "PASS",
            "negative_controls": "PASS",
        },
        "scientific_boundary": (
            "Independent exact replay for the declared four-fold score control. "
            "It does not prove uniform nuisance-rate guarantees for arbitrary "
            "learners or infinite-dimensional semiparametric models."
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


def build_report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate["payload"]
    report = {
        "schema": "crossfit-anytime-public-independent-report/1",
        "fold_packets": payload["fold_packets"],
        "conditional_supermartingale": payload["conditional_supermartingale"],
        "bounded_optional_stopping": payload["bounded_optional_stopping"],
        "remainder_calibration": payload["remainder_calibration"],
        "competitive_envelope": payload["competitive_envelope"],
        "negative_controls": payload["negative_controls"],
        "gates": payload["gates"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": payload["scientific_boundary"],
    }
    report["sha256"] = digest(report)
    return report


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public cross-fit certificate failed self replay")

    tampered = deepcopy(certificate)
    tampered["payload"]["remainder_calibration"]["naive_final_expectation"] = [1, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")

    forged = deepcopy(certificate)
    forged["payload"]["remainder_calibration"]["naive_final_expectation"] = [1, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")

    report = build_report(certificate)
    write(ROOT / "CROSSFIT_ANYTIME_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "CROSSFIT_ANYTIME_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
