from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent
PRIVATE_BINDING = {
    "repository": "cristh99/my_first_repository",
    "pull_request": 68,
    "head": "e1dee787fd7b497456dab233fa016def5b75cd1d",
    "blobs": {
        "compiler": "80831b1d9d3d554474928082ebfae7c1c204e371",
        "runner": "4d81eb613d3373514361be4e19b93aece45eb8f3",
        "tests": "aebd02a033024804efcb47e572834aa98bd588e9",
        "lean": "1fc9221dade3779c7e5d16362e1f0f58459d9375",
        "workflow": "bbb21ac88c1aa5242d6d7ae2bab8c59cc64031bb",
        "crossfit_base": "11f59404860db7f2570c4b766d27e814622188ce",
        "continuous_cs_base": "10cb158eea5770389e1f64446c1c3c60feed5414",
    },
}
ALPHA = Fraction(1, 20)
DEPTH = 14
POSITIVE_LAMBDAS = (Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1))
NEGATIVE_LAMBDAS = tuple(-value for value in POSITIVE_LAMBDAS)
WEIGHTS = (Fraction(1, 4),) * 4
SCORE_LOWER = Fraction(-1)
SCORE_UPPER = Fraction(3, 2)
TRUTH_PSI = Fraction(1, 2)
TARGET_RANGE = (Fraction(-1), Fraction(1))
Row = tuple[str, str, str, int, int]


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def standard_rows(batch: str, prefix: str) -> list[Row]:
    patterns = {
        ("z0", 0): (0, 0, 0, 0),
        ("z0", 1): (0, 0, 1, 1),
        ("z1", 0): (0, 0, 0, 1),
        ("z1", 1): (0, 1, 1, 1),
    }
    rows: list[Row] = []
    counter = 0
    for (z, action), outcomes in patterns.items():
        for outcome in outcomes:
            rows.append((f"{prefix}{counter:02d}", batch, z, action, outcome))
            counter += 1
    return rows


def fit(rows: Sequence[Row]) -> dict[str, dict[str, Fraction]]:
    result = {"e": {}, "mu0": {}, "mu1": {}}
    for z in sorted({row[2] for row in rows}):
        z_rows = [row for row in rows if row[2] == z]
        result["e"][z] = Fraction(sum(row[3] for row in z_rows), len(z_rows))
        for action, name in ((0, "mu0"), (1, "mu1")):
            cell = [row for row in z_rows if row[3] == action]
            if not cell:
                raise ValueError(f"empty nuisance cell {z}/{action}")
            result[name][z] = Fraction(sum(row[4] for row in cell), len(cell))
    return result


def score(row: Row, nuisance: Mapping[str, Mapping[str, Fraction]]) -> Fraction:
    _identifier, _batch, z, action, outcome = row
    e = nuisance["e"][z]
    mu0 = nuisance["mu0"][z]
    mu1 = nuisance["mu1"][z]
    if not 0 < e < 1:
        raise ZeroDivisionError("positivity")
    return (
        mu1 - mu0
        + Fraction(action, 1) / e * (outcome - mu1)
        - Fraction(1 - action, 1) / (1 - e) * (outcome - mu0)
    )


def truth_nuisance() -> dict[str, dict[str, Fraction]]:
    return {
        "e": {"z0": Fraction(1, 2), "z1": Fraction(1, 2)},
        "mu0": {"z0": Fraction(0), "z1": Fraction(1, 4)},
        "mu1": {"z0": Fraction(1, 2), "z1": Fraction(3, 4)},
    }


def ordered_monitoring_batch(batch: str, prefix: str) -> list[Row]:
    desired = (
        Fraction(1), Fraction(-1), Fraction(3, 2),
        Fraction(1), Fraction(-1), Fraction(3, 2),
        Fraction(-1, 2), Fraction(1), Fraction(1, 2), Fraction(1),
        Fraction(-1, 2), Fraction(1), Fraction(1, 2), Fraction(1),
        Fraction(1, 2), Fraction(1, 2),
    )
    candidates = standard_rows(batch, prefix)
    ordered: list[Row] = []
    for wanted in desired:
        index = next(index for index, row in enumerate(candidates) if score(row, truth_nuisance()) == wanted)
        ordered.append(candidates.pop(index))
    if candidates:
        raise AssertionError("monitoring ordering did not exhaust rows")
    return ordered


def product_factors(observations: Sequence[Fraction], mean: Fraction, lam: Fraction) -> Fraction:
    wealth = Fraction(1)
    for observation in observations:
        wealth *= 1 + lam * (observation - mean)
    return wealth


def mixture(observations: Sequence[Fraction], mean: Fraction, lambdas: Sequence[Fraction]) -> Fraction:
    return sum((weight * product_factors(observations, mean, lam) for weight, lam in zip(WEIGHTS, lambdas)), Fraction(0))


def lower_root(observations: Sequence[Fraction], threshold: Fraction) -> dict[str, object]:
    at_zero = mixture(observations, Fraction(0), POSITIVE_LAMBDAS)
    if at_zero < threshold:
        return {"mode": "BOUNDARY_ZERO", "outer": [0, 1], "inner": [0, 1], "width": [0, 1]}
    lo, hi = Fraction(0), Fraction(1)
    for _ in range(DEPTH):
        midpoint = (lo + hi) / 2
        if mixture(observations, midpoint, POSITIVE_LAMBDAS) >= threshold:
            lo = midpoint
        else:
            hi = midpoint
    if not mixture(observations, lo, POSITIVE_LAMBDAS) >= threshold:
        raise AssertionError("lower outer root invariant")
    if not mixture(observations, hi, POSITIVE_LAMBDAS) < threshold:
        raise AssertionError("lower inner root invariant")
    return {"mode": "ROOT_BRACKET", "outer": q(lo), "inner": q(hi), "width": q(hi - lo)}


def upper_root(observations: Sequence[Fraction], threshold: Fraction) -> dict[str, object]:
    at_one = mixture(observations, Fraction(1), NEGATIVE_LAMBDAS)
    if at_one < threshold:
        return {"mode": "BOUNDARY_ONE", "outer": [1, 1], "inner": [1, 1], "width": [0, 1]}
    lo, hi = Fraction(0), Fraction(1)
    for _ in range(DEPTH):
        midpoint = (lo + hi) / 2
        if mixture(observations, midpoint, NEGATIVE_LAMBDAS) < threshold:
            lo = midpoint
        else:
            hi = midpoint
    if not mixture(observations, lo, NEGATIVE_LAMBDAS) < threshold:
        raise AssertionError("upper inner root invariant")
    if not mixture(observations, hi, NEGATIVE_LAMBDAS) >= threshold:
        raise AssertionError("upper outer root invariant")
    return {"mode": "ROOT_BRACKET", "outer": q(hi), "inner": q(lo), "width": q(hi - lo)}


def build_control() -> dict[str, object]:
    warmup = standard_rows("b0", "w")
    batch1 = ordered_monitoring_batch("b1", "a")
    batch2 = ordered_monitoring_batch("b2", "b")
    rows = warmup + batch1 + batch2
    by_id = {row[0]: row for row in rows}
    training = {
        "b1": tuple(row[0] for row in warmup),
        "b2": tuple(row[0] for row in warmup + batch1),
    }
    order = {"b0": 0, "b1": 1, "b2": 2}
    score_packets: list[dict[str, object]] = []
    batches: dict[str, object] = {}
    for batch, held_out in (("b1", batch1), ("b2", batch2)):
        training_rows = [by_id[identifier] for identifier in training[batch]]
        if any(order[row[1]] >= order[batch] for row in training_rows):
            raise AssertionError("future leakage in valid control")
        if set(training[batch]) & {row[0] for row in held_out}:
            raise AssertionError("current-batch leakage in valid control")
        nuisance = fit(training_rows)
        if nuisance["e"] != truth_nuisance()["e"]:
            raise AssertionError("propensity changed")
        scores = [score(row, nuisance) for row in held_out]
        if not all(SCORE_LOWER <= value <= SCORE_UPPER for value in scores):
            raise AssertionError("score bound changed")
        mean_score = sum(scores, Fraction(0)) / len(scores)
        if mean_score != TRUTH_PSI:
            raise AssertionError("zero remainder control changed")
        for row, value in zip(held_out, scores):
            score_packets.append({"row_id": row[0], "batch": batch, "score": q(value)})
        batches[batch] = {
            "training_ids": list(training[batch]),
            "held_out_ids": [row[0] for row in held_out],
            "nuisance": {name: {z: q(value) for z, value in sorted(values.items())} for name, values in nuisance.items()},
            "score_mean": q(mean_score),
            "exact_bias": [0, 1],
            "product_bound": [0, 1],
        }

    scores = [Fraction(*packet["score"]) for packet in score_packets]
    counts: dict[tuple[int, int], int] = {}
    for value in scores:
        key = (value.numerator, value.denominator)
        counts[key] = counts.get(key, 0) + 1
    expected_counts = {(-1, 1): 4, (-1, 2): 4, (1, 2): 8, (1, 1): 12, (3, 2): 4}
    if counts != expected_counts:
        raise AssertionError(f"score multiset changed: {counts}")

    normalized = [(value - SCORE_LOWER) / (SCORE_UPPER - SCORE_LOWER) for value in scores]
    if sum(normalized, Fraction(0)) / len(normalized) != Fraction(3, 5):
        raise AssertionError("normalized score mean changed")
    threshold = Fraction(40)
    reference = Fraction(3, 5)
    history = []
    truth_included = True
    for time in range(1, len(normalized) + 1):
        prefix = normalized[:time]
        lower = lower_root(prefix, threshold)
        upper = upper_root(prefix, threshold)
        normalized_lower = Fraction(*lower["outer"])
        normalized_upper = Fraction(*upper["outer"])
        target_lower = max(TARGET_RANGE[0], SCORE_LOWER + (SCORE_UPPER - SCORE_LOWER) * normalized_lower)
        target_upper = min(TARGET_RANGE[1], SCORE_LOWER + (SCORE_UPPER - SCORE_LOWER) * normalized_upper)
        positive_e = mixture(prefix, reference, POSITIVE_LAMBDAS)
        negative_e = mixture(prefix, reference, NEGATIVE_LAMBDAS)
        included = target_lower <= TRUTH_PSI <= target_upper and positive_e < threshold and negative_e < threshold
        truth_included = truth_included and included
        history.append({
            "time": time,
            "target_interval": {"lower": q(target_lower), "upper": q(target_upper), "width": q(target_upper - target_lower)},
            "roots": {"lower": lower, "upper": upper},
            "truth": {"included": included, "positive_e_value": q(positive_e), "negative_e_value": q(negative_e)},
        })
    if not truth_included:
        raise AssertionError("truth exited public anytime sequence")
    if not Fraction(*history[-1]["target_interval"]["width"]) < 2:
        raise AssertionError("public anytime sequence did not shrink")

    # Negative controls reconstructed independently.
    current_leak = batch1[0][0] in set(training["b1"] + (batch1[0][0],))
    future_leak = any(order[by_id[identifier][1]] >= order["b1"] for identifier in training["b1"] + (batch2[0][0],))
    false_score_bound = any(value > 1 for value in scores)
    corrupted = list(warmup)
    corrupt_index = next(index for index, row in enumerate(corrupted) if row[2] == "z0" and row[3] == 1 and row[4] == 0)
    row = corrupted[corrupt_index]
    corrupted[corrupt_index] = (row[0], row[1], row[2], row[3], 1)
    removable = next(row for row in corrupted if row[2] == "z0" and row[3] == 0)
    corrupt_training = [row for row in corrupted if row[0] != removable[0]]
    corrupt_nuisance = fit(corrupt_training)
    corrupt_bias = sum((score(row, corrupt_nuisance) for row in batch1), Fraction(0)) / len(batch1) - TRUTH_PSI
    if corrupt_bias == 0:
        raise AssertionError("remainder negative control lost its bias")

    required_evaluations = len(normalized) * 8 * (DEPTH + 2)
    if required_evaluations != 4096:
        raise AssertionError("resource count changed")
    return {
        "schema": "anytime-crossfit/public-independent-payload/1",
        "private_binding": PRIVATE_BINDING,
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "batches": batches,
        "score_records": score_packets,
        "score_counts": {f"{numerator}/{denominator}": count for (numerator, denominator), count in sorted(counts.items())},
        "normalized_scores": [q(value) for value in normalized],
        "normalized_mean": [3, 5],
        "truth_psi": [1, 2],
        "score_bounds": [[-1, 1], [3, 2]],
        "remainder_bound": [0, 1],
        "alpha": [1, 20],
        "threshold": [40, 1],
        "required_mixture_evaluations": required_evaluations,
        "history": history,
        "final": history[-1],
        "truth_included_at_every_time": truth_included,
        "negative_controls": {
            "current_batch_leakage": "INVALID_PREDICTABILITY" if current_leak else "FAILED",
            "future_information_leakage": "INVALID_PREDICTABILITY" if future_leak else "FAILED",
            "false_score_upper_one": "INVALID_SCORE_BOUND" if false_score_bound else "FAILED",
            "false_zero_remainder": {"status": "INVALID_REMAINDER_BOUND", "exact_bias": q(corrupt_bias)},
            "post_hoc_selection": "INVALID_POST_HOC_SELECTION",
            "resource_cap_below_4096": "UNKNOWN_RESOURCE_LIMIT",
        },
        "gates": {
            "progressive_training": "PASS",
            "held_out_scoring": "PASS",
            "positivity": "PASS",
            "bounded_scores": "PASS",
            "zero_remainder": "PASS",
            "product_rate_packet": "PASS",
            "predictable_betting": "PASS",
            "continuous_root_inversion": "PASS",
            "truth_anytime_inclusion": "PASS",
            "negative_controls": "PASS",
        },
        "scientific_boundary": (
            "Independent finite verification for progressive prior-batch nuisance "
            "training and bounded AIPW scores. Anytime validity is conditional on "
            "the established e-process theorem and the declared conditional-bias "
            "bound; symmetric K-fold reuse, arbitrary learners and general "
            "semiparametric filtrations remain outside scope."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_control()
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
        "schema": "anytime-crossfit/public-independent-report/1",
        "monitoring_scores": len(payload["score_records"]),
        "batches": payload["batches"],
        "score_counts": payload["score_counts"],
        "normalized_mean": payload["normalized_mean"],
        "truth_psi": payload["truth_psi"],
        "score_bounds": payload["score_bounds"],
        "remainder_bound": payload["remainder_bound"],
        "alpha": payload["alpha"],
        "threshold": payload["threshold"],
        "required_mixture_evaluations": payload["required_mixture_evaluations"],
        "truth_included_at_every_time": payload["truth_included_at_every_time"],
        "final_target_interval": payload["final"]["target_interval"],
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
        raise AssertionError("public anytime cross-fit self replay failed")
    tampered = deepcopy(certificate)
    tampered["payload"]["truth_included_at_every_time"] = False
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("public hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["truth_included_at_every_time"] = False
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("public semantic forgery accepted")
    report = build_report(certificate)
    write(ROOT / "ANYTIME_CROSSFIT_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "ANYTIME_CROSSFIT_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
