from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def law_signature(values: Iterable[Fraction]) -> str:
    return "|".join(f"{value.numerator}/{value.denominator}" for value in values)


def enumerate_models() -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for treatment in product((0, 1), repeat=2):
        for outcome in product((0, 1), repeat=4):
            name = "A" + "".join(map(str, treatment)) + "_Y" + "".join(map(str, outcome))

            def y(action: int, latent: int) -> int:
                return outcome[2 * action + latent]

            observational = [Fraction(0) for _ in range(4)]
            do0 = [Fraction(0), Fraction(0)]
            do1 = [Fraction(0), Fraction(0)]
            joint = [Fraction(0) for _ in range(4)]
            for latent in (0, 1):
                action = treatment[latent]
                observed_outcome = y(action, latent)
                observational[2 * action + observed_outcome] += Fraction(1, 2)
                do0[y(0, latent)] += Fraction(1, 2)
                do1[y(1, latent)] += Fraction(1, 2)
                joint[2 * y(0, latent) + y(1, latent)] += Fraction(1, 2)
            ace = do1[1] - do0[1]
            models.append(
                {
                    "name": name,
                    "observational": tuple(observational),
                    "do0": tuple(do0),
                    "do1": tuple(do1),
                    "joint": tuple(joint),
                    "pns": joint[1],
                    "ace": ace,
                    "monotone": all(y(1, latent) >= y(0, latent) for latent in (0, 1)),
                }
            )
    return models


def partition(
    models: Iterable[dict[str, object]], fields: tuple[str, ...]
) -> dict[tuple[str, ...], list[dict[str, object]]]:
    groups: dict[tuple[str, ...], list[dict[str, object]]] = {}
    for model in models:
        key = tuple(law_signature(model[field]) for field in fields)
        groups.setdefault(key, []).append(model)
    return dict(sorted(groups.items()))


def target_values(group: Iterable[dict[str, object]]) -> tuple[Fraction, ...]:
    return tuple(sorted({model["pns"] for model in group}))


def width(group: Iterable[dict[str, object]]) -> Fraction:
    values = target_values(group)
    if not values:
        raise ValueError("group must be nonempty")
    return values[-1] - values[0]


def frontier(
    models: list[dict[str, object]], fields: tuple[str, ...]
) -> dict[str, object]:
    groups = partition(models, fields)
    expected = Fraction(0)
    worst = Fraction(0)
    point = 0
    for group in groups.values():
        group_width = width(group)
        expected += Fraction(len(group), len(models)) * group_width
        worst = max(worst, group_width)
        if group_width == 0:
            point += 1
    return {
        "evidence": list(fields),
        "signature_classes": len(groups),
        "point_identified_classes": point,
        "ambiguous_classes": len(groups) - point,
        "expected_width": q(expected),
        "worst_width": q(worst),
    }


def experiment_width(
    belief: list[dict[str, object]], field: str
) -> tuple[Fraction, Fraction]:
    groups = partition(belief, (field,))
    expected = sum(
        (
            Fraction(len(group), len(belief)) * width(group)
            for group in groups.values()
        ),
        Fraction(0),
    )
    worst = max((width(group) for group in groups.values()), default=Fraction(0))
    return worst, expected


def adaptive_after_observation(models: list[dict[str, object]]) -> dict[str, object]:
    observation_groups = partition(models, ("observational",))
    expected = Fraction(0)
    selected_strata = {"do0": 0, "do1": 0}
    selected_worlds = {"do0": 0, "do1": 0}
    strata: list[dict[str, object]] = []
    for observation, belief in observation_groups.items():
        candidates = []
        for field in ("do0", "do1"):
            worst, conditional_expected = experiment_width(belief, field)
            candidates.append((worst, conditional_expected, field))
        selected = min(candidates)
        expected += Fraction(len(belief), len(models)) * selected[1]
        selected_strata[selected[2]] += 1
        selected_worlds[selected[2]] += len(belief)
        strata.append(
            {
                "observational_signature": observation[0],
                "worlds": len(belief),
                "identified_values": [q(value) for value in target_values(belief)],
                "selected": selected[2],
                "selected_worst_width": q(selected[0]),
                "selected_expected_width": q(selected[1]),
                "candidates": [
                    {
                        "experiment": field,
                        "worst_width": q(worst),
                        "expected_width": q(conditional_expected),
                    }
                    for worst, conditional_expected, field in candidates
                ],
            }
        )
    return {
        "expected_width": q(expected),
        "selected_strata": selected_strata,
        "selected_worlds": selected_worlds,
        "strata": strata,
    }


def find_obstruction(models: list[dict[str, object]]) -> dict[str, object]:
    groups = partition(models, ("observational", "do0", "do1"))
    for evidence, group in groups.items():
        values = target_values(group)
        if len(values) <= 1:
            continue
        ordered = sorted(group, key=lambda model: model["name"])
        for left in ordered:
            for right in ordered:
                if left["name"] >= right["name"] or left["pns"] == right["pns"]:
                    continue
                return {
                    "available_evidence": ["observational", "do0", "do1"],
                    "evidence_signature": list(evidence),
                    "left": left["name"],
                    "right": right["name"],
                    "left_pns": q(left["pns"]),
                    "right_pns": q(right["pns"]),
                    "left_joint_Y0_Y1": [q(value) for value in left["joint"]],
                    "right_joint_Y0_Y1": [q(value) for value in right["joint"]],
                    "identified_values": [q(value) for value in values],
                }
    raise AssertionError("counterfactual obstruction was not found")


def build_payload() -> dict[str, object]:
    models = enumerate_models()
    monotone = [model for model in models if model["monotone"]]
    histogram: dict[str, int] = {}
    for model in models:
        value = model["pns"]
        key = f"{value.numerator}/{value.denominator}"
        histogram[key] = histogram.get(key, 0) + 1

    observation = frontier(models, ("observational",))
    fixed_do0 = frontier(models, ("observational", "do0"))
    fixed_do1 = frontier(models, ("observational", "do1"))
    both = frontier(models, ("observational", "do0", "do1"))
    joint = frontier(models, ("joint",))
    adaptive = adaptive_after_observation(models)
    obstruction = find_obstruction(models)
    monotone_both = frontier(monotone, ("do0", "do1"))

    assert len(models) == 64
    assert len(monotone) == 36
    assert histogram == {"0/1": 36, "1/2": 24, "1/1": 4}
    assert observation == {
        "evidence": ["observational"],
        "signature_classes": 10,
        "point_identified_classes": 3,
        "ambiguous_classes": 7,
        "expected_width": [1, 2],
        "worst_width": [1, 1],
    }
    assert fixed_do0["expected_width"] == [9, 32]
    assert fixed_do1["expected_width"] == [9, 32]
    assert adaptive["expected_width"] == [1, 8]
    assert adaptive["selected_strata"] == {"do0": 7, "do1": 3}
    assert adaptive["selected_worlds"] == {"do0": 44, "do1": 20}
    assert both == {
        "evidence": ["observational", "do0", "do1"],
        "signature_classes": 34,
        "point_identified_classes": 32,
        "ambiguous_classes": 2,
        "expected_width": [1, 16],
        "worst_width": [1, 2],
    }
    assert joint == {
        "evidence": ["joint"],
        "signature_classes": 10,
        "point_identified_classes": 10,
        "ambiguous_classes": 0,
        "expected_width": [0, 1],
        "worst_width": [0, 1],
    }
    assert obstruction["left"] == "A00_Y0101"
    assert obstruction["right"] == "A00_Y0110"
    assert obstruction["left_pns"] == [0, 1]
    assert obstruction["right_pns"] == [1, 2]
    assert monotone_both == {
        "evidence": ["do0", "do1"],
        "signature_classes": 6,
        "point_identified_classes": 6,
        "ambiguous_classes": 0,
        "expected_width": [0, 1],
        "worst_width": [0, 1],
    }
    assert all(model["pns"] == model["ace"] for model in monotone)

    return {
        "schema": "finite-counterfactual-independent-public-verification/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": "26ccc743f42df497102851e259cbbbcecefc8f0d",
            "compiler_blob": "df310d848a2981d17221c170ad3a9d5397d08cbb",
            "runner_blob": "110dc77e63f4bda8c74940289823c1aaedf860f8",
            "lean_blob": "d52bc41dc71c7fcb9721c0fd8f09d3e556c00105",
        },
        "query": {
            "name": "probability_of_necessity_and_sufficiency",
            "event": "P(Y_0=0,Y_1=1)",
        },
        "family": {
            "worlds": len(models),
            "monotone_worlds": len(monotone),
            "target_histogram": dict(sorted(histogram.items())),
        },
        "frontier": {
            "observation_only": observation,
            "observation_plus_fixed_do0": fixed_do0,
            "observation_plus_fixed_do1": fixed_do1,
            "observation_plus_adaptive_one_intervention": adaptive,
            "observation_plus_both_interventions": both,
            "joint_counterfactual_oracle": joint,
        },
        "single_world_nonidentifiability": {
            "status": "PASS",
            "witness": obstruction,
        },
        "monotonicity_closure": {
            "assumption": "Y_1 >= Y_0 unitwise",
            "identity": "P(Y_0=0,Y_1=1)=E[Y_1]-E[Y_0]",
            "remaining_worlds": len(monotone),
            "both_interventions": monotone_both,
            "status": "POINT_IDENTIFIED",
        },
        "models": [
            {
                "name": model["name"],
                "observational": [q(value) for value in model["observational"]],
                "do0": [q(value) for value in model["do0"]],
                "do1": [q(value) for value in model["do1"]],
                "joint_Y0_Y1": [q(value) for value in model["joint"]],
                "pns": q(model["pns"]),
                "ace": q(model["ace"]),
                "monotone": model["monotone"],
            }
            for model in models
        ],
        "gates": {
            "complete_model_enumeration": "PASS",
            "counterfactual_semantics": "PASS",
            "sharp_width_frontier": "PASS",
            "adaptive_design": "PASS",
            "single_world_obstruction": "PASS",
            "monotonicity_closure": "PASS",
            "tamper_rejection": "PASS",
        },
        "scientific_boundary": (
            "Exact finite semantic counterfactual identification over the complete "
            "binary SCM family. This is not the general graphical ID* or IDC* algorithm."
        ),
    }


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    claimed = certificate.get("sha256")
    if not isinstance(payload, dict) or not isinstance(claimed, str):
        return ["certificate-shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    if canonical(payload) != canonical(build_payload()):
        return ["semantic-replay"]
    return []


def main() -> None:
    payload = build_payload()
    certificate = {"payload": payload, "sha256": digest(payload)}
    assert verify_certificate(certificate) == []
    tampered = deepcopy(certificate)
    tampered["payload"]["frontier"]["observation_plus_both_interventions"][
        "expected_width"
    ] = [0, 1]
    assert verify_certificate(tampered) == ["payload-hash"]

    report = {
        "schema": "inference-power-compiler/finite-counterfactual-public-report/1",
        "query": payload["query"],
        "family": payload["family"],
        "frontier": payload["frontier"],
        "single_world_nonidentifiability": payload[
            "single_world_nonidentifiability"
        ],
        "monotonicity_closure": payload["monotonicity_closure"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "scientific_boundary": payload["scientific_boundary"],
    }
    report["sha256"] = digest(report)

    (ROOT / "FINITE_COUNTERFACTUAL_PUBLIC_CERTIFICATE.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ROOT / "FINITE_COUNTERFACTUAL_PUBLIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
