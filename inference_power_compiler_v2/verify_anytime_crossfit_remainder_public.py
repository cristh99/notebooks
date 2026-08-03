from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

from verify_anytime_crossfit_public import (
    ALPHA,
    DEPTH,
    NEGATIVE_LAMBDAS,
    POSITIVE_LAMBDAS,
    SCORE_LOWER,
    SCORE_UPPER,
    TARGET_RANGE,
    WEIGHTS,
    TRUTH_PSI,
    canonical,
    digest,
    fit,
    lower_root,
    mixture,
    ordered_monitoring_batch,
    posterior if False else q,
    score,
    standard_rows,
    upper_root,
)

ROOT = Path(__file__).resolve().parent
PRIVATE_BINDING = {
    "repository": "cristh99/my_first_repository",
    "pull_request": 68,
    "head": "cb103b068de777ba8117eb14986ae22e727ef2f2",
    "blobs": {
        "base_compiler": "80831b1d9d3d554474928082ebfae7c1c204e371",
        "base_runner": "4d81eb613d3373514361be4e19b93aece45eb8f3",
        "remainder_runner": "84016bc6e040442b04b191f6c7343243f6b4cadb",
        "remainder_tests": "948b66c661a4268f888ed42f1ba05f14a791c381",
        "remainder_lean": "991839d2294843dbce836b07369f7a026296b294",
        "remainder_workflow": "b141c0b84de589f64474953bb71f5a6066735317",
        "public_base_verifier": "641d161088e50dbce88c687ad6ca52aa307c8812",
    },
}
REMAINDER = Fraction(1, 64)


def corrupt_warmup():
    warmup = standard_rows("b0", "w")
    corrupt_index = next(
        index
        for index, row in enumerate(warmup)
        if row[2] == "z0" and row[3] == 1 and row[4] == 0
    )
    identifier, batch, z, action, _outcome = warmup[corrupt_index]
    warmup[corrupt_index] = (identifier, batch, z, action, 1)
    removable = next(
        row[0] for row in warmup if row[2] == "z0" and row[3] == 0
    )
    return warmup, removable


def nuisance_errors(nuisance: Mapping[str, Mapping[str, Fraction]]):
    truth = {
        "e": {"z0": Fraction(1, 2), "z1": Fraction(1, 2)},
        "mu0": {"z0": Fraction(0), "z1": Fraction(1, 4)},
        "mu1": {"z0": Fraction(1, 2), "z1": Fraction(3, 4)},
    }
    support = ("z0", "z1")
    errors = {
        name: sum(
            ((nuisance[name][z] - truth[name][z]) ** 2 for z in support),
            Fraction(0),
        )
        / 2
        for name in ("e", "mu0", "mu1")
    }
    product = 2 * errors["e"] * (errors["mu0"] + errors["mu1"])
    return errors, product


def transform(score_value: Fraction) -> Fraction:
    return (score_value - SCORE_LOWER) / (SCORE_UPPER - SCORE_LOWER)


def target_from_normalized(value: Fraction) -> Fraction:
    return SCORE_LOWER + (SCORE_UPPER - SCORE_LOWER) * value


def build_payload() -> dict[str, object]:
    warmup, removable = corrupt_warmup()
    batch1 = ordered_monitoring_batch("b1", "a")
    batch2 = ordered_monitoring_batch("b2", "b")
    rows = warmup + batch1 + batch2
    by_id = {row[0]: row for row in rows}
    training = {
        "b1": tuple(row[0] for row in warmup if row[0] != removable),
        "b2": tuple(
            row[0] for row in (*warmup, *batch1) if row[0] != removable
        ),
    }
    batches: dict[str, object] = {}
    all_scores: list[Fraction] = []
    expected = {
        "b1": {
            "nuisance": {
                "e": {"z0": Fraction(4, 7), "z1": Fraction(1, 2)},
                "mu0": {"z0": Fraction(0), "z1": Fraction(1, 4)},
                "mu1": {"z0": Fraction(3, 4), "z1": Fraction(3, 4)},
            },
            "bias": Fraction(1, 64),
            "product": Fraction(1, 6272),
        },
        "b2": {
            "nuisance": {
                "e": {"z0": Fraction(8, 15), "z1": Fraction(1, 2)},
                "mu0": {"z0": Fraction(0), "z1": Fraction(1, 4)},
                "mu1": {"z0": Fraction(5, 8), "z1": Fraction(3, 4)},
            },
            "bias": Fraction(1, 256),
            "product": Fraction(1, 115200),
        },
    }

    for batch, held_out in (("b1", batch1), ("b2", batch2)):
        nuisance = fit([by_id[identifier] for identifier in training[batch]])
        if nuisance != expected[batch]["nuisance"]:
            raise AssertionError(f"{batch} nuisance changed: {nuisance}")
        scores = [score(row, nuisance) for row in held_out]
        if not all(SCORE_LOWER <= value <= SCORE_UPPER for value in scores):
            raise AssertionError(f"{batch} score bound changed")
        mean_score = sum(scores, Fraction(0)) / len(scores)
        bias = mean_score - TRUTH_PSI
        if bias != expected[batch]["bias"]:
            raise AssertionError(f"{batch} bias changed: {bias}")
        errors, product_bound = nuisance_errors(nuisance)
        if product_bound != expected[batch]["product"]:
            raise AssertionError(f"{batch} product changed: {product_bound}")
        all_scores.extend(scores)
        batches[batch] = {
            "training_ids": list(training[batch]),
            "held_out_ids": [row[0] for row in held_out],
            "nuisance": {
                name: {z: q(value) for z, value in sorted(values.items())}
                for name, values in nuisance.items()
            },
            "score_counts": {
                f"{value.numerator}/{value.denominator}": scores.count(value)
                for value in sorted(set(scores))
            },
            "score_mean": q(mean_score),
            "exact_bias": q(bias),
            "errors": {name: q(value) for name, value in errors.items()},
            "product_bound": q(product_bound),
        }

    normalized = [transform(value) for value in all_scores]
    threshold = Fraction(2, 1) / ALPHA
    positive_reference = transform(TRUTH_PSI + REMAINDER)
    negative_reference = transform(TRUTH_PSI - REMAINDER)
    history: list[dict[str, object]] = []
    included_at_every_time = True

    for time in range(1, len(normalized) + 1):
        prefix = normalized[:time]
        lower = lower_root(prefix, threshold)
        upper = upper_root(prefix, threshold)
        lower_target = max(
            TARGET_RANGE[0],
            target_from_normalized(Fraction(*lower["outer"])) - REMAINDER,
        )
        upper_target = min(
            TARGET_RANGE[1],
            target_from_normalized(Fraction(*upper["outer"])) + REMAINDER,
        )
        positive_e = mixture(prefix, positive_reference, POSITIVE_LAMBDAS)
        negative_e = mixture(prefix, negative_reference, NEGATIVE_LAMBDAS)
        included = (
            lower_target <= TRUTH_PSI <= upper_target
            and positive_e < threshold
            and negative_e < threshold
        )
        included_at_every_time = included_at_every_time and included
        history.append(
            {
                "time": time,
                "target_interval": {
                    "lower": q(lower_target),
                    "upper": q(upper_target),
                    "width": q(upper_target - lower_target),
                },
                "roots": {"lower": lower, "upper": upper},
                "truth": {
                    "included": included,
                    "positive_e_value": q(positive_e),
                    "negative_e_value": q(negative_e),
                },
            }
        )

    if not included_at_every_time:
        raise AssertionError("truth exited nonzero-remainder sequence")
    if not abs(expected["b1"]["bias"]) <= REMAINDER:
        raise AssertionError("declared remainder misses batch one")
    if not abs(expected["b2"]["bias"]) <= REMAINDER:
        raise AssertionError("declared remainder misses batch two")
    too_small = Fraction(1, 256)
    if abs(expected["b1"]["bias"]) <= too_small:
        raise AssertionError("too-small remainder was not falsified")

    return {
        "schema": "anytime-crossfit-remainder/public-independent-payload/1",
        "private_binding": PRIVATE_BINDING,
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "remainder_bound": q(REMAINDER),
        "normalized_remainder": [1, 160],
        "batches": batches,
        "score_records": len(all_scores),
        "score_range": [q(min(all_scores)), q(max(all_scores))],
        "required_mixture_evaluations": len(all_scores)
        * (len(POSITIVE_LAMBDAS) + len(NEGATIVE_LAMBDAS))
        * (DEPTH + 2),
        "history": history,
        "final": history[-1],
        "truth_included_at_every_time": included_at_every_time,
        "maximum_product_bound": [1, 6272],
        "negative_control": {
            "claimed_remainder": q(too_small),
            "status": "INVALID_REMAINDER_BOUND",
            "witness_batch": "b1",
            "exact_bias": [1, 64],
        },
        "gates": {
            "imperfect_nuisance": "PASS",
            "nonzero_remainder": "PASS",
            "batch_biases": "PASS",
            "product_rate_packets": "PASS",
            "truth_anytime_inclusion": "PASS",
            "too_small_remainder_rejection": "PASS",
            "continuous_root_inversion": "PASS",
        },
        "scientific_boundary": (
            "Independent finite control with two imperfect progressive nuisance "
            "fits and exact conditional score biases. It validates interval "
            "expansion by a declared nonzero remainder; it does not establish a "
            "uniform learner-rate theorem over arbitrary distributions."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload, claimed = certificate.get("payload"), certificate.get("sha256")
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
        "schema": "anytime-crossfit-remainder/public-independent-report/1",
        "remainder_bound": payload["remainder_bound"],
        "normalized_remainder": payload["normalized_remainder"],
        "batches": payload["batches"],
        "score_records": payload["score_records"],
        "score_range": payload["score_range"],
        "required_mixture_evaluations": payload["required_mixture_evaluations"],
        "truth_included_at_every_time": payload["truth_included_at_every_time"],
        "final_target_interval": payload["final"]["target_interval"],
        "maximum_product_bound": payload["maximum_product_bound"],
        "negative_control": payload["negative_control"],
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
        raise AssertionError("public nonzero-remainder self replay failed")
    tampered = deepcopy(certificate)
    tampered["payload"]["remainder_bound"] = [0, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("public remainder hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["remainder_bound"] = [0, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("public remainder semantic forgery accepted")
    report = build_report(certificate)
    write(ROOT / "ANYTIME_CROSSFIT_REMAINDER_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "ANYTIME_CROSSFIT_REMAINDER_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
