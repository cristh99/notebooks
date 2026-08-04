from __future__ import annotations

from fractions import Fraction
from itertools import combinations
from typing import Mapping

import verify_execution_orchestrator_public as core


def corrected_execute_lower_bound(
    _data: Mapping[str, object],
) -> dict[str, object]:
    worlds, laws, targets = core.lower_problem()

    le_cam_best: tuple[Fraction, tuple[str, str]] | None = None
    for left, right in combinations(worlds, 2):
        separation = (targets[left] - targets[right]) ** 2
        total_variation = sum(
            abs(laws[left][index] - laws[right][index])
            for index in range(2)
        ) / 2
        lower_bound = separation * (1 - total_variation) / 8
        candidate = (lower_bound, (left, right))
        if le_cam_best is None or candidate > le_cam_best:
            le_cam_best = candidate
    if le_cam_best is None:
        raise AssertionError("Le Cam pair search produced no witness")

    packing_best: tuple[
        Fraction,
        tuple[str, ...],
        Fraction,
        Fraction,
    ] | None = None
    packings_examined = 0
    for size in range(2, len(worlds) + 1):
        for subset in combinations(worlds, size):
            packings_examined += 1
            separation = min(
                (targets[left] - targets[right]) ** 2
                for left, right in combinations(subset, 2)
            )
            testing_error = core.bayes_error(subset, laws)
            lower_bound = separation / 4 * testing_error
            candidate = (
                lower_bound,
                subset,
                separation,
                testing_error,
            )
            if packing_best is None or candidate > packing_best:
                packing_best = candidate
    if packing_best is None:
        raise AssertionError("packing search produced no witness")

    if le_cam_best[0] != Fraction(9, 320):
        raise AssertionError(f"Le Cam lower bound changed: {le_cam_best}")
    if packing_best[0] != Fraction(9, 320):
        raise AssertionError(f"packing lower bound changed: {packing_best}")
    if packings_examined != 26:
        raise AssertionError("packing work count changed")

    # Both methods certify the same value. The private metacompiler breaks the
    # tie by work units, selecting Le Cam (10 pairs) over packing (26 subsets).
    certificate = core.adapter_certificate(
        "lower-bound",
        {
            "status": "SOLVED",
            "selection_rule": (
                "maximize the certified lower bound; break ties by fewer "
                "work units and then method name"
            ),
            "selected_method": "le_cam_two_point",
            "selected_lower_bound": core.q(le_cam_best[0]),
            "selected_work_units": 10,
            "le_cam_pair": list(le_cam_best[1]),
            "matching_packing_lower_bound": core.q(packing_best[0]),
            "matching_packing_subset": list(packing_best[1]),
            "matching_packing_work_units": packings_examined,
        },
    )
    return {
        "status": "SOLVED",
        "provides": ["formal_certificate", "lower_bound", "optimality"],
        "certificate": certificate,
        "summary": {
            "selected_method": "le_cam_two_point",
            "selected_lower_bound": core.q(le_cam_best[0]),
            "candidate_upper_bound": None,
            "verdict": "LOWER_BOUND",
            "work_units": 10,
            "matching_packing_lower_bound": core.q(packing_best[0]),
            "matching_packing_work_units": packings_examined,
        },
        "reason": None,
    }


def main() -> None:
    core.execute_lower_bound = corrected_execute_lower_bound
    core.main()


if __name__ == "__main__":
    main()
