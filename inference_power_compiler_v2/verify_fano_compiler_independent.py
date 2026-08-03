from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, getcontext
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json
import os
from pathlib import Path

from fano_compiler import (
    build_fano_certificate,
    make_symmetric_eight_world_problem,
    verify_fano_certificate,
)


ROOT = Path(__file__).resolve().parent
getcontext().prec = 90


def decimal_fraction(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def decimal_information(
    laws: dict[str, tuple[Fraction, ...]], subset: tuple[str, ...]
) -> Decimal:
    size = Decimal(len(subset))
    mixture = [
        sum(
            (decimal_fraction(laws[world][index]) for world in subset),
            Decimal(0),
        )
        / size
        for index in range(8)
    ]
    information = Decimal(0)
    for world in subset:
        for index, probability_fraction in enumerate(laws[world]):
            probability = decimal_fraction(probability_fraction)
            if probability == 0:
                continue
            information += (
                probability
                * (probability / mixture[index]).ln()
                / size
            )
    return information


def independent_best_packing() -> dict[str, object]:
    worlds = tuple(f"h{index}" for index in range(8))
    diagonal = Fraction(1, 4)
    off_diagonal = Fraction(3, 28)
    laws = {
        world: tuple(
            diagonal if world_index == outcome_index else off_diagonal
            for outcome_index in range(8)
        )
        for world_index, world in enumerate(worlds)
    }
    best: tuple[Decimal, int, tuple[str, ...]] | None = None
    examined = 0
    for size in range(2, 9):
        for subset in combinations(worlds, size):
            examined += 1
            information = decimal_information(laws, subset)
            error = Decimal(1) - (
                information + Decimal(2).ln()
            ) / Decimal(size).ln()
            if error < 0:
                error = Decimal(0)
            squared = error / Decimal(2)
            candidate = (squared, size, subset)
            if best is None or candidate[0] > best[0] or (
                candidate[0] == best[0]
                and (
                    candidate[1] > best[1]
                    or (
                        candidate[1] == best[1]
                        and candidate[2] < best[2]
                    )
                )
            ):
                best = candidate
    if best is None:
        raise AssertionError("independent packing search failed")
    return {
        "examined": examined,
        "packing": list(best[2]),
        "packing_size": best[1],
        "squared_lower_bound": str(best[0]),
        "classification_error_lower_bound": str(best[0] * 2),
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    problem = make_symmetric_eight_world_problem()
    certificate = build_fano_certificate(
        problem, "symmetric_eight_world_channel"
    )
    if verify_fano_certificate(certificate):
        raise AssertionError("canonical semantic replay failed")

    result = certificate["payload"]["result"]
    lower = result["lower_bound"]
    upper = result["upper_witness"]
    independent = independent_best_packing()

    if independent["examined"] != 247:
        raise AssertionError("independent subset count changed")
    if independent["packing_size"] != 8:
        raise AssertionError("independent search did not select eight worlds")
    if independent["packing"] != [f"h{index}" for index in range(8)]:
        raise AssertionError("independent packing differs")
    if lower["certified_error_floor_1e12"] != [
        638931438667,
        1_000_000_000_000,
    ]:
        raise AssertionError("certified error floor differs")
    if lower["certified_squared_loss_floor_1e12"] != [
        319465719333,
        1_000_000_000_000,
    ]:
        raise AssertionError("certified squared floor differs")
    if upper["maximum_classification_risk"] != [3, 4]:
        raise AssertionError("MAP classification risk differs")
    if upper["maximum_squared_loss_risk"] != [3, 2]:
        raise AssertionError("MAP squared risk differs")

    actual_error = Decimal(
        independent["classification_error_lower_bound"]
    )
    exact_wolfram_expression = (
        Decimal(5488) / Decimal(27)
    ).ln() / Decimal(4096).ln()
    if abs(actual_error - exact_wolfram_expression) > Decimal("1e-80"):
        raise AssertionError("independent Fano value differs from Wolfram")

    tampered = deepcopy(certificate)
    tampered["payload"]["result"]["lower_bound"][
        "packing_size"
    ] = 7
    if verify_fano_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("tampered certificate was not rejected")

    payload = {
        "schema": "fano-compiler/public-independent-receipt/1",
        "private_repository": "cristh99/my_first_repository",
        "private_pr": 68,
        "private_source_blob": (
            "e9a82e75db96d8dba317962312cd8e8286dd8683"
        ),
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "canonical_certificate_sha256": certificate["sha256"],
        "independent_search": independent,
        "wolfram_exact_expression": "Log[5488/27]/Log[4096]",
        "exact_controls": {
            "row_sum": "1/4 + 7*(3/28) = 1",
            "map_classification_risk": "3/4",
            "map_squared_loss_risk": "3/2",
            "certified_error_floor": "638931438667/10^12",
            "certified_squared_floor": "319465719333/10^12",
        },
        "gates": {
            "canonical_semantic_replay": "PASS",
            "independent_247_subset_search": "PASS",
            "Wolfram_value_agreement": "PASS",
            "tamper_rejection": "PASS",
        },
    }
    receipt = {
        "payload": payload,
        "sha256": sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    }
    output = ROOT / "FANO_PUBLIC_RECEIPT.json"
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
