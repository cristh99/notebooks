from __future__ import annotations

import copy
from fractions import Fraction
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parent
Expr = tuple


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def one() -> Expr:
    return ("one",)


def prob(variable: str, given: tuple[str, ...]) -> Expr:
    return ("p", variable, given)


def mul(*items: Expr) -> Expr:
    factors: list[Expr] = []
    for item in items:
        if item == one():
            continue
        if item[0] == "mul":
            factors.extend(item[1])
        else:
            factors.append(item)
    if not factors:
        return one()
    if len(factors) == 1:
        return factors[0]
    return ("mul", tuple(factors))


def summation(variables: Iterable[str], body: Expr) -> Expr:
    variables_tuple = tuple(dict.fromkeys(variables))
    return body if not variables_tuple else ("sum", variables_tuple, body)


def divide(numerator: Expr, denominator: Expr) -> Expr:
    if denominator == one():
        return numerator
    if numerator == denominator:
        return one()
    return ("div", numerator, denominator)


def expr_data(expression: Expr) -> object:
    operation = expression[0]
    if operation == "one":
        return {"op": "const", "value": [1, 1]}
    if operation == "p":
        return {
            "op": "prob",
            "variable": expression[1],
            "given": list(expression[2]),
        }
    if operation == "mul":
        return {
            "op": "product",
            "factors": [expr_data(item) for item in expression[1]],
        }
    if operation == "sum":
        return {
            "op": "sum",
            "variables": list(expression[1]),
            "body": expr_data(expression[2]),
        }
    if operation == "div":
        return {
            "op": "ratio",
            "numerator": expr_data(expression[1]),
            "denominator": expr_data(expression[2]),
        }
    raise ValueError("unknown expression")


def pretty(expression: Expr) -> str:
    operation = expression[0]
    if operation == "one":
        return "1"
    if operation == "p":
        variable, given = expression[1], expression[2]
        return f"P({variable})" if not given else f"P({variable}|{','.join(given)})"
    if operation == "mul":
        return " * ".join(f"({pretty(item)})" for item in expression[1])
    if operation == "sum":
        return f"SUM_[{','.join(expression[1])}]({pretty(expression[2])})"
    if operation == "div":
        return f"({pretty(expression[1])})/({pretty(expression[2])})"
    raise ValueError("unknown expression")


class Graph:
    def __init__(
        self,
        nodes: tuple[str, ...],
        directed: tuple[tuple[str, str], ...],
        bidirected: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.nodes = nodes
        self.directed = directed
        self.bidirected = tuple(
            sorted(
                (left, right) if left < right else (right, left)
                for left, right in bidirected
            )
        )
        position = {node: index for index, node in enumerate(nodes)}
        if any(position[left] >= position[right] for left, right in directed):
            raise ValueError("nodes are not topological")

    def induced(self, chosen: Iterable[str]) -> "Graph":
        selected = frozenset(chosen)
        return Graph(
            tuple(node for node in self.nodes if node in selected),
            tuple(
                edge
                for edge in self.directed
                if edge[0] in selected and edge[1] in selected
            ),
            tuple(
                edge
                for edge in self.bidirected
                if edge[0] in selected and edge[1] in selected
            ),
        )

    def ancestors(self, targets: Iterable[str]) -> frozenset[str]:
        parents = {node: set() for node in self.nodes}
        for parent, child in self.directed:
            parents[child].add(parent)
        reached = set(targets)
        stack = list(reached)
        while stack:
            node = stack.pop()
            for parent in parents[node]:
                if parent not in reached:
                    reached.add(parent)
                    stack.append(parent)
        return frozenset(reached)

    def districts(self) -> tuple[frozenset[str], ...]:
        neighbors = {node: set() for node in self.nodes}
        for left, right in self.bidirected:
            neighbors[left].add(right)
            neighbors[right].add(left)
        unseen = set(self.nodes)
        result: list[frozenset[str]] = []
        while unseen:
            root = min(unseen, key=self.nodes.index)
            unseen.remove(root)
            component = {root}
            stack = [root]
            while stack:
                node = stack.pop()
                for neighbor in neighbors[node]:
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
            result.append(frozenset(component))
        return tuple(result)

    def data(self) -> dict[str, object]:
        return {
            "nodes": list(self.nodes),
            "directed": [list(edge) for edge in self.directed],
            "bidirected": [list(edge) for edge in self.bidirected],
        }


class Kernel:
    def __init__(
        self,
        scope: tuple[str, ...],
        factors: Mapping[str, Expr],
    ) -> None:
        self.scope = scope
        self.factors = dict(factors)

    @classmethod
    def observational(cls, order: tuple[str, ...]) -> "Kernel":
        return cls(
            order,
            {
                node: prob(node, order[:index])
                for index, node in enumerate(order)
            },
        )

    def expression(self) -> Expr:
        return mul(*(self.factors[node] for node in self.scope))

    @classmethod
    def refactor(
        cls,
        expression: Expr,
        scope: tuple[str, ...],
    ) -> "Kernel":
        factors: dict[str, Expr] = {}
        for index, node in enumerate(scope):
            numerator = summation(scope[index + 1 :], expression)
            if index == 0:
                factors[node] = numerator
            else:
                denominator = summation(scope[index:], expression)
                factors[node] = divide(numerator, denominator)
        return cls(scope, factors)


class HedgeError(RuntimeError):
    def __init__(self, forest: tuple[str, ...], subforest: tuple[str, ...]) -> None:
        super().__init__("hedge")
        self.forest = forest
        self.subforest = subforest


def identify_recursive(
    graph: Graph,
    y: frozenset[str],
    x: frozenset[str],
    kernel: Kernel,
) -> Expr:
    vertices = frozenset(graph.nodes)
    if not x:
        return summation(
            (node for node in graph.nodes if node not in y),
            kernel.expression(),
        )
    ancestors = graph.ancestors(y)
    if vertices - ancestors:
        removed = tuple(node for node in graph.nodes if node not in ancestors)
        marginal = summation(removed, kernel.expression())
        ancestor_order = tuple(node for node in graph.nodes if node in ancestors)
        return identify_recursive(
            graph.induced(ancestors),
            y,
            x & ancestors,
            Kernel.refactor(marginal, ancestor_order),
        )
    after_intervention = graph.induced(vertices - x)
    w = (vertices - x) - after_intervention.ancestors(y)
    if w:
        return identify_recursive(graph, y, x | w, kernel)
    districts = after_intervention.districts()
    if len(districts) > 1:
        pieces = tuple(
            identify_recursive(
                graph, district, vertices - district, kernel
            )
            for district in districts
        )
        return summation(
            (
                node
                for node in graph.nodes
                if node not in y | x
            ),
            mul(*pieces),
        )
    district = districts[0]
    full_districts = graph.districts()
    if len(full_districts) == 1:
        raise HedgeError(
            graph.nodes,
            tuple(node for node in graph.nodes if node in district),
        )
    if district in full_districts:
        factor = mul(
            *(
                kernel.factors[node]
                for node in kernel.scope
                if node in district
            )
        )
        return summation(
            (node for node in graph.nodes if node in district - y),
            factor,
        )
    containing = next(
        candidate for candidate in full_districts if district < candidate
    )
    order = tuple(node for node in kernel.scope if node in containing)
    return identify_recursive(
        graph.induced(containing),
        y,
        x & containing,
        Kernel(order, {node: kernel.factors[node] for node in order}),
    )


def identify(graph: Graph, y: tuple[str, ...], x: tuple[str, ...]) -> dict[str, object]:
    try:
        expression = identify_recursive(
            graph,
            frozenset(y),
            frozenset(x),
            Kernel.observational(graph.nodes),
        )
    except HedgeError as hedge:
        return {
            "status": "NOT_IDENTIFIABLE",
            "hedge": {
                "forest": list(hedge.forest),
                "subforest": list(hedge.subforest),
            },
        }
    return {
        "status": "IDENTIFIED",
        "expression": expr_data(expression),
        "pretty": pretty(expression),
        "raw": expression,
    }


def joint_distribution(
    variables: tuple[str, ...],
    factor: callable,
) -> dict[tuple[str, ...], Fraction]:
    mass = {
        outcome: factor(dict(zip(variables, outcome, strict=True)))
        for outcome in product(("0", "1"), repeat=len(variables))
    }
    if sum(mass.values(), Fraction()) != 1:
        raise AssertionError("joint distribution does not normalize")
    return mass


def probability(
    variables: tuple[str, ...],
    mass: Mapping[tuple[str, ...], Fraction],
    event: Mapping[str, str],
) -> Fraction:
    positions = {node: index for index, node in enumerate(variables)}
    return sum(
        (
            value
            for outcome, value in mass.items()
            if all(outcome[positions[node]] == state for node, state in event.items())
        ),
        Fraction(),
    )


def conditional(
    variables: tuple[str, ...],
    mass: Mapping[tuple[str, ...], Fraction],
    event: Mapping[str, str],
    given: Mapping[str, str],
) -> Fraction:
    denominator = probability(variables, mass, given)
    if denominator == 0:
        raise ZeroDivisionError("positivity failure")
    return probability(variables, mass, {**given, **event}) / denominator


def evaluate(
    expression: Expr,
    variables: tuple[str, ...],
    mass: Mapping[tuple[str, ...], Fraction],
    assignment: Mapping[str, str],
) -> Fraction:
    operation = expression[0]
    if operation == "one":
        return Fraction(1)
    if operation == "p":
        variable, given = expression[1], expression[2]
        return conditional(
            variables,
            mass,
            {variable: assignment[variable]},
            {node: assignment[node] for node in given},
        )
    if operation == "mul":
        value = Fraction(1)
        for factor in expression[1]:
            value *= evaluate(factor, variables, mass, assignment)
        return value
    if operation == "sum":
        total = Fraction()
        for values in product(("0", "1"), repeat=len(expression[1])):
            extended = dict(assignment)
            extended.update(zip(expression[1], values, strict=True))
            total += evaluate(expression[2], variables, mass, extended)
        return total
    if operation == "div":
        denominator = evaluate(expression[2], variables, mass, assignment)
        if denominator == 0:
            raise ZeroDivisionError("identified denominator is zero")
        return evaluate(expression[1], variables, mass, assignment) / denominator
    raise ValueError("unknown expression")


def backdoor_mass() -> tuple[tuple[str, ...], dict[tuple[str, ...], Fraction]]:
    variables = ("Z", "X", "Y")
    p_x1 = {"0": Fraction(1, 4), "1": Fraction(3, 4)}
    p_y1 = {
        ("0", "0"): Fraction(1, 10),
        ("0", "1"): Fraction(1, 2),
        ("1", "0"): Fraction(1, 2),
        ("1", "1"): Fraction(9, 10),
    }

    def factor(a: dict[str, str]) -> Fraction:
        px = p_x1[a["Z"]] if a["X"] == "1" else 1 - p_x1[a["Z"]]
        py_one = p_y1[(a["Z"], a["X"])]
        py = py_one if a["Y"] == "1" else 1 - py_one
        return Fraction(1, 2) * px * py

    return variables, joint_distribution(variables, factor)


def frontdoor_mass() -> tuple[tuple[str, ...], dict[tuple[str, ...], Fraction]]:
    variables = ("X", "M", "Y")
    p_m1 = {"0": Fraction(1, 4), "1": Fraction(3, 4)}
    p_y1 = {
        ("0", "0"): Fraction(1, 10),
        ("1", "0"): Fraction(1, 2),
        ("0", "1"): Fraction(1, 2),
        ("1", "1"): Fraction(9, 10),
    }

    def factor(a: dict[str, str]) -> Fraction:
        pm_one = p_m1[a["X"]]
        pm = pm_one if a["M"] == "1" else 1 - pm_one
        py_one = p_y1[(a["X"], a["M"])]
        py = py_one if a["Y"] == "1" else 1 - py_one
        return Fraction(1, 2) * pm * py

    return variables, joint_distribution(variables, factor)


def build_certificate() -> dict[str, object]:
    simple_graph = Graph(("X", "Y"), (("X", "Y"),))
    backdoor_graph = Graph(
        ("Z", "X", "Y"),
        (("Z", "X"), ("Z", "Y"), ("X", "Y")),
    )
    frontdoor_graph = Graph(
        ("X", "M", "Y"),
        (("X", "M"), ("M", "Y")),
        (("X", "Y"),),
    )
    bow_graph = Graph(
        ("X", "Y"),
        (("X", "Y"),),
        (("X", "Y"),),
    )
    simple = identify(simple_graph, ("Y",), ("X",))
    backdoor = identify(backdoor_graph, ("Y",), ("X",))
    frontdoor = identify(frontdoor_graph, ("Y",), ("X",))
    bow = identify(bow_graph, ("Y",), ("X",))

    back_variables, back_mass = backdoor_mass()
    front_variables, front_mass = frontdoor_mass()
    back_raw = backdoor.pop("raw")
    front_raw = frontdoor.pop("raw")
    simple.pop("raw")
    back_low = evaluate(
        back_raw, back_variables, back_mass, {"X": "0", "Y": "1"}
    )
    back_high = evaluate(
        back_raw, back_variables, back_mass, {"X": "1", "Y": "1"}
    )
    front_low = evaluate(
        front_raw, front_variables, front_mass, {"X": "0", "Y": "1"}
    )
    front_high = evaluate(
        front_raw, front_variables, front_mass, {"X": "1", "Y": "1"}
    )
    payload = {
        "schema": "inference-power-compiler/admg-id-public-certificate/1",
        "cases": {
            "simple": simple,
            "backdoor": {
                **backdoor,
                "do_x0_y1": [back_low.numerator, back_low.denominator],
                "do_x1_y1": [back_high.numerator, back_high.denominator],
            },
            "frontdoor": {
                **frontdoor,
                "do_x0_y1": [front_low.numerator, front_low.denominator],
                "do_x1_y1": [front_high.numerator, front_high.denominator],
            },
            "bow_arc": bow,
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
    if canonical(payload) != canonical(rebuilt["payload"]):
        return ["semantic-replay"]
    return []


def main() -> None:
    certificate = build_certificate()
    errors = verify_certificate(certificate)
    if errors:
        raise AssertionError(f"certificate replay failed: {errors}")
    cases = certificate["payload"]["cases"]
    if cases["simple"]["pretty"] != "P(Y|X)":
        raise AssertionError("simple ID formula mismatch")
    if cases["backdoor"]["do_x0_y1"] != [3, 10] or cases["backdoor"]["do_x1_y1"] != [7, 10]:
        raise AssertionError("backdoor semantics mismatch")
    if cases["frontdoor"]["do_x0_y1"] != [2, 5] or cases["frontdoor"]["do_x1_y1"] != [3, 5]:
        raise AssertionError("frontdoor semantics mismatch")
    if cases["bow_arc"]["status"] != "NOT_IDENTIFIABLE":
        raise AssertionError("bow arc should fail ID")
    if cases["bow_arc"]["hedge"] != {
        "forest": ["X", "Y"],
        "subforest": ["Y"],
    }:
        raise AssertionError("bow hedge mismatch")

    tampered = copy.deepcopy(certificate)
    tampered["payload"]["cases"]["frontdoor"]["status"] = "NOT_IDENTIFIABLE"
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("tampered ID certificate accepted")

    report = {
        "schema": "inference-power-compiler/admg-id-public-report/1",
        "simple": {
            "expression": cases["simple"]["pretty"],
        },
        "backdoor": {
            "expression": cases["backdoor"]["pretty"],
            "do_x0_y1": [3, 10],
            "do_x1_y1": [7, 10],
            "effect": [2, 5],
        },
        "frontdoor": {
            "expression": cases["frontdoor"]["pretty"],
            "do_x0_y1": [2, 5],
            "do_x1_y1": [3, 5],
            "effect": [1, 5],
        },
        "bow_arc": {
            "status": "NOT_IDENTIFIABLE",
            "hedge": cases["bow_arc"]["hedge"],
            "twin_scm_witness": {
                "observational": "P(X=Y=0)=P(X=Y=1)=1/2",
                "direct_effect": [1, 1],
                "pure_confounding_effect": [0, 1],
            },
        },
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "boundary": (
            "ADMG ID algorithm for unconditional interventional distributions; "
            "no transportability, conditional ID, path-specific effects, "
            "selection bias, cyclic graphs or finite-sample estimation"
        ),
    }
    report["sha256"] = digest(report)
    (ROOT / "ADMG_ID_PUBLIC_CERTIFICATE.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ROOT / "ADMG_ID_PUBLIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
