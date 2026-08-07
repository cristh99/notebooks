from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--solution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()

    shutil.copy2(args.solution, args.official_dir / "ps8.py")
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
    else:
        status = "PASS_OFFICIAL_EXPERIMENT_GRID_REPLAY"

    report = {
        "schema": "university-cs1200-ps8-glucose/experiment-report/1",
        "status": status,
        "returncode": completed.returncode,
        "official_timeout_seconds_per_algorithm_case": 1,
        "rows": rows,
        "summary": summary,
        "denominator": len(rows),
        "timeouts_retained": sum(row["outcome"] == "timeout" for row in rows),
        "output_sha256": hashlib.sha256(clean.encode()).hexdigest(),
        "elapsed_seconds": elapsed,
        "scope_boundary": (
            "Exact public ps8_experiments.py grid on this GitHub Actions runner; "
            "observed timing boundaries are hardware/interpreter specific."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if status.startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
