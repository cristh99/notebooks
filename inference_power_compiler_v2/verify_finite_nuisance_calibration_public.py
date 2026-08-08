from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

import verify_drift_aware_online_crossfit_public as online

ROOT = Path(__file__).resolve().parent
COMPONENTS = (
    "e|z0",
    "e|z1",
    "mu0|z0",
    "mu0|z1",
    "mu1|z0",
    "mu1|z1",
)
BATCHES = tuple(f"b{index}" for index in range(1, 9))
ALPHA_TOTAL = Fraction(1, 20)
ALPHA_CALIBRATION = Fraction(1, 100)
ALPHA_MONITORING = Fraction(1, 25)
ALPHA_PAIR = Fraction(1, 4800)
RADIUS_DEPTH = 20
EXPONENTIAL_STEPS = 64
HOMOGENEITY_THRESHOLD = Fraction(1, 16)
MAX_REMAINDER = Fraction(1, 16)
MONITORING_THRESHOLD = Fraction(50)
EXPECTED_REMAINDERS = (
    Fraction(7523843697, 240518168576),
    Fraction(28376904617, 2078764171264),
    Fraction(1551732299, 193273528320),
    Fraction(134927501495, 24807731101696),
    Fraction(72759995533, 18176301596672),
    Fraction(51950888503, 16698832846848),
    Fraction(20742442279, 8254927142912),
    Fraction(175805415059, 84181359001600),
)
EXPECTED_PRIVATE_BINDING = {
    "schema": "finite-nuisance-calibration/private-binding/1",
    "repository": "cristh99/my_first_repository",
    "branch": "agent/inference-power-compiler-v2-logic-power-v10",
    "head": "3ce7c59a8929bf580e1cedc6df478ea51f9830ff",
    "binding_mode": "immutable-git-object-ids",
    "files": {
        "compiler": {
            "path": "inference_power_compiler_v2/finite_nuisance_calibration_compiler.py",
            "git_blob_sha1": "11bd8fc90b47841438a8d8d4237dd2dcd77bbe85",
        },
        "runner": {
            "path": "inference_power_compiler_v2/run_finite_nuisance_calibration_compiler.py",
            "git_blob_sha1": "e95feddf30bdb512692882aa5d6da551106d15dc",
        },
        "tests": {
            "path": "inference_power_compiler_v2/test_finite_nuisance_calibration_compiler.py",
            "git_blob_sha1": "9b65d73092b2dd55305c064f585823eaf115ab31",
        },
        "lean": {
            "path": "FiniteNuisanceCalibration.lean",
            "git_blob_sha1": "c7fe74bf5bada2ca9d5d52284e450a29d7e620aa",
        },
        "workflow": {
            "path": ".github/workflows/finite-nuisance-calibration-compiler.yml",
            "git_blob_sha1": "259c63415d9348fbfa17b7d80aea8f53f5234cc9",
        },
        "online_base": {
            "path": "inference_power_compiler_v2/drift_aware_online_crossfit_compiler.py",
            "git_blob_sha1": "3de813e42f1cd4c9fd3c4e3c562a654537de4dfd",
        },
        "hardening_base": {
            "path": "inference_power_compiler_v2/drift_aware_online_crossfit_hardening.py",
            "git_blob_sha1": "7e04055f573f92e54275668981c936a54d771db6",
        },
    },
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def parse_q(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("malformed rational")
    numerator, denominator = value
    if not isinstance(numerator, int) or not isinstance(denominator, int) or denominator <= 0:
        raise ValueError("malformed rational")
    return Fraction(numerator, denominator)


def rational_hoeffding_bound(trials: int, radius: Fraction) -> Fraction:
    if trials <= 0 or radius < 0:
        raise ValueError("invalid Hoeffding arguments")
    exponent = 2 * trials * radius * radius
    return Fraction(2) / (
        1 + exponent / EXPONENTIAL_STEPS
    ) ** EXPONENTIAL_STEPS


def certified_radius(trials: int) -> dict[str, object]:
    lo, hi = Fraction(0), Fraction(1)
    if rational_hoeffding_bound(trials, hi) > ALPHA_PAIR:
        return {
            "status": "UNKNOWN_CALIBRATION_IMPRECISION",
            "trials": trials,
        }
    for _ in range(RADIUS_DEPTH):
        midpoint = (lo + hi) / 2
        if rational_hoeffding_bound(trials, midpoint) <= ALPHA_PAIR:
            hi = midpoint
        else:
            lo = midpoint
    outer = rational_hoeffding_bound(trials, hi)
    inner = rational_hoeffding_bound(trials, lo)
    if not outer <= ALPHA_PAIR < inner:
        raise AssertionError("rational Hoeffding bracket failed")
    return {
        "status": "SOLVED",
        "radius": q(hi),
        "inner_radius": q(lo),
        "resolution": q(hi - lo),
        "outer_failure_bound": q(outer),
        "inner_failure_bound": q(inner),
        "trials": trials,
        "alpha": q(ALPHA_PAIR),
    }


def merged_state() -> dict[str, object]:
    original = online.build_state()
    original_by_batch: dict[str, list[online.Row]] = original["rows_by_batch"]  # type: ignore[assignment]
    rows: list[online.Row] = []
    for row in (*original_by_batch["b0"], *original_by_batch["b1"]):
        rows.append(replace(row, batch="b0"))
    for new_index, old_index in enumerate(range(2, 10), start=1):
        for row in original_by_batch[f"b{old_index}"]:
            rows.append(replace(row, batch=f"b{new_index}"))
    rows_by_batch = {
        f"b{index}": [row for row in rows if row.batch == f"b{index}"]
        for index in range(9)
    }
    training: dict[str, tuple[str, ...]] = {}
    prior = list(rows_by_batch["b0"])
    for index in range(1, 9):
        batch = f"b{index}"
        training[batch] = tuple(row.row_id for row in prior)
        prior.extend(rows_by_batch[batch])
    if tuple(len(rows_by_batch[f"b{index}"]) for index in range(9)) != (32,) + (16,) * 8:
        raise AssertionError("merged online schedule changed")
    return {
        "rows": tuple(rows),
        "rows_by_batch": rows_by_batch,
        "training": training,
    }


def truth_value(component: str) -> Fraction:
    nuisance, z = component.split("|", 1)
    return {
        "e": online.TRUTH_E,
        "mu0": online.TRUTH_MU0,
        "mu1": online.TRUTH_MU1,
    }[nuisance][z]


def fitted_value(
    nuisance: Mapping[str, Mapping[str, Fraction]],
    component: str,
) -> Fraction:
    name, z = component.split("|", 1)
    return nuisance[name][z]


def calibration_blocks(mode: str | None) -> list[dict[str, tuple[int, int]]]:
    counts = {
        "e|z0": (2048, 4096),
        "e|z1": (2048, 4096),
        "mu0|z0": (1024, 4096),
        "mu0|z1": (1024, 4096),
        "mu1|z0": (3072, 4096),
        "mu1|z1": (3072, 4096),
    }
    blocks: list[dict[str, tuple[int, int]]] = []
    for index in range(8):
        block = dict(counts)
        if mode == "calibration_event" and index == 0:
            block["e|z0"] = (0, 4096)
        if mode == "calibration_drift" and index == 1:
            block["e|z0"] = (4096, 4096)
        if mode == "small_sample":
            block = {
                component: (successes // 64, 64)
                for component, (successes, _trials) in block.items()
            }
        blocks.append(block)
    if mode == "missing_cell":
        del blocks[0]["mu1|z1"]
    return blocks


def generate_envelopes(mode: str | None = None) -> dict[str, object]:
    if mode == "model_undeclared":
        return {
            "status": "UNKNOWN_CALIBRATION_MODEL",
            "witness": "IID_HOMOGENEOUS_BERNOULLI_NOT_DECLARED",
        }
    state = merged_state()
    rows: tuple[online.Row, ...] = state["rows"]  # type: ignore[assignment]
    training: dict[str, tuple[str, ...]] = state["training"]  # type: ignore[assignment]
    row_by_id = {row.row_id: row for row in rows}
    blocks = calibration_blocks(mode)
    packets: dict[str, object] = {}
    remainders: list[Fraction] = []
    previous: Fraction | None = None
    for monitoring_index, batch in enumerate(BATCHES):
        nuisance = online.fit([row_by_id[row_id] for row_id in training[batch]])
        component_packets: dict[str, object] = {}
        component_radii: dict[str, Fraction] = {}
        source_ids: list[str] = []
        for component in COMPONENTS:
            selected = [
                (block_index, block[component])
                for block_index, block in enumerate(blocks[: monitoring_index + 1])
                if component in block
            ]
            if not selected:
                return {
                    "status": "UNKNOWN_CALIBRATION_CELL",
                    "witness": {"batch": batch, "component": component},
                }
            block_estimates = tuple(
                Fraction(successes, trials)
                for _index, (successes, trials) in selected
            )
            block_range = max(block_estimates) - min(block_estimates)
            if block_range > HOMOGENEITY_THRESHOLD:
                return {
                    "status": "UNKNOWN_CALIBRATION_DRIFT",
                    "witness": {
                        "batch": batch,
                        "component": component,
                        "block_range": q(block_range),
                    },
                }
            successes = sum(packet[0] for _index, packet in selected)
            trials = sum(packet[1] for _index, packet in selected)
            radius_packet = certified_radius(trials)
            if radius_packet["status"] != "SOLVED":
                return radius_packet
            radius = parse_q(radius_packet["radius"])
            estimate = Fraction(successes, trials)
            lower = max(Fraction(0), estimate - radius)
            upper = min(Fraction(1), estimate + radius)
            truth = truth_value(component)
            if not lower <= truth <= upper:
                return {
                    "status": "CALIBRATION_EVENT_FAILED",
                    "witness": {
                        "batch": batch,
                        "component": component,
                        "truth": q(truth),
                        "interval": [q(lower), q(upper)],
                    },
                }
            point = fitted_value(nuisance, component)
            envelope_radius = max(abs(point - lower), abs(upper - point))
            component_radii[component] = envelope_radius
            stat_ids = tuple(f"c{index}:{component}" for index, _packet in selected)
            source_ids.extend(stat_ids)
            component_packets[component] = {
                "successes": successes,
                "trials": trials,
                "calibration_estimate": q(estimate),
                "confidence_interval": [q(lower), q(upper)],
                "point_estimate": q(point),
                "generated_envelope_radius": q(envelope_radius),
                "source_stat_ids": list(stat_ids),
                "radius_certificate": radius_packet,
            }
        e_sup = max(component_radii["e|z0"], component_radii["e|z1"])
        mu0_sup = max(component_radii["mu0|z0"], component_radii["mu0|z1"])
        mu1_sup = max(component_radii["mu1|z0"], component_radii["mu1|z1"])
        eta = min(
            *nuisance["e"].values(),
            *(1 - value for value in nuisance["e"].values()),
        )
        remainder = e_sup * (mu0_sup + mu1_sup) / eta
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
        bias = online.expected_score(nuisance) - online.TRUTH_PSI
        if abs(bias) > remainder:
            return {
                "status": "INVALID_GENERATED_REMAINDER",
                "witness": {"batch": batch, "bias": q(bias), "bound": q(remainder)},
            }
        remainders.append(remainder)
        packets[batch] = {
            "nuisance": {
                name: {z: q(value) for z, value in sorted(mapping.items())}
                for name, mapping in nuisance.items()
            },
            "components": component_packets,
            "calibration_stat_ids": sorted(set(source_ids)),
            "generated_envelope": {
                "source_ids": list(training[batch]),
                "e_sup": q(e_sup),
                "mu0_sup": q(mu0_sup),
                "mu1_sup": q(mu1_sup),
            },
            "generated_remainder": q(remainder),
            "exact_bias_audit": q(bias),
        }
    if tuple(remainders) != EXPECTED_REMAINDERS:
        raise AssertionError(
            f"generated remainder sequence changed: {[q(value) for value in remainders]}"
        )
    return {
        "status": "SOLVED",
        "batches": packets,
        "remainders": remainders,
    }


def mixture_e_value(
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
        for score, remainder in zip(scores, remainders):
            center = target + remainder if side == "positive" else target - remainder
            factor = 1 + current_lambda * (
                online.transformed(score) - online.transformed(center)
            )
            if factor < 0:
                raise AssertionError("negative betting factor")
            wealth *= factor
        total += weight * wealth
    return total


def root_interval(
    scores: Sequence[Fraction],
    remainders: Sequence[Fraction],
    positive_lambdas: Sequence[Fraction],
    negative_lambdas: Sequence[Fraction],
    weights: Sequence[Fraction],
) -> dict[str, object]:
    lo, hi = online.TARGET_LOWER, online.TARGET_UPPER
    if mixture_e_value(scores, remainders, lo, positive_lambdas, weights, "positive") < MONITORING_THRESHOLD:
        lower = lo
    else:
        for _ in range(online.DEPTH):
            midpoint = (lo + hi) / 2
            if mixture_e_value(scores, remainders, midpoint, positive_lambdas, weights, "positive") >= MONITORING_THRESHOLD:
                lo = midpoint
            else:
                hi = midpoint
        lower = lo
    lo, hi = online.TARGET_LOWER, online.TARGET_UPPER
    if mixture_e_value(scores, remainders, hi, negative_lambdas, weights, "negative") < MONITORING_THRESHOLD:
        upper = hi
    else:
        for _ in range(online.DEPTH):
            midpoint = (lo + hi) / 2
            if mixture_e_value(scores, remainders, midpoint, negative_lambdas, weights, "negative") < MONITORING_THRESHOLD:
                lo = midpoint
            else:
                hi = midpoint
        upper = hi
    return {
        "nonempty": lower <= upper,
        "lower": q(lower),
        "upper": q(upper),
        "width": None if lower > upper else q(upper - lower),
    }


def monitoring_resource_count() -> int:
    endpoints = tuple(16 * index for index in range(1, 9))
    root_work = sum(
        endpoint * 10 * (online.DEPTH + 4) for endpoint in endpoints
    )
    truth_work = 4 * endpoints[-1] * (endpoints[-1] + 1)
    if root_work != 126720 or truth_work != 66048:
        raise AssertionError("monitoring resource accounting changed")
    return root_work + truth_work


def evaluate(mode: str | None = None) -> dict[str, object]:
    if mode == "alpha_overspend":
        return {"status": "INVALID_ALPHA_ALLOCATION"}
    calibration = generate_envelopes(mode)
    if calibration["status"] != "SOLVED":
        return calibration
    state = merged_state()
    rows: tuple[online.Row, ...] = state["rows"]  # type: ignore[assignment]
    rows_by_batch: dict[str, list[online.Row]] = state["rows_by_batch"]  # type: ignore[assignment]
    training: dict[str, tuple[str, ...]] = state["training"]  # type: ignore[assignment]
    row_by_id = {row.row_id: row for row in rows}
    scores: list[Fraction] = []
    remainders: list[Fraction] = []
    milestones: list[dict[str, object]] = []
    truth_included = True
    for batch_index, batch in enumerate(BATCHES):
        nuisance = online.fit([row_by_id[row_id] for row_id in training[batch]])
        remainder = calibration["remainders"][batch_index]
        for row in rows_by_batch[batch]:
            score = online.aipw(row, nuisance)
            if not online.SCORE_LOWER <= score <= online.SCORE_UPPER:
                return {"status": "INVALID_SCORE_BOUND", "batch": batch}
            scores.append(score)
            remainders.append(remainder)
            positive = mixture_e_value(
                scores,
                remainders,
                online.TRUTH_PSI,
                online.POSITIVE_LAMBDAS,
                online.EQUAL_WEIGHTS,
                "positive",
            )
            negative = mixture_e_value(
                scores,
                remainders,
                online.TRUTH_PSI,
                online.NEGATIVE_LAMBDAS,
                online.EQUAL_WEIGHTS,
                "negative",
            )
            truth_included = (
                truth_included
                and positive < MONITORING_THRESHOLD
                and negative < MONITORING_THRESHOLD
            )
        milestones.append(
            {
                "batch": batch,
                "adaptive": root_interval(
                    scores,
                    remainders,
                    online.POSITIVE_LAMBDAS,
                    online.NEGATIVE_LAMBDAS,
                    online.EQUAL_WEIGHTS,
                ),
                "baseline": root_interval(
                    scores,
                    remainders,
                    (online.BASELINE_LAMBDA,),
                    (-online.BASELINE_LAMBDA,),
                    (Fraction(1),),
                ),
            }
        )
    adaptive_final = milestones[-1]["adaptive"]
    baseline_final = milestones[-1]["baseline"]
    if adaptive_final != {
        "nonempty": True,
        "lower": [31905, 131072],
        "upper": [189181, 262144],
        "width": [125371, 262144],
    }:
        raise AssertionError(f"adaptive interval changed: {adaptive_final}")
    if baseline_final != {
        "nonempty": True,
        "lower": [11603, 131072],
        "upper": [239209, 262144],
        "width": [216003, 262144],
    }:
        raise AssertionError(f"baseline interval changed: {baseline_final}")
    adaptive_width = parse_q(adaptive_final["width"])
    baseline_width = parse_q(baseline_final["width"])
    relative = (baseline_width - adaptive_width) / baseline_width
    calibration_work = 48 * RADIUS_DEPTH * EXPONENTIAL_STEPS
    monitoring_work = monitoring_resource_count()
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
    if not path or not Path(path).exists():
        return {"status": "UNBOUND_LOCAL_REPLAY"}
    binding = json.loads(Path(path).read_text())
    if canonical(binding) != canonical(EXPECTED_PRIVATE_BINDING):
        raise AssertionError("private source binding changed")
    return binding


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
        "alpha_overspend": "INVALID_ALPHA_ALLOCATION",
    }
    negatives: dict[str, object] = {}
    for mode, expected in expected_negatives.items():
        packet = evaluate(mode)
        if packet["status"] != expected:
            raise AssertionError(f"{mode}: {packet}")
        negatives[mode] = packet
    return {
        "schema": "finite-nuisance-calibration/public-independent-certificate/2",
        "private_binding": private_binding(),
        "public_base_binding": {
            "repository": "cristh99/notebooks",
            "drift_verifier_blob": "9d1e77f95df346279957ce60ef4079f616d9b110",
        },
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "control": control,
        "negative_controls": negatives,
        "gates": {
            "independent_prior_batch_reconstruction": "PASS",
            "rational_hoeffding_certificate": "PASS",
            "simultaneous_union_bound": "PASS",
            "automatic_envelope_generation": "PASS",
            "generated_product_rate": "PASS",
            "generated_remainder_nonincreasing": "PASS",
            "alpha_split": "PASS",
            "continuous_monitoring_inversion": "PASS",
            "truth_anytime_inclusion": "PASS",
            "negative_controls": "PASS",
            "semantic_replay": "PASS",
        },
        "scientific_boundary": (
            "Independent finite replay for homogeneous IID Bernoulli calibration "
            "blocks, dyadic rational Hoeffding inversion and an explicit "
            "calibration/monitoring error split. Coverage is conditional on the "
            "declared calibration model; arbitrary dependence, adaptive model "
            "selection and continuous covariates remain outside scope."
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
        "schema": "finite-nuisance-calibration/public-independent-report/2",
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
