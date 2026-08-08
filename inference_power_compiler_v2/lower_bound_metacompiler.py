from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import comb
from typing import Mapping

from fano_lower_bound import build_fano_certificate, fano_packing_bound
from lower_bound_compiler import (
    FiniteEstimationProblem,
    HypercubeExperiment,
    build_assouad_certificate,
    build_le_cam_certificate,
    canonical_json,
    digest_payload,
    fraction_data,
)
from packing_lower_bound import (
    FiniteClassificationProblem,
    build_packing_certificate,
)


@dataclass(frozen=True)
class MetaBudget:
    maximum_exact_packings: int = 10_000
    maximum_exact_subset_size: int = 8
    fano_log_terms: int = 12

    def __post_init__(self) -> None:
        if self.maximum_exact_packings <= 0:
            raise ValueError("maximum_exact_packings must be positive")
        if self.maximum_exact_subset_size < 2:
            raise ValueError("maximum_exact_subset_size must be at least two")
        if self.fano_log_terms <= 0:
            raise ValueError("fano_log_terms must be positive")

    def to_data(self) -> dict[str, int]:
        return {
            "maximum_exact_packings": self.maximum_exact_packings,
            "maximum_exact_subset_size": self.maximum_exact_subset_size,
            "fano_log_terms": self.fano_log_terms,
        }


@dataclass(frozen=True)
class MethodCandidate:
    method: str
    status: str
    lower_bound: Fraction | None
    work_units: int
    certificate_sha256: str | None
    reason: str | None

    def to_data(self) -> dict[str, object]:
        return {
            "method": self.method,
            "status": self.status,
            "lower_bound": (
                None if self.lower_bound is None else fraction_data(self.lower_bound)
            ),
            "work_units": self.work_units,
            "certificate_sha256": self.certificate_sha256,
            "reason": self.reason,
        }


def packing_count(worlds: int, maximum_subset_size: int) -> int:
    return sum(
        comb(worlds, size)
        for size in range(2, min(worlds, maximum_subset_size) + 1)
    )


def compile_lower_bounds(
    problem: FiniteEstimationProblem,
    case_name: str,
    *,
    budget: MetaBudget,
    hypercube: HypercubeExperiment | None = None,
    candidate_upper_bound: Fraction | None = None,
) -> dict[str, object]:
    methods: list[MethodCandidate] = []
    certificates: dict[str, dict[str, object]] = {}

    le_cam = build_le_cam_certificate(problem, f"{case_name}_le_cam")
    le_cam_lower = Fraction(
        *le_cam["payload"]["result"]["strongest_lower_bound"]
    )
    methods.append(
        MethodCandidate(
            method="le_cam_two_point",
            status="CERTIFIED",
            lower_bound=le_cam_lower,
            work_units=le_cam["payload"]["result"]["pair_count"],
            certificate_sha256=le_cam["sha256"],
            reason=None,
        )
    )
    certificates["le_cam_two_point"] = le_cam

    world_count = len(problem.worlds)
    subset_limit = min(world_count, budget.maximum_exact_subset_size)
    exact_packings = packing_count(world_count, subset_limit)
    if (
        subset_limit == world_count
        and exact_packings <= budget.maximum_exact_packings
    ):
        packing = build_packing_certificate(
            problem,
            f"{case_name}_packing",
            max_subset_size=subset_limit,
            max_packings=budget.maximum_exact_packings,
        )
        packing_lower = Fraction(
            *packing["payload"]["result"]["strongest_lower_bound"]
        )
        methods.append(
            MethodCandidate(
                method="exact_finite_packing",
                status="CERTIFIED",
                lower_bound=packing_lower,
                work_units=packing["payload"]["result"]["packings_examined"],
                certificate_sha256=packing["sha256"],
                reason=None,
            )
        )
        certificates["exact_finite_packing"] = packing
    else:
        reason = (
            f"requires {exact_packings} packings through subset size "
            f"{subset_limit}; full coverage of {world_count} worlds exceeds "
            "the declared exact-enumeration budget"
        )
        methods.append(
            MethodCandidate(
                method="exact_finite_packing",
                status="SKIPPED_RESOURCE",
                lower_bound=None,
                work_units=exact_packings,
                certificate_sha256=None,
                reason=reason,
            )
        )

    if world_count >= 3:
        classification = FiniteClassificationProblem(
            problem.worlds, problem.outcomes, problem.laws
        )
        fano = build_fano_certificate(
            classification,
            f"{case_name}_fano",
            log_terms=budget.fano_log_terms,
        )
        fano_packing = fano_packing_bound(
            problem, log_terms=budget.fano_log_terms
        )
        fano_lower = Fraction(*fano_packing["estimation_lower_bound"])
        methods.append(
            MethodCandidate(
                method="certified_fano",
                status="CERTIFIED",
                lower_bound=fano_lower,
                work_units=world_count * len(problem.outcomes),
                certificate_sha256=fano["sha256"],
                reason=None,
            )
        )
        certificates["certified_fano"] = fano
    else:
        methods.append(
            MethodCandidate(
                method="certified_fano",
                status="NOT_APPLICABLE",
                lower_bound=None,
                work_units=0,
                certificate_sha256=None,
                reason="Fano requires at least three hypotheses",
            )
        )

    if hypercube is not None:
        if (
            set(hypercube.worlds) != set(problem.worlds)
            or set(hypercube.outcomes) != set(problem.outcomes)
        ):
            raise ValueError("hypercube metadata does not match the problem")
        assouad = build_assouad_certificate(
            hypercube, f"{case_name}_assouad"
        )
        assouad_lower = Fraction(
            *assouad["payload"]["result"]["lower_bound"]
        )
        methods.append(
            MethodCandidate(
                method="assouad_hypercube",
                status="CERTIFIED",
                lower_bound=assouad_lower,
                work_units=hypercube.dimension * len(hypercube.outcomes),
                certificate_sha256=assouad["sha256"],
                reason=None,
            )
        )
        certificates["assouad_hypercube"] = assouad
    else:
        methods.append(
            MethodCandidate(
                method="assouad_hypercube",
                status="NOT_APPLICABLE",
                lower_bound=None,
                work_units=0,
                certificate_sha256=None,
                reason="no certified binary-hypercube structure was supplied",
            )
        )

    certified = [
        candidate
        for candidate in methods
        if candidate.status == "CERTIFIED" and candidate.lower_bound is not None
    ]
    if not certified:
        raise RuntimeError("no lower-bound method produced a certificate")
    selected = max(
        certified,
        key=lambda candidate: (
            candidate.lower_bound,
            -candidate.work_units,
            candidate.method,
        ),
    )
    if candidate_upper_bound is not None and candidate_upper_bound < selected.lower_bound:
        raise AssertionError(
            "declared upper bound is below a certified lower bound"
        )
    if candidate_upper_bound is None:
        verdict = "LOWER_BOUND"
    elif candidate_upper_bound == selected.lower_bound:
        verdict = "MATCHED"
    else:
        verdict = "GAP"

    payload = {
        "schema": "inference-power-compiler/lower-bound-metacompiler/1",
        "case": case_name,
        "problem": problem.to_data(),
        "budget": budget.to_data(),
        "methods": [candidate.to_data() for candidate in methods],
        "selected_method": selected.method,
        "selected_lower_bound": fraction_data(selected.lower_bound),
        "selected_work_units": selected.work_units,
        "candidate_upper_bound": (
            None
            if candidate_upper_bound is None
            else fraction_data(candidate_upper_bound)
        ),
        "verdict": verdict,
        "certificates": certificates,
    }
    return {"payload": payload, "sha256": digest_payload(payload)}


def verify_meta_certificate(
    certificate: Mapping[str, object],
    *,
    hypercube: HypercubeExperiment | None = None,
) -> list[str]:
    payload = certificate.get("payload")
    payload_hash = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(payload_hash, str):
        return ["certificate-shape"]
    if digest_payload(payload) != payload_hash:
        return ["payload-hash"]
    try:
        problem_data = payload.get("problem")
        budget_data = payload.get("budget")
        case_name = payload.get("case")
        upper_data = payload.get("candidate_upper_bound")
        if (
            not isinstance(problem_data, Mapping)
            or not isinstance(budget_data, Mapping)
            or not isinstance(case_name, str)
        ):
            raise ValueError("malformed metacompiler payload")
        problem = FiniteEstimationProblem.from_data(problem_data)
        budget = MetaBudget(
            maximum_exact_packings=int(
                budget_data["maximum_exact_packings"]
            ),
            maximum_exact_subset_size=int(
                budget_data["maximum_exact_subset_size"]
            ),
            fano_log_terms=int(budget_data["fano_log_terms"]),
        )
        upper = None if upper_data is None else Fraction(*upper_data)
        rebuilt = compile_lower_bounds(
            problem,
            case_name,
            budget=budget,
            hypercube=hypercube,
            candidate_upper_bound=upper,
        )
    except Exception as exc:
        return [f"rebuild:{type(exc).__name__}"]
    return [] if canonical_json(rebuilt["payload"]) == canonical_json(payload) else ["semantic-replay"]
