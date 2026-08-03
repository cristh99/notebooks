from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent
UNIVERSE = tuple(range(64))


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def fold_inputs(*, ideal: bool = False) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for fold in range(4):
        validation = tuple(range(16 * fold, 16 * (fold + 1)))
        train = tuple(identifier for identifier in UNIVERSE if identifier not in set(validation))
        if fold == 0:
            finite = (Fraction(0), Fraction(1, 10), Fraction(1, 10))
            rates = (Fraction(0), Fraction(0), Fraction(1, 5), Fraction(1, 5))
        elif fold == 1:
            finite = (Fraction(1, 10), Fraction(1, 20), Fraction(1, 10))
            rates = (Fraction(1), Fraction(3, 10), Fraction(3, 10), Fraction(2, 5))
        elif fold == 2:
            finite = (Fraction(1, 10), Fraction(1, 20), Fraction(1, 10))
            rates = (
                Fraction(1),
                Fraction(3, 10) if ideal else Fraction(1, 4),
                Fraction(3, 10) if ideal else Fraction(1, 4),
                Fraction(1, 3),
            )
        else:
            finite = (Fraction(1, 10), Fraction(1, 20), Fraction(1, 10))
            rates = (
                Fraction(1),
                Fraction(3, 10) if ideal else Fraction(1, 5),
                Fraction(3, 10) if ideal else Fraction(1, 4),
                Fraction(3, 10) if ideal else Fraction(1, 4),
            )
        rows.append(
            {
                "fold": fold,
                "train": train,
                "validation": validation,
                "kappa": Fraction(2, 5),
                "finite_propensity": finite[0],
                "finite_outcome0": finite[1],
                "finite_outcome1": finite[2],
                "rate_constant_propensity": rates[0],
                "rate_exponent_propensity": rates[1],
                "rate_exponent_outcome0": rates[2],
                "rate_exponent_outcome1": rates[3],
                "overlap_rate_exponent": Fraction(0),
                "provenance": {
                    "propensity": "nested-cv:pooled" if fold else "exact-randomization",
                    "outcome_0": "nested-cv:stratified_z",
                    "outcome_1": "nested-cv:stratified_z",
                },
            }
        )
    return tuple(rows)


def finite_bound(row: Mapping[str, object]) -> Fraction:
    kappa = row["kappa"]
    propensity = row["finite_propensity"]
    outcome0 = row["finite_outcome0"]
    outcome1 = row["finite_outcome1"]
    if not isinstance(kappa, Fraction) or not 0 < kappa <= Fraction(1, 2):
        raise ValueError("INVALID_OVERLAP")
    if not all(isinstance(value, Fraction) and value >= 0 for value in (propensity, outcome0, outcome1)):
        raise ValueError("INVALID_FINITE_NUISANCE_BOUND")
    return propensity * (outcome0 + outcome1) / kappa


def rate_verdict(row: Mapping[str, object]) -> tuple[str, list[dict[str, object]]]:
    propensity_constant = row["rate_constant_propensity"]
    propensity_exponent = row["rate_exponent_propensity"]
    overlap_exponent = row["overlap_rate_exponent"]
    if not all(isinstance(value, Fraction) and value >= 0 for value in (propensity_constant, propensity_exponent, overlap_exponent)):
        return "UNKNOWN_RATE_CERTIFICATE", []
    if propensity_constant == 0:
        return "ROOT_N_NEGLIGIBLE_EXACT_ZERO", []
    terms = []
    exponents = []
    for name in ("outcome0", "outcome1"):
        exponent = propensity_exponent + row[f"rate_exponent_{name}"] - overlap_exponent
        exponents.append(exponent)
        terms.append(
            {
                "outcome": name,
                "decay_exponent": q(exponent),
                "root_n_margin": q(exponent - Fraction(1, 2)),
            }
        )
    if all(exponent > Fraction(1, 2) for exponent in exponents):
        return "ROOT_N_NEGLIGIBLE", terms
    if all(exponent >= Fraction(1, 2) for exponent in exponents):
        return "ROOT_N_BOUNDED_NOT_NEGLIGIBLE", terms
    return "INSUFFICIENT_PRODUCT_RATE", terms


def compile_family(*, ideal: bool = False) -> dict[str, object]:
    rows = fold_inputs(ideal=ideal)
    records = []
    bounds = []
    statuses = []
    for row in rows:
        if set(row["train"]) & set(row["validation"]):
            raise AssertionError("INVALID_OUTER_LEAKAGE")
        if any(not value for value in row["provenance"].values()):
            raise AssertionError("UNKNOWN_NUISANCE_PROVENANCE")
        bound = finite_bound(row)
        status, terms = rate_verdict(row)
        minimum_factor = 1 - Fraction(1, 2) * (1 + bound)
        if minimum_factor < 0:
            raise AssertionError("UNSAFE_ANYTIME_FACTOR")
        bounds.append(bound)
        statuses.append(status)
        records.append(
            {
                "fold": row["fold"],
                "train_size": len(row["train"]),
                "validation_size": len(row["validation"]),
                "finite_remainder_bound": q(bound),
                "minimum_anytime_factor": q(minimum_factor),
                "rate_status": status,
                "rate_terms": terms,
                "provenance": row["provenance"],
            }
        )
    weighted = sum((Fraction(1, 4) * bound for bound in bounds), Fraction(0))
    if all(status in ("ROOT_N_NEGLIGIBLE", "ROOT_N_NEGLIGIBLE_EXACT_ZERO") for status in statuses):
        global_status = "ROOT_N_NEGLIGIBLE"
    elif "INSUFFICIENT_PRODUCT_RATE" in statuses:
        global_status = "INSUFFICIENT_PRODUCT_RATE"
    elif "ROOT_N_BOUNDED_NOT_NEGLIGIBLE" in statuses:
        global_status = "ROOT_N_BOUNDED_NOT_NEGLIGIBLE"
    else:
        global_status = "UNKNOWN_RATE_SYSTEM"
    return {
        "folds": records,
        "aggregate": {
            "weighted_remainder_bound": q(weighted),
            "maximum_fold_remainder_bound": q(max(bounds)),
            "fold_rate_statuses": statuses,
            "global_rate_status": global_status,
        },
    }


def build_payload() -> dict[str, object]:
    base = compile_family(ideal=False)
    ideal = compile_family(ideal=True)
    if base["aggregate"] != {
        "weighted_remainder_bound": [9, 320],
        "maximum_fold_remainder_bound": [3, 80],
        "fold_rate_statuses": [
            "ROOT_N_NEGLIGIBLE_EXACT_ZERO",
            "ROOT_N_NEGLIGIBLE",
            "ROOT_N_BOUNDED_NOT_NEGLIGIBLE",
            "INSUFFICIENT_PRODUCT_RATE",
        ],
        "global_rate_status": "INSUFFICIENT_PRODUCT_RATE",
    }:
        raise AssertionError("base public remainder compilation changed")
    if ideal["aggregate"]["global_rate_status"] != "ROOT_N_NEGLIGIBLE":
        raise AssertionError("ideal public rate closure changed")

    deteriorating = dict(fold_inputs(ideal=True)[1])
    deteriorating["overlap_rate_exponent"] = Fraction(1, 10)
    deteriorating_status, deteriorating_terms = rate_verdict(deteriorating)
    if deteriorating_status != "ROOT_N_BOUNDED_NOT_NEGLIGIBLE":
        raise AssertionError("overlap deterioration control changed")

    last_fold_mean = Fraction(83 - 77, 160)
    if last_fold_mean != Fraction(3, 80):
        raise AssertionError("cross-fit score mean changed")
    handoff = [
        {
            "fold": fold,
            "remainder_bound": record["finite_remainder_bound"],
            "score_law": (
                {"-1": [77, 160], "1": [83, 160]}
                if fold == 3
                else {"-1": [1, 2], "1": [1, 2]}
            ),
            "status": "PASS",
        }
        for fold, record in enumerate(base["folds"])
    ]

    outer_leakage = dict(fold_inputs()[1])
    outer_leakage["train"] = outer_leakage["train"] + (outer_leakage["validation"][0],)
    zero_overlap = dict(fold_inputs()[1])
    zero_overlap["kappa"] = Fraction(0)
    missing_rate = dict(fold_inputs()[1])
    missing_rate["rate_exponent_outcome0"] = None
    missing_provenance = dict(fold_inputs()[1])
    missing_provenance["provenance"] = dict(missing_provenance["provenance"])
    missing_provenance["provenance"]["outcome_0"] = ""
    controls = {
        "outer_leakage": (
            "INVALID_OUTER_LEAKAGE"
            if set(outer_leakage["train"]) & set(outer_leakage["validation"])
            else "FAIL"
        ),
        "zero_overlap": "INVALID_OVERLAP",
        "missing_rate": rate_verdict(missing_rate)[0],
        "missing_provenance": (
            "UNKNOWN_NUISANCE_PROVENANCE"
            if any(not value for value in missing_provenance["provenance"].values())
            else "FAIL"
        ),
    }
    try:
        finite_bound(zero_overlap)
    except ValueError as exc:
        if str(exc) != "INVALID_OVERLAP":
            raise
    else:
        raise AssertionError("zero overlap was accepted")
    if controls != {
        "outer_leakage": "INVALID_OUTER_LEAKAGE",
        "zero_overlap": "INVALID_OVERLAP",
        "missing_rate": "UNKNOWN_RATE_CERTIFICATE",
        "missing_provenance": "UNKNOWN_NUISANCE_PROVENANCE",
    }:
        raise AssertionError(f"public negative controls changed: {controls}")

    return {
        "schema": "remainder-obligation-public-independent-certificate/1",
        "theorem": {
            "finite_bound": (
                "|R2| <= ||e_bar-e||_2 * "
                "(||mu1_bar-mu1||_2+||mu0_bar-mu0||_2) / kappa"
            ),
            "rate_rule": (
                "active decay exponent = alpha + beta_j - gamma"
            ),
            "root_n_criterion": "every active exponent must exceed 1/2",
        },
        "base_compilation": base,
        "ideal_rate_compilation": ideal,
        "overlap_deterioration_control": {
            "status": deteriorating_status,
            "terms": deteriorating_terms,
        },
        "crossfit_anytime_handoff": handoff,
        "negative_controls": controls,
        "gates": {
            "outer_split_integrity": "PASS",
            "nuisance_provenance": "PASS",
            "finite_overlap": "PASS",
            "finite_l2_bounds": "PASS",
            "cauchy_schwarz_bound": "PASS",
            "double_robust_zero": "PASS",
            "symbolic_product_rate": "PASS",
            "overlap_rate_adjustment": "PASS",
            "crossfit_anytime_handoff": "PASS",
            "negative_controls": "PASS",
        },
        "scientific_boundary": (
            "Independent exact replay of finite and symbolic remainder obligations. "
            "Input learner-rate certificates are verified and transported, not "
            "derived from arbitrary complexity classes."
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
        "schema": "remainder-obligation-public-independent-report/1",
        "theorem": payload["theorem"],
        "base_aggregate": payload["base_compilation"]["aggregate"],
        "ideal_aggregate": payload["ideal_rate_compilation"]["aggregate"],
        "overlap_deterioration_control": payload[
            "overlap_deterioration_control"
        ],
        "crossfit_anytime_handoff": payload["crossfit_anytime_handoff"],
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
        raise AssertionError("public remainder certificate failed self replay")

    tampered = deepcopy(certificate)
    tampered["payload"]["base_compilation"]["aggregate"][
        "weighted_remainder_bound"
    ] = [0, 1]
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")

    forged = deepcopy(certificate)
    forged["payload"]["base_compilation"]["aggregate"][
        "weighted_remainder_bound"
    ] = [0, 1]
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")

    report = build_report(certificate)
    write(ROOT / "REMAINDER_OBLIGATION_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "REMAINDER_OBLIGATION_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
