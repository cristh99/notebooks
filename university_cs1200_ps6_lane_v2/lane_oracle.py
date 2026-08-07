from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import heapq
import json
import random
import time
from itertools import product
from pathlib import Path

from ps6 import (
    Graph,
    bfs_2_coloring,
    get_maximal_isets,
    iset_bfs_3_coloring,
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


def valid_coloring(graph: Graph, coloring, allowed: set[int]) -> bool:
    if coloring is None or len(coloring) != graph.N:
        return False
    if any(color not in allowed for color in coloring):
        return False
    return all(
        coloring[u] != coloring[v]
        for u in range(graph.N)
        for v in graph.edges[u]
    )


def brute_coloring(graph: Graph, colors: int):
    for assignment in product(range(colors), repeat=graph.N):
        if valid_coloring(graph, assignment, set(range(colors))):
            return list(assignment)
    return None


def independent(graph: Graph, vertices: set[int]) -> bool:
    return all(not (graph.edges[u] & vertices) for u in vertices)


def brute_maximal_independent_sets(graph: Graph) -> set[tuple[int, ...]]:
    vertices = set(range(graph.N))
    result: set[tuple[int, ...]] = set()
    for mask in range(1 << graph.N):
        subset = {v for v in range(graph.N) if mask & (1 << v)}
        if not independent(graph, subset):
            continue
        if all(graph.edges[v] & subset for v in vertices - subset):
            result.add(tuple(sorted(subset)))
    return result


def greedy_maximal_independent_set(graph: Graph) -> set[int]:
    chosen: set[int] = set()
    blocked: set[int] = set()
    for vertex in range(graph.N):
        if vertex in blocked:
            continue
        chosen.add(vertex)
        blocked.add(vertex)
        blocked.update(graph.edges[vertex])
    return chosen


def check_graph_case(payload: tuple[int, int]) -> dict:
    n, mask = payload
    graph = graph_from_mask(n, mask)

    expected_2 = brute_coloring(graph, 2)
    expected_3 = brute_coloring(graph, 3)
    actual_2 = bfs_2_coloring(graph.clone())
    actual_3 = iset_bfs_3_coloring(graph.clone())
    assert (actual_2 is not None) == (expected_2 is not None)
    assert (actual_3 is not None) == (expected_3 is not None)
    if actual_2 is not None:
        assert valid_coloring(graph, actual_2, {0, 1})
    if actual_3 is not None:
        assert valid_coloring(graph, actual_3, {0, 1, 2})

    preset_checks = 0
    for subset_mask in range(1 << n):
        preset = {v for v in range(n) if subset_mask & (1 << v)}
        if not independent(graph, preset):
            continue
        residual_vertices = [v for v in range(n) if v not in preset]
        index = {v: i for i, v in enumerate(residual_vertices)}
        residual = Graph(len(residual_vertices))
        for u in residual_vertices:
            for v in graph.edges[u]:
                if v in index and index[u] < index[v]:
                    residual.add_edge(index[u], index[v])
        expected = brute_coloring(residual, 2) is not None
        actual = bfs_2_coloring(graph.clone(), preset)
        assert (actual is not None) == expected
        if actual is not None:
            assert all(actual[v] == 2 for v in preset)
            assert valid_coloring(graph, actual, {0, 1, 2})
        preset_checks += 1

    expected_isets = brute_maximal_independent_sets(graph)
    actual_isets = {
        tuple(sorted(item)) for item in get_maximal_isets(graph)
    }
    assert actual_isets == expected_isets

    greedy = greedy_maximal_independent_set(graph)
    assert independent(graph, greedy)
    assert all(graph.edges[v] & greedy for v in set(range(n)) - greedy)

    return {
        "n": n,
        "mask": mask,
        "two_colorable": expected_2 is not None,
        "three_colorable": expected_3 is not None,
        "preset_checks": preset_checks,
        "maximal_isets": len(expected_isets),
    }


def interval_depth(intervals: list[tuple[int, int]]) -> int:
    events = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    depth = current = 0
    for _, delta in sorted(events):
        current += delta
        depth = max(depth, current)
    return depth


def validate_interval_coloring(
    intervals: list[tuple[int, int]], coloring: list[int]
) -> bool:
    if len(intervals) != len(coloring):
        return False
    for i, (a, b) in enumerate(intervals):
        for j in range(i + 1, len(intervals)):
            c, d = intervals[j]
            if max(a, c) < min(b, d) and coloring[i] == coloring[j]:
                return False
    return True


def interval_coloring_nk(intervals: list[tuple[int, int]]) -> list[int]:
    order = sorted(range(len(intervals)), key=lambda i: intervals[i][0])
    end_by_color: list[int] = []
    colors = [-1] * len(intervals)
    for index in order:
        start, end = intervals[index]
        for color, latest_end in enumerate(end_by_color):
            if latest_end <= start:
                end_by_color[color] = end
                colors[index] = color
                break
        else:
            colors[index] = len(end_by_color)
            end_by_color.append(end)
    return colors


def interval_coloring_heap(intervals: list[tuple[int, int]]) -> list[int]:
    order = sorted(range(len(intervals)), key=lambda i: intervals[i][0])
    active: list[tuple[int, int]] = []
    free_colors: list[int] = []
    next_color = 0
    colors = [-1] * len(intervals)
    for index in order:
        start, end = intervals[index]
        while active and active[0][0] <= start:
            _, color = heapq.heappop(active)
            heapq.heappush(free_colors, color)
        if free_colors:
            color = heapq.heappop(free_colors)
        else:
            color = next_color
            next_color += 1
        colors[index] = color
        heapq.heappush(active, (end, color))
    return colors


def check_interval_case(seed: int) -> dict:
    rng = random.Random(seed)
    n = rng.randint(1, 24)
    endpoints = rng.sample(range(0, 20 * n + 1), 2 * n)
    intervals = []
    for i in range(n):
        a, b = endpoints[2 * i : 2 * i + 2]
        intervals.append((min(a, b), max(a, b)))
    expected = interval_depth(intervals)
    nk = interval_coloring_nk(intervals)
    heap = interval_coloring_heap(intervals)
    assert validate_interval_coloring(intervals, nk)
    assert validate_interval_coloring(intervals, heap)
    assert len(set(nk)) == expected
    assert len(set(heap)) == expected
    return {"seed": seed, "n": n, "depth": expected}


def official_broken_helper(graph: Graph):
    def recurse(R: set[int], P: set[int], X: set[int]):
        if not P and not X:
            yield R.copy()
        pivot_edges = (
            graph.edges[min(P | X, key=lambda v: len(graph.edges[v]))]
            if P | X
            else set()
        )
        for vertex in P.copy() - pivot_edges:
            forbidden = graph.edges[vertex] | {vertex}
            yield from recurse(
                R | {vertex}, P - forbidden, X - forbidden
            )
            P.remove(vertex)
            X.add(vertex)
    return {tuple(sorted(item)) for item in recurse(set(), set(range(graph.N)), set())}


def run(workers: int) -> dict:
    graph_payloads = []
    for n in range(0, 6):
        edge_count = n * (n - 1) // 2
        graph_payloads.extend((n, mask) for mask in range(1 << edge_count))
    interval_seeds = list(range(6000, 9000))

    started = time.perf_counter()
    if workers == 1:
        graph_results = [check_graph_case(item) for item in graph_payloads]
        interval_results = [check_interval_case(seed) for seed in interval_seeds]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            graph_results = list(pool.map(check_graph_case, graph_payloads))
            interval_results = list(pool.map(check_interval_case, interval_seeds))

    # Explicit source-defect control: the official pivot loop omits maximal sets.
    defect_graph = graph_from_mask(5, 431)
    expected_sets = brute_maximal_independent_sets(defect_graph)
    broken_sets = official_broken_helper(defect_graph)
    repaired_sets = {
        tuple(sorted(item)) for item in get_maximal_isets(defect_graph)
    }
    assert broken_sets != expected_sets
    assert repaired_sets == expected_sets

    # Explicit negative controls.
    triangle = Graph(3).add_edge(0, 1).add_edge(1, 2).add_edge(2, 0)
    assert bfs_2_coloring(triangle) is None
    k4 = Graph(4)
    for u in range(4):
        for v in range(u + 1, 4):
            k4.add_edge(u, v)
    assert iset_bfs_3_coloring(k4) is None

    scientific = {
        "graph_results": graph_results,
        "interval_results": interval_results,
        "defect_expected_sets": sorted(expected_sets),
        "defect_broken_sets": sorted(broken_sets),
        "defect_repaired_sets": sorted(repaired_sets),
    }
    return {
        "schema": "university-cs1200-ps6/lane-oracle/1",
        "status": "PASS_PS6_INDEPENDENT_ORACLES",
        "workers": workers,
        "exhaustive_graphs": len(graph_results),
        "precolored_cases": sum(item["preset_checks"] for item in graph_results),
        "maximal_isets_checked": sum(item["maximal_isets"] for item in graph_results),
        "interval_cases": len(interval_results),
        "two_colorable_graphs": sum(item["two_colorable"] for item in graph_results),
        "three_colorable_graphs": sum(item["three_colorable"] for item in graph_results),
        "source_defect_control": "PASS_OFFICIAL_PIVOT_OMITS_MAXIMAL_ISETS",
        "negative_controls": 2,
        "scientific_digest": hashlib.sha256(
            json.dumps(scientific, sort_keys=True).encode()
        ).hexdigest(),
        "elapsed_seconds": time.perf_counter() - started,
        "scope_boundary": (
            "Mandatory technical mechanisms and independent oracles only; "
            "reflection, survey, private grader and official course completion excluded."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.workers)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
