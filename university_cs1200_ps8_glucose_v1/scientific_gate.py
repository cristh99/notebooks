from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
import random
import time
from pathlib import Path

from pysat.solvers import Glucose3, Minisat22

from ps8_solution import (
    Graph,
    graph_3_coloring_cnf,
    sat_3_coloring,
    solve_three_dimensional_complete_matching,
)


def graph_from_mask(n: int, mask: int) -> Graph:
    graph = Graph(n)
    bit = 0
    for u in range(n):
        for v in range(u + 1, n):
            if mask & (1 << bit):
                graph.add_edge(u, v)
            bit += 1
    return graph


def exact_three_colorable(graph: Graph) -> bool:
    if graph.N == 0:
        return True
    order = sorted(range(graph.N), key=lambda v: len(graph.edges[v]), reverse=True)
    colors = [-1] * graph.N

    def search(index: int) -> bool:
        if index == graph.N:
            return True
        vertex = order[index]
        forbidden = {colors[nbr] for nbr in graph.edges[vertex] if colors[nbr] >= 0}
        for color in range(3):
            if color in forbidden:
                continue
            colors[vertex] = color
            if search(index + 1):
                return True
        colors[vertex] = -1
        return False

    return search(0)


def solve_cnf_two_solvers(clauses: list[list[int]]) -> tuple[bool, bool]:
    glucose = Glucose3(bootstrap_with=clauses)
    minisat = Minisat22(bootstrap_with=clauses)
    try:
        return glucose.solve(), minisat.solve()
    finally:
        glucose.delete()
        minisat.delete()


def graph_case(payload: tuple[int, int]) -> dict:
    n, mask = payload
    graph = graph_from_mask(n, mask)
    expected = exact_three_colorable(graph)
    candidate = graph.clone()
    result = sat_3_coloring(candidate)
    observed = result is not None
    if observed != expected:
        raise AssertionError((n, mask, expected, observed))
    if result is not None and not candidate.is_graph_coloring_valid():
        raise AssertionError("invalid decoded coloring")
    clauses = graph_3_coloring_cnf(graph)
    glucose, minisat = solve_cnf_two_solvers(clauses)
    if glucose != expected or minisat != expected:
        raise AssertionError("solver disagreement")
    return {
        "n": n,
        "mask": mask,
        "edges": sum(len(row) for row in graph.edges) // 2,
        "colorable": expected,
        "clauses": len(clauses),
    }


def random_graph_case(seed: int) -> dict:
    rng = random.Random(seed)
    n = rng.randint(6, 11)
    probability = rng.uniform(0.05, 0.95)
    graph = Graph(n)
    for u in range(n):
        for v in range(u + 1, n):
            if rng.random() < probability:
                graph.add_edge(u, v)
    expected = exact_three_colorable(graph)
    candidate = graph.clone()
    result = sat_3_coloring(candidate)
    observed = result is not None
    if observed != expected:
        raise AssertionError((seed, expected, observed))
    return {
        "seed": seed,
        "n": n,
        "edges": sum(len(row) for row in graph.edges) // 2,
        "colorable": expected,
    }


def brute_three_dimensional_matching(
    v0: tuple[str, ...], edges: tuple[tuple[str, str, str], ...]
):
    for selection in itertools.combinations(edges, len(v0)):
        flattened = [vertex for edge in selection for vertex in edge]
        if len(set(flattened)) != len(flattened):
            continue
        if {edge[0] for edge in selection} == set(v0):
            return selection
    return None


def matching_case(payload: tuple[int, int]) -> dict:
    size, mask = payload
    v0 = tuple(f"a{i}" for i in range(size))
    v1 = tuple(f"b{i}" for i in range(size))
    v2 = tuple(f"c{i}" for i in range(size))
    universe = tuple(itertools.product(v0, v1, v2))
    edges = tuple(edge for index, edge in enumerate(universe) if mask & (1 << index))
    expected = brute_three_dimensional_matching(v0, edges)
    observed = solve_three_dimensional_complete_matching(v0, v1, v2, edges)
    if (expected is None) != (observed is None):
        raise AssertionError((size, mask, expected, observed))
    return {
        "size": size,
        "mask": mask,
        "hyperedges": len(edges),
        "satisfiable": expected is not None,
    }


def random_matching_case(seed: int) -> dict:
    rng = random.Random(seed)
    size = 3
    v0 = tuple(f"a{i}" for i in range(size))
    v1 = tuple(f"b{i}" for i in range(size))
    v2 = tuple(f"c{i}" for i in range(size))
    universe = tuple(itertools.product(v0, v1, v2))
    chosen = tuple(edge for edge in universe if rng.random() < rng.uniform(0.12, 0.5))
    expected = brute_three_dimensional_matching(v0, chosen)
    observed = solve_three_dimensional_complete_matching(v0, v1, v2, chosen)
    if (expected is None) != (observed is None):
        raise AssertionError((seed, expected, observed))
    return {
        "seed": seed,
        "hyperedges": len(chosen),
        "satisfiable": expected is not None,
    }


def parse_dimacs(path: Path) -> Graph:
    n = None
    edges: list[tuple[int, int]] = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("c"):
            continue
        parts = line.split()
        if parts[0] == "p":
            n = int(parts[-2])
        elif parts[0] == "e":
            edges.append((int(parts[1]) - 1, int(parts[2]) - 1))
    if n is None:
        raise ValueError(f"missing DIMACS problem line: {path}")
    graph = Graph(n)
    for u, v in edges:
        if v not in graph.edges[u]:
            graph.add_edge(u, v)
    return graph


def dimacs_case(path: Path) -> dict:
    graph = parse_dimacs(path)
    clauses = graph_3_coloring_cnf(graph)
    started = time.perf_counter()
    glucose, minisat = solve_cnf_two_solvers(clauses)
    elapsed = time.perf_counter() - started
    if glucose != minisat:
        raise AssertionError(f"Glucose/Minisat disagreement on {path.name}")
    candidate = graph.clone()
    decoded = sat_3_coloring(candidate)
    if (decoded is not None) != glucose:
        raise AssertionError(f"decode disagreement on {path.name}")
    if decoded is not None and not candidate.is_graph_coloring_valid():
        raise AssertionError(f"invalid coloring on {path.name}")
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "vertices": graph.N,
        "edges": sum(len(row) for row in graph.edges) // 2,
        "clauses": len(clauses),
        "three_colorable": glucose,
        "solver_parity": True,
        "elapsed_seconds": elapsed,
    }


def run_map(function, payloads, workers: int):
    if workers == 1:
        return [function(payload) for payload in payloads]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(function, payloads))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    exact_graph_payloads = [
        (n, mask)
        for n in range(0, 6)
        for mask in range(1 << (n * (n - 1) // 2))
    ]
    exact_graphs = run_map(graph_case, exact_graph_payloads, args.workers)
    random_graphs = run_map(random_graph_case, range(8000, 9000), args.workers)

    exact_matching_payloads = [(2, mask) for mask in range(1 << 8)]
    exact_matchings = run_map(matching_case, exact_matching_payloads, args.workers)
    random_matchings = run_map(random_matching_case, range(9000, 9500), args.workers)

    k4 = Graph(4)
    for u in range(4):
        for v in range(u + 1, 4):
            k4.add_edge(u, v)
    if sat_3_coloring(k4) is not None:
        raise AssertionError("K4 negative control unexpectedly colorable")

    official_unsat_edges = (
        ("a0", "b1", "c1"),
        ("a1", "b1", "c0"),
        ("a2", "b0", "c2"),
        ("a3", "b3", "c3"),
    )
    if solve_three_dimensional_complete_matching(
        tuple(f"a{i}" for i in range(4)),
        tuple(f"b{i}" for i in range(4)),
        tuple(f"c{i}" for i in range(4)),
        official_unsat_edges,
    ) is not None:
        raise AssertionError("official 3D matching negative control unexpectedly SAT")

    dimacs_files = [
        args.official_dir / "le450_25a.txt",
        args.official_dir / "le450_25d.txt",
        args.official_dir / "le1000_25a.txt",
    ]
    if args.workers == 1:
        dimacs = [dimacs_case(path) for path in dimacs_files]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:
            dimacs = list(pool.map(dimacs_case, dimacs_files))
    dimacs.sort(key=lambda row: row["file"])

    scientific_payload = {
        "exact_graphs": exact_graphs,
        "random_graphs": random_graphs,
        "exact_matchings": exact_matchings,
        "random_matchings": random_matchings,
        "dimacs": [
            {key: value for key, value in row.items() if key != "elapsed_seconds"}
            for row in dimacs
        ],
        "negative_controls": ["K4_3COLOR_UNSAT", "OFFICIAL_3D_MATCHING_UNSAT"],
    }
    digest = hashlib.sha256(
        json.dumps(scientific_payload, sort_keys=True).encode()
    ).hexdigest()
    report = {
        "schema": "university-cs1200-ps8-glucose/scientific-report/1",
        "status": "PASS_REAL_GLUCOSE_AND_DIMACS_GATE",
        "workers": args.workers,
        "exact_graphs": len(exact_graphs),
        "random_graphs": len(random_graphs),
        "exact_3d_matching_instances": len(exact_matchings),
        "random_3d_matching_instances": len(random_matchings),
        "dimacs": dimacs,
        "negative_controls": 2,
        "glucose_minisat_parity": True,
        "scientific_digest": digest,
        "elapsed_seconds": time.perf_counter() - started,
        "scope_boundary": (
            "Real PySAT Glucose3 plus Minisat22 cross-check, official public tests and "
            "three frozen DIMACS graphs; not a private grader or official course grade."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
