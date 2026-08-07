from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ALGORITHMS = {
    "Exhaustive Coloring": "exhaustive",
    "ISET BFS Coloring": "iset_bfs",
    "SAT Coloring": "glucose_sat",
}


def prepare_hard_instances(official_dir: Path) -> dict:
    """Repair an upstream packaging gap without changing the experiment script.

    ps8_experiments.py unconditionally reads ./hard_instances, but the frozen
    public repository omits that directory while publishing three DIMACS hard
    graphs in the same PS8 directory. We serialize those exact frozen graphs in
    the format expected by the public experiment script and retain the repair in
    the report.
    """
    hard_dir = official_dir / "hard_instances"
    hard_dir.mkdir(exist_ok=True)
    for existing in hard_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    sys.path.insert(0, str(official_dir))
    try:
        ps8 = importlib.import_module("ps8")
        helpers = importlib.import_module("ps8_helpers")
        sources = ["le450_25a.txt", "le450_25d.txt", "le1000_25a.txt"]
        rows = []
        for ordinal, name in enumerate(sources, start=1):
            source = official_dir / name
            graph = helpers.load_dimacs_graph(ps8.Graph, source)
            # The upstream script sorts names by an initial integer.
            target = hard_dir / f"{graph.N * 100 + ordinal}_{name}.pickle"
            with target.open("wb") as handle:
                pickle.dump(graph, handle)
            rows.append(
                {
                    "source": name,
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "pickle": target.name,
                    "vertices": graph.N,
                    "edges": sum(len(neighbors) for neighbors in graph.edges) // 2,
                }
            )
        return {
            "upstream_hard_instances_directory_present": False,
            "repair": "SERIALIZE_THREE_FROZEN_DIMACS_GRAPHS",
            "rows": rows,
        }
    finally:
        sys.path.pop(0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--solution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()

    shutil.copy2(args.solution, args.official_dir / "ps8.py")
    packaging_repair = prepare_hard_instances(args.official_dir)
    env = os.environ.copy()
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "MPLBACKEND": "Agg",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "ps8_experiments.py"],
        cwd=args.official_dir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=2700,
    )
    elapsed = time.perf_counter() - started
    clean = ANSI_RE.sub("", completed.stdout)
    args.log.write_text(clean)

    family = "unknown"
    current_case = "unknown"
    rows = []
    for raw in clean.splitlines():
        line = raw.strip()
        if line == "Line of Rings":
            family = "line_of_rings"
        elif line.startswith("Randomized Cluster Connections"):
            family = "random_clusters"
        elif line == "Hard instances":
            family = "hard_instances"
        elif line.startswith("(n =") or line.startswith("n ="):
            current_case = line
        elif line.startswith("Loading file:"):
            current_case = line.split(":", 1)[1].strip()
        elif "Finished constructing/reading a hard instance" in line:
            current_case = line
        else:
            for printed, canonical in ALGORITHMS.items():
                marker = f"{printed}:"
                if marker not in line:
                    continue
                outcome = "timeout" if "Timeout" in line else "finished"
                colorable = None
                if "Found 3-coloring" in line:
                    colorable = True
                elif "No 3-coloring found" in line:
                    colorable = False
                rows.append(
                    {
                        "family": family,
                        "case": current_case,
                        "algorithm": canonical,
                        "outcome": outcome,
                        "three_colorable": colorable,
                    }
                )
                break

    counts = defaultdict(Counter)
    for row in rows:
        counts[row["family"]][f"{row['algorithm']}:{row['outcome']}"] += 1

    summary = {
        family_name: dict(sorted(counter.items()))
        for family_name, counter in sorted(counts.items())
    }
    if completed.returncode != 0:
        status = "FAIL_OFFICIAL_EXPERIMENT_PROCESS"
    elif not rows:
        status = "FAIL_NO_EXPERIMENT_ROWS"
    elif "hard_instances" not in summary:
        status = "FAIL_HARD_INSTANCE_ROWS_MISSING"
    else:
        status = "PASS_OFFICIAL_EXPERIMENT_GRID_REPLAY"

    report = {
        "schema": "university-cs1200-ps8-glucose/experiment-report/1",
        "status": status,
        "returncode": completed.returncode,
        "official_timeout_seconds_per_algorithm_case": 1,
        "packaging_repair": packaging_repair,
        "rows": rows,
        "summary": summary,
        "denominator": len(rows),
        "timeouts_retained": sum(row["outcome"] == "timeout" for row in rows),
        "output_sha256": hashlib.sha256(clean.encode()).hexdigest(),
        "elapsed_seconds": elapsed,
        "scope_boundary": (
            "Exact public ps8_experiments.py grid on this GitHub Actions runner. "
            "The absent hard_instances folder is repaired only by serializing the "
            "three exact frozen DIMACS graphs already published with PS8; observed "
            "timing boundaries are hardware/interpreter specific."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
