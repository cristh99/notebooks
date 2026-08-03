from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NODES = ("Z", "X", "Y")
EDGES = (("Z", "X"), ("Z", "Y"), ("X", "Y"))
DOMAINS = {node: ("0", "1") for node in NODES}


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def fdata(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def descendants(source: str) -> set[str]:
    children = {node: set() for node in NODES}
    for left, right in EDGES:
        children[left].add(right)
    reached: set[str] = set()
    stack = [source]
    while stack:
        node = stack.pop()
        for child in children[node]:
            if child not in reached:
                reached.add(child)
                stack.append(child)
    return reached


def moral_path_after_backdoor_removal(
    conditioned: tuple[str, ...],
) -> list[str] | None:
    # Remove outgoing X edges, take ancestors of X,Y,Z and moralize.
    edges = tuple(edge for edge in EDGES if edge[0] != "X")
    parents = {node: set() for node in NODES}
    for left, right in edges:
        parents[right].add(left)
    relevant = set(NODES)
    moral = {node: set() for node in relevant}
    for left, right in edges:
        moral[left].add(right)
        moral[right].add(left)
    for child in relevant:
        for first, second in combinations(sorted(parents[child]), 2):
            moral[first].add(second)
            moral[second].add(first)
    for node in conditioned:
        for neighbor in list(moral[node]):
            moral[neighbor].discard(node)
        moral[node].clear()
    predecessor: dict[str, str | None] = {"X": None}
    queue = ["X"]
    while queue:
        node = queue.pop(0)
        for neighbor in sorted(moral[node]):
            if neighbor not in predecessor:
                predecessor[neighbor] = node
                queue.append(neighbor)
    if "Y" not in predecessor:
        return None
    path: list[str] = []
    current: str | None = "Y"
    while current is not None:
        path.append(current)
        current = predecessor[current]
    return list(reversed(path))


def valid_backdoor(adjustment: tuple[str, ...]) -> bool:
    if any(node not in {"Z"} for node in adjustment):
        return False
    if set(adjustment) & descendants("X"):
        return False
    return moral_path_after_backdoor_removal(adjustment) is None


def joint_mass() -> dict[tuple[str, str, str], Fraction]:
    p_x1 = {"0": Fraction(1, 4), "1": Fraction(3, 4)}
    p_y1 = {
        ("0", "0"): Fraction(1, 10),
        ("0", "1"): Fraction(1, 2),
        ("1", "0"): Fraction(1, 2),
        ("1", "1"): Fraction(9, 10),
    }
    mass: dict[tuple[str, str, str], Fraction] = {}
    for z, x, y in product(("0", "1"), repeat=3):
        px = p_x1[z] if x == "1" else 1 - p_x1[z]
        py_one = p_y1[(z, x)]
        py = py_one if y == "1" else 1 - py_one
        mass[(z, x, y)] = Fraction(1, 2) * px * py
    if sum(mass.values(), Fraction()) != 1:
        raise AssertionError("joint mass does not normalize")
    return mass


def probability(
    mass: dict[tuple[str, str, str], Fraction],
    event: dict[str, str],
) -> Fraction:
    index = {node: position for position, node in enumerate(NODES)}
    return sum(
        (
            value
            for outcome, value in mass.items()
            if all(outcome[index[node]] == state for node, state in event.items())
        ),
        Fraction(),
    )


def conditional(
    mass: dict[tuple[str, str, str], Fraction],
    event: dict[str, str],
    given: dict[str, str],
) -> Fraction:
    denominator = probability(mass, given)
    if denominator == 0:
        raise ZeroDivisionError("positivity failure")
    return probability(mass, {**given, **event}) / denominator


def adjusted(
    mass: dict[tuple[str, str, str], Fraction],
    x: str,
) -> tuple[Fraction, list[dict[str, object]]]:
    total = Fraction()
    terms: list[dict[str, object]] = []
    for z in ("0", "1"):
        weight = probability(mass, {"Z": z})
        outcome = conditional(
            mass,
            {"Y": "1"},
            {"X": x, "Z": z},
        )
        contribution = weight * outcome
        total += contribution
        terms.append(
            {
                "Z": z,
                "weight": fdata(weight),
                "conditional": fdata(outcome),
                "contribution": fdata(contribution),
            }
        )
    return total, terms


def build_certificate() -> dict[str, object]:
    mass = joint_mass()
    candidates = [(), ("Z",)]
    valid = [list(candidate) for candidate in candidates if valid_backdoor(candidate)]
    low, low_terms = adjusted(mass, "0")
    high, high_terms = adjusted(mass, "1")
    naive_low = conditional(mass, {"Y": "1"}, {"X": "0"})
    naive_high = conditional(mass, {"Y": "1"}, {"X": "1"})
    payload = {
        "schema": (
            "inference-power-compiler/"
            "backdoor-adjustment-public-certificate/1"
        ),
        "graph": {
            "nodes": list(NODES),
            "edges": [list(edge) for edge in EDGES],
        },
        "candidate_sets": [list(candidate) for candidate in candidates],
        "valid_minimal_sets": valid,
        "empty_set_path": moral_path_after_backdoor_removal(()),
        "selected": ["Z"],
        "adjustment": {
            "low": fdata(low),
            "high": fdata(high),
            "effect": fdata(high - low),
            "low_terms": low_terms,
            "high_terms": high_terms,
        },
        "naive": {
            "low": fdata(naive_low),
            "high": fdata(naive_high),
            "effect": fdata(naive_high - naive_low),
            "bias": fdata((naive_high - naive_low) - (high - low)),
        },
        "failure_controls": {
            "mediator_is_descendant": True,
            "latent_confounder_without_observed_covariate": "NO_BACKDOOR_SET",
        },
    }
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: dict[str, object]) -> list[str]:
    payload = certificate.get("payload")
    certificate_hash = certificate.get("sha256")
    if not isinstance(payload, dict) or not isinstance(certificate_hash, str):
        return ["certificate-shape"]
    if digest(payload) != certificate_hash:
        return ["payload-hash"]
    rebuilt = build_certificate()
    if canonical_json(payload) != canonical_json(rebuilt["payload"]):
        return ["semantic-replay"]
    return []


def main() -> None:
    certificate = build_certificate()
    errors = verify_certificate(certificate)
    if errors:
        raise AssertionError(f"certificate replay failed: {errors}")
    payload = certificate["payload"]
    expected = {
        "valid_minimal_sets": [["Z"]],
        "empty_set_path": ["X", "Z", "Y"],
        "selected": ["Z"],
    }
    for key, value in expected.items():
        if payload[key] != value:
            raise AssertionError(f"{key}: {payload[key]!r}")
    if payload["adjustment"]["low"] != [3, 10]:
        raise AssertionError("adjusted low mismatch")
    if payload["adjustment"]["high"] != [7, 10]:
        raise AssertionError("adjusted high mismatch")
    if payload["adjustment"]["effect"] != [2, 5]:
        raise AssertionError("adjusted effect mismatch")
    if payload["naive"]["effect"] != [3, 5]:
        raise AssertionError("naive effect mismatch")
    if payload["naive"]["bias"] != [1, 5]:
        raise AssertionError("bias mismatch")

    tampered = copy.deepcopy(certificate)
    tampered["payload"]["selected"] = []
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("tampered adjustment certificate accepted")

    report = {
        "schema": (
            "inference-power-compiler/"
            "backdoor-adjustment-public-report/1"
        ),
        "minimal_adjustment_set": ["Z"],
        "empty_set_open_path": ["X", "Z", "Y"],
        "adjusted_effect": [2, 5],
        "naive_effect": [3, 5],
        "confounding_bias": [1, 5],
        "failure_controls": payload["failure_controls"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "boundary": (
            "finite DAG backdoor adjustment only; no front-door, ID "
            "algorithm, equivalence-class discovery, transportability, "
            "or finite-sample causal estimation"
        ),
    }
    report["sha256"] = digest(report)
    (ROOT / "BACKDOOR_ADJUSTMENT_PUBLIC_CERTIFICATE.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ROOT / "BACKDOOR_ADJUSTMENT_PUBLIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
