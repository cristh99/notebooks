from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ps6 import Graph, exhaustive_search_coloring, iset_bfs_3_coloring
from ps6_helpers import (
    generate_line_of_ring_subgraphs,
    generate_random_linked_cluster,
    validate_graph_coloring,
)


def _worker(queue, algorithm: str, graph_type: str, params: dict, seed: int):
    try:
        random.seed(seed)
        np.random.seed(seed)
        if graph_type == "line_of_rings":
            graph = generate_line_of_ring_subgraphs(
                Graph,
                params["number_of_rings"],
                params["nodes_per_ring"],
            )
            guaranteed_3_colorable = True
        elif graph_type == "random_clusters":
            graph = generate_random_linked_cluster(
                Graph,
                params["cluster_size"],
                params["cluster_count"],
                params["p"],
            )
            # Each cluster is an independent color class. q <= 3 guarantees a
            # 3-coloring; q=4 is intentionally included by the assignment but
            # does not guarantee one.
            guaranteed_3_colorable = params["cluster_count"] <= 3
        else:
            raise ValueError(graph_type)

        started = time.perf_counter()
        if algorithm == "exhaustive":
            coloring = exhaustive_search_coloring(graph, 3)
        elif algorithm == "iset_bfs":
            coloring = iset_bfs_3_coloring(graph)
        else:
            raise ValueError(algorithm)
        elapsed = time.perf_counter() - started

        if coloring is None:
            status = (
                "FAIL_MISSING_COLORING"
                if guaranteed_3_colorable
                else "PASS_NO_COLORING_RETURNED"
            )
            valid = None
        else:
            valid = validate_graph_coloring(graph, coloring)
            status = "PASS" if valid else "FAIL_INVALID_COLORING"

        queue.put(
            {
                "status": status,
                "elapsed_seconds": elapsed,
                "n": graph.N,
                "m": sum(len(neighbors) for neighbors in graph.edges) // 2,
                "valid": valid,
                "guaranteed_3_colorable": guaranteed_3_colorable,
            }
        )
    except BaseException as exc:  # preserve experiment failure as evidence
        queue.put(
            {
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )


def run_case(
    algorithm: str,
    graph_type: str,
    params: dict,
    seed: int,
    timeout_seconds: float,
) -> dict:
    ctx = mp.get_context("fork")
    queue = ctx.Queue()
    process = ctx.Process(
        target=_worker,
        args=(queue, algorithm, graph_type, params, seed),
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2)
        result = {"status": "TIMEOUT"}
    elif queue.empty():
        result = {
            "status": "ERROR",
            "error_type": "NoPayload",
            "error": f"worker exitcode={process.exitcode}",
        }
    else:
        result = queue.get()

    return {
        "algorithm": algorithm,
        "graph_type": graph_type,
        "params": params,
        "seed": seed,
        "timeout_seconds": timeout_seconds,
        **result,
    }


def _expected_n(graph_type: str, params: dict) -> int:
    if graph_type == "line_of_rings":
        return params["number_of_rings"] * params["nodes_per_ring"]
    return params["cluster_size"] * params["cluster_count"]


def summarize(rows: list[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["graph_type"], row["algorithm"])].append(row)

    summary = {}
    accepted_statuses = {"PASS", "PASS_NO_COLORING_RETURNED"}
    for (graph_type, algorithm), items in sorted(groups.items()):
        completed = [item for item in items if item["status"] in accepted_statuses]
        timed_out = [item for item in items if item["status"] == "TIMEOUT"]
        failures = [
            item
            for item in items
            if item["status"] not in accepted_statuses | {"TIMEOUT"}
        ]
        summary[f"{graph_type}:{algorithm}"] = {
            "cases": len(items),
            "completed": len(completed),
            "timeouts": len(timed_out),
            "failures": len(failures),
            "no_coloring_returned_on_q4": sum(
                item["status"] == "PASS_NO_COLORING_RETURNED"
                for item in items
            ),
            "largest_n_completed": max(
                (_expected_n(item["graph_type"], item["params"]) for item in completed),
                default=None,
            ),
            "smallest_n_timed_out": min(
                (_expected_n(item["graph_type"], item["params"]) for item in timed_out),
                default=None,
            ),
            "note": (
                "Thresholds are empirical on one runner and need not be monotone "
                "because graph structure changes with parameters. q=4 random "
                "clusters are not guaranteed 3-colorable; returning None there is "
                "recorded, not treated as a functional failure."
            ),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=0.25)
    args = parser.parse_args()

    rows = []
    algorithms = ("exhaustive", "iset_bfs")

    ring_cases = [
        {"number_of_rings": count, "nodes_per_ring": size}
        for size in (3, 4, 5)
        for count in (1, 2, 3, 5, 8, 13, 21, 34, 55)
    ]
    cluster_cases = [
        {
            "cluster_size": size,
            "cluster_count": count,
            "p": probability,
        }
        for probability in (0.25, 0.5, 0.75)
        for count in (2, 3, 4)
        for size in (2, 3, 4, 5, 6, 8, 10, 12, 16)
    ]

    for algorithm in algorithms:
        for index, params in enumerate(ring_cases):
            rows.append(
                run_case(
                    algorithm,
                    "line_of_rings",
                    params,
                    120000 + index,
                    args.timeout,
                )
            )
        for index, params in enumerate(cluster_cases):
            rows.append(
                run_case(
                    algorithm,
                    "random_clusters",
                    params,
                    130000 + index,
                    args.timeout,
                )
            )

    report = {
        "schema": "university-cs1200-ps6/benchmark/2",
        "status": "PASS_BOUNDED_EXPERIMENT_COMPLETED",
        "timeout_seconds_per_case": args.timeout,
        "cpu_count": os.cpu_count(),
        "rows": rows,
        "summary": summarize(rows),
        "guardrails": {
            "timing_is_runner_specific": True,
            "timeouts_removed_from_denominator": 0,
            "q4_noncolorability_not_misclassified": True,
            "course_complete": False,
        },
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
