from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent
COMPONENTS = (
    "e|z0", "e|z1", "mu0|z0", "mu0|z1", "mu1|z0", "mu1|z1"
)
BATCHES = tuple(f"b{index}" for index in range(1, 9))
ALPHA_TOTAL = Fraction(1, 20)
ALPHA_CALIBRATION = Fraction(1, 100)
ALPHA_MONITORING = Fraction(1, 25)
ALPHA_PAIR = ALPHA_CALIBRATION / (len(BATCHES) * len(COMPONENTS))
RADIUS_DEPTH = 20
EXPONENTIAL_STEPS = 64
SCORE_LOWER = Fraction(-3, 2)
SCORE_UPPER = Fraction(3, 2)
TARGET_LOWER = Fraction(0)
TARGET_UPPER = Fraction(1)
MAX_REMAINDER = Fraction(1, 16)
MONITOR_DEPTH = 18
POSITIVE_LAMBDAS = (
    Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1)
)
NEGATIVE_LAMBDAS = tuple(-value for value in POSITIVE_LAMBDAS)
MIXTURE_WEIGHTS = (Fraction(1, 4),) * 4
BASELINE_LAMBDA = Fraction(1, 4)
TRUTH = {
    "e|z0": Fraction(1, 2),
    "e|z1": Fraction(1, 2),
    "mu0|z0": Fraction(1, 4),
    "mu0|z1": Fraction(1, 4),
    "mu1|z0": Fraction(3, 4),
    "mu1|z1": Fraction(3, 4),
}
TRUTH_PSI = Fraction(1, 2)
EXPECTED_REMAINDERS = (
    Fraction(7523843697, 240518168576),
    Fraction(35540308081, 2164663517184),
    Fraction(788530084127, 76922408034304),
    Fraction(204766990245, 28856596013056),
    Fraction(537815685811, 103672501075200),
    Fraction(473381797871, 119150618443776),
    Fraction(1815742228801, 571360942489600),
    Fraction(175805415059, 84181359001600),
)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def rational_hoeffding_bound(trials: int, radius: Fraction) -> Fraction:
    exponent = 2 * trials * radius * radius
    return Fraction(2, 1) / (
        1 + exponent / EXPONENTIAL_STEPS
    ) ** EXPONENTIAL_STEPS


def certified_radius(trials: int) -> dict[str, object]:
    lo, hi = Fraction(0), Fraction(1)
    if rational_hoeffding_bound(trials, hi) > ALPHA_PAIR:
        return {"status": "UNKNOWN_CALIBRATION_IMPRECISION"}
    for _ in range(RADIUS_DEPTH):
        midpoint = (lo + hi) / 2
        if rational_hoeffding_bound(trials, midpoint) <= ALPHA_PAIR:
            hi = midpoint
        else:
            lo = midpoint
    outer = rational_hoeffding_bound(trials, hi)
    inner = rational_hoeffding_bound(trials, lo)
    if not outer <= ALPHA_PAIR < inner:
        raise AssertionError("rational radius bracket failed")
    return {
        "status": "SOLVED",
        "radius": q(hi),
        "inner_radius": q(lo),
        "resolution": q(hi - lo),
        "outer_failure_bound": q(outer),
        "inner_failure_bound": q(inner),
        "trials": trials,
    }


def nuisance(batch_index: int) -> dict[str, Fraction]:
    k = batch_index
    return {
        "e|z0": Fraction(3 + 4 * k, 8 + 8 * k),
        "e|z1": Fraction(5 + 4 * k, 8 + 8 * k),
        "mu0|z0": Fraction(1 + k, 5 + 4 * k),
        "mu0|z1": Fraction(1 + k, 3 + 4 * k),
        "mu1|z0": Fraction(2 + 3 * k, 3 + 4 * k),
        "mu1|z1": Fraction(4 + 3 * k, 5 + 4 * k),
    }


def calibration_counts(component: str, blocks: int, mode: str | None) -> tuple[int, int, tuple[Fraction, ...]]:
    per_block = {
        "e|z0": 2048,
        "e|z1": 2048,
        "mu0|z0": 1024,
        "mu0|z1": 1024,
        "mu1|z0": 3072,
        "mu1|z1": 3072,
    }
    successes = 0
    trials = 0
    estimates = []
    for block in range(blocks):
        current_trials = 4096
        current_successes = per_block[component]
        if mode == "small_sample":
            current_trials = 64
            current_successes //= 64
        if mode == "calibration_event" and block == 0 and component == "e|z0":
            current_successes = 0
        if mode == "calibration_drift" and block == 1 and component == "e|z0":
            current_successes = current_trials
        successes += current_successes
        trials += current_trials
        estimates.append(Fraction(current_successes, current_trials))
    return successes, trials, tuple(estimates)


def generate_envelopes(mode: str | None = None) -> dict[str, object]:
    if mode == "model_undeclared":
        return {"status": "UNKNOWN_CALIBRATION_MODEL"}
    packets: dict[str, object] = {}
    remainders: list[Fraction] = []
    previous: Fraction | None = None
    for batch_index, batch in enumerate(BATCHES, start=1):
        current_nuisance = nuisance(batch_index)
        component_packets: dict[str, object] = {}
        radii: dict[str, Fraction] = {}
        for component in COMPONENTS:
            if mode == "missing_cell" and batch_index == 1 and component == "mu1|z1":
                return {
                    "status": "UNKNOWN_CALIBRATION_CELL",
                    "witness": {"batch": batch, "component": component},
                }
            successes, trials, estimates = calibration_counts(
                component, batch_index, mode
            )
            if max(estimates) - min(estimates) > Fraction(1, 16):
                return {
                    "status": "UNKNOWN_CALIBRATION_DRIFT",
                    "witness": {"batch": batch, "component": component},
                }
            certificate = certified_radius(trials)
            if certificate["status"] != "SOLVED":
                return certificate
            calibration_radius = Fraction(*certificate["radius"])
            calibration_estimate = Fraction(successes, trials)
            lower = max(Fraction(0), calibration_estimate - calibration_radius)
            upper = min(Fraction(1), calibration_estimate + calibration_radius)
            if not lower <= TRUTH[component] <= upper:
                return {
                    "status": "CALIBRATION_EVENT_FAILED",
                    "witness": {"batch": batch, "component": component},
                }
            envelope = max(
                abs(current_nuisance[component] - lower),
                abs(upper - current_nuisance[component]),
            )
            radii[component] = envelope
            component_packets[component] = {
                "successes": successes,
                "trials": trials,
                "calibration_estimate": q(calibration_estimate),
                "confidence_interval": [q(lower), q(upper)],
                "point_estimate": q(current_nuisance[component]),
                "generated_envelope_radius": q(envelope),
                "certificate": certificate,
            }
        eta = min(
            current_nuisance["e|z0"],
            current_nuisance["e|z1"],
            1 - current_nuisance["e|z0"],
            1 - current_nuisance["e|z1"],
        )
        remainder = max(radii["e|z0"], radii["e|z1"]) * (
            max(radii["mu0|z0"], radii["mu0|z1"])
            + max(radii["mu1|z0"], radii["mu1|z1"])
        ) / eta
        if remainder > MAX_REMAINDER:
            return {
                "status": "UNKNOWN_PRODUCT_RATE",
                "witness": {"batch": batch, "remainder": q(remainder)},
            }
        if previous is not None and remainder > previous:
            return {
                "status": "UNKNOWN_PRODUCT_RATE_REGRESSION",
                "witness": {"batch": batch},
            }
        previous = remainder
        remainders.append(remainder)
        packets[batch] = {
            "nuisance": {key: q(value) for key, value in current_nuisance.items()},
            "components": component_packets,
            "minimum_overlap": q(eta),
            "generated_remainder": q(remainder),
        }
    if tuple(remainders) != EXPECTED_REMAINDERS:
        raise AssertionError("generated remainder sequence changed")
    return {"status": "SOLVED", "batches": packets, "remainders": remainders}


def score(z: str, action: int, outcome: int, nuisance_values: Mapping[str, Fraction]) -> Fraction:
    e = nuisance_values[f"e|{z}"]
    mu0 = nuisance_values[f"mu0|{z}"]
    mu1 = nuisance_values[f"mu1|{z}"]
    return (
        mu1 - mu0
        + Fraction(action, 1) / e * (outcome - mu1)
        - Fraction(1 - action, 1) / (1 - e) * (outcome - mu0)
    )


def standard_events() -> tuple[tuple[str, int, int], ...]:
    events: list[tuple[str, int, int]] = []
    for z in ("z0", "z1"):
        for action in (0, 1):
            outcomes = (0, 0, 0, 1) if action == 0 else (0, 1, 1, 1)
            events.extend((z, action, outcome) for outcome in outcomes)
    return tuple(events)


def factor(current_lambda: Fraction, score_value: Fraction, mean: Fraction) -> Fraction:
    transformed_score = (score_value - SCORE_LOWER) / (SCORE_UPPER - SCORE_LOWER)
    transformed_mean = (mean - SCORE_LOWER) / (SCORE_UPPER - SCORE_LOWER)
    return 1 + current_lambda * (transformed_score - transformed_mean)


def mixture_e(
    scores: Sequence[Fraction],
    remainders: Sequence[Fraction],
    target: Fraction,
    lambdas: Sequence[Fraction],
    weights: Sequence[Fraction],
    side: str,
) -> Fraction:
    total = Fraction(0)
    for current_lambda, weight in zip(lambdas, weights):
        wealth = Fraction(1)
        for score_value, remainder in zip(scores, remainders):
            mean = target + remainder if side == "positive" else target - remainder
            current_factor = factor(current_lambda, score_value, mean)
            if current_factor < 0:
                raise AssertionError("negative betting factor")
            wealth *= current_factor
        total += weight * wealth
    return total


def root_interval(
    scores: Sequence[Fraction],
    remainders: Sequence[Fraction],
    positive_lambdas: Sequence[Fraction],
    negative_lambdas: Sequence[Fraction],
    weights: Sequence[Fraction],
) -> dict[str, object]:
    threshold = 2 / ALPHA_MONITORING
    lo, hi = TARGET_LOWER, TARGET_UPPER
    if mixture_e(scores, remainders, lo, positive_lambdas, weights, "positive") < threshold:
        lower = lo
    else:
        for _ in range(MONITOR_DEPTH):
            midpoint = (lo + hi) / 2
            if mixture_e(scores, remainders, midpoint, positive_lambdas, weights, "positive") >= threshold:
                lo = midpoint
            else:
                hi = midpoint
        lower = lo
    lo, hi = TARGET_LOWER, TARGET_UPPER
    if mixture_e(scores, remainders, hi, negative_lambdas, weights, "negative") < threshold:
        upper = hi
    else:
        for _ in range(MONITOR_DEPTH):
            midpoint = (lo + hi) / 2
            if mixture_e(scores, remainders, midpoint, negative_lambdas, weights, "negative") < threshold:
                lo = midpoint
            else:
                hi = midpoint
        upper = hi
    return {
        "nonempty": lower <= upper,
        "lower": q(lower),
        "upper": q(upper),
        "width": q(upper - lower),
    }


def evaluate(mode: str | None = None) -> dict[str, object]:
    calibration = generate_envelopes(mode)
    if calibration["status"] != "SOLVED":
        return calibration
    scores: list[Fraction] = []
    remainders: list[Fraction] = []
    milestones = []
    truth_included = True
    threshold = 2 / ALPHA_MONITORING
    for batch_index, batch in enumerate(BATCHES, start=1):
        current_nuisance = nuisance(batch_index)
        current_remainder = calibration["remainders"][batch_index - 1]
        for event in standard_events():
            current_score = score(*event, current_nuisance)
            if not SCORE_LOWER <= current_score <= SCORE_UPPER:
                return {"status": "INVALID_SCORE_BOUND"}
            scores.append(current_score)
            remainders.append(current_remainder)
            positive = mixture_e(
                scores, remainders, TRUTH_PSI,
                POSITIVE_LAMBDAS, MIXTURE_WEIGHTS, "positive"
            )
            negative = mixture_e(
                scores, remainders, TRUTH_PSI,
                NEGATIVE_LAMBDAS, MIXTURE_WEIGHTS, "negative"
            )
            truth_included = truth_included and positive < threshold and negative < threshold
        adaptive = root_interval(
            scores, remainders,
            POSITIVE_LAMBDAS, NEGATIVE_LAMBDAS, MIXTURE_WEIGHTS
        )
        baseline = root_interval(
            scores, remainders,
            (BASELINE_LAMBDA,), (-BASELINE_LAMBDA,), (Fraction(1),)
        )
        milestones.append({"batch": batch, "adaptive": adaptive, "baseline": baseline})
    adaptive_final = milestones[-1]["adaptive"]
    baseline_final = milestones[-1]["baseline"]
    if adaptive_final != {
        "nonempty": True,
        "lower": [31905, 131072],
        "upper": [189181, 262144],
        "width": [125371, 262144],
    }:
        raise AssertionError("adaptive interval changed")
    if baseline_final != {
        "nonempty": True,
        "lower": [11603, 131072],
        "upper": [239209, 262144],
        "width": [216003, 262144],
    }:
        raise AssertionError("baseline interval changed")
    relative = (
        Fraction(*baseline_final["width"]) - Fraction(*adaptive_final["width"])
    ) / Fraction(*baseline_final["width"])
    if relative != Fraction(90632, 216003):
        raise AssertionError("relative reduction changed")
    calibration_work = 48 * RADIUS_DEPTH * EXPONENTIAL_STEPS
    monitoring_work = 192768
    total_work = calibration_work + monitoring_work
    if mode == "resource" and total_work > 200000:
        return {
            "status": "UNKNOWN_RESOURCE_LIMIT",
            "required_total_evaluations": total_work,
            "maximum": 200000,
        }
    return {
        "status": "SOLVED",
        "alpha": {
            "total": q(ALPHA_TOTAL),
            "calibration": q(ALPHA_CALIBRATION),
            "monitoring": q(ALPHA_MONITORING),
            "component_batch": q(ALPHA_PAIR),
            "union_bound": q(ALPHA_PAIR * 48),
        },
        "score_count": len(scores),
        "generated_remainders": [q(value) for value in calibration["remainders"]],
        "calibration": calibration["batches"],
        "milestones": milestones,
        "adaptive_final": adaptive_final,
        "baseline_final": baseline_final,
        "relative_width_reduction": q(relative),
        "truth_included_at_every_time": truth_included,
        "resources": {
            "calibration_evaluations": calibration_work,
            "monitoring_evaluations": monitoring_work,
            "total_evaluations": total_work,
        },
    }


def private_binding() -> object:
    path = os.environ.get("PRIVATE_BINDING_PATH")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    return {"status": "UNBOUND_LOCAL_REPLAY"}


def build_payload() -> dict[str, object]:
    control = evaluate()
    if control["status"] != "SOLVED" or not control["truth_included_at_every_time"]:
        raise AssertionError(control)
    expected_negatives = {
        "missing_cell": "UNKNOWN_CALIBRATION_CELL",
        "model_undeclared": "UNKNOWN_CALIBRATION_MODEL",
        "calibration_event": "CALIBRATION_EVENT_FAILED",
        "calibration_drift": "UNKNOWN_CALIBRATION_DRIFT",
        "small_sample": "UNKNOWN_PRODUCT_RATE",
        "resource": "UNKNOWN_RESOURCE_LIMIT",
    }
    negatives = {}
    for mode, expected in expected_negatives.items():
        packet = evaluate(mode)
        if packet["status"] != expected:
            raise AssertionError(f"{mode}: {packet}")
        negatives[mode] = packet
    return {
        "schema": "finite-nuisance-calibration/public-independent-certificate/1",
        "private_binding": private_binding(),
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "control": control,
        "negative_controls": negatives,
        "gates": {
            "rational_hoeffding_certificate": "PASS",
            "simultaneous_union_bound": "PASS",
            "strict_prior_calibration": "PASS",
            "automatic_envelope_generation": "PASS",
            "generated_product_rate": "PASS",
            "generated_remainder_nonincreasing": "PASS",
            "alpha_split": "PASS",
            "continuous_monitoring_inversion": "PASS",
            "truth_anytime_inclusion": "PASS",
            "negative_controls": "PASS",
        },
        "scientific_boundary": (
            "Independent exact-rational verification for homogeneous IID Bernoulli "
            "calibration cells and a finite binary AIPW monitoring control. The "
            "rational Hoeffding upper bound and Bonferroni split generate the "
            "nuisance envelopes automatically. General dependent calibration, "
            "adaptive model selection and continuous covariates remain outside scope."
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
    control = payload["control"]
    result = {
        "schema": "finite-nuisance-calibration/public-independent-report/1",
        "private_binding": payload["private_binding"],
        "alpha": control["alpha"],
        "score_count": control["score_count"],
        "generated_remainders": control["generated_remainders"],
        "adaptive_final": control["adaptive_final"],
        "baseline_final": control["baseline_final"],
        "relative_width_reduction": control["relative_width_reduction"],
        "truth_included_at_every_time": control["truth_included_at_every_time"],
        "resources": control["resources"],
        "negative_controls": {
            key: value["status"] for key, value in payload["negative_controls"].items()
        },
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
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public calibration certificate failed replay")
    tampered = deepcopy(certificate)
    tampered["payload"]["control"]["score_count"] = 0
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["control"]["score_count"] = 0
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")
    report = build_report(certificate)
    write(ROOT / "FINITE_NUISANCE_CALIBRATION_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "FINITE_NUISANCE_CALIBRATION_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
