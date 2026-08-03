from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXTERNAL = ROOT / "external"
SEEDS = (2024, 20260803, 314159265, 271828182)
REFERENCE_BPB = 3.8


def evaluate(seed: int, predictor_path: Path, label: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"autolab-{label}-{seed}-") as raw:
        temp = Path(raw)
        hidden = temp / "hidden"
        app = temp / "app"
        tests = temp / "tests"
        app.mkdir()
        tests.mkdir()
        shutil.copy2(predictor_path, app / "predictor.py")
        shutil.copy2(EXTERNAL / "predictor_host.py", tests / "predictor_host.py")
        subprocess.run(
            [
                sys.executable,
                str(EXTERNAL / "datagen.py"),
                "--seed",
                str(seed),
                "--output-dir",
                str(hidden),
            ],
            check=True,
        )
        manifest = json.loads((hidden / "manifest.json").read_text(encoding="utf-8"))
        byte_count = sum(item["size"] for item in manifest["sequences"])
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONUNBUFFERED": "1",
            "HIDDEN_DIR": str(hidden),
            "APP_DIR": str(app),
            "TESTS_DIR": str(tests),
        }
        completed = subprocess.run(
            [sys.executable, str(EXTERNAL / "evaluate_hidden.py")],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=900,
        )
        match = re.search(r"overall_bpb=([0-9.]+)", completed.stdout)
        if not match:
            raise RuntimeError(f"missing score: {completed.stdout!r}")
        return {
            "label": label,
            "seed": seed,
            "bytes": byte_count,
            "bpb": float(match.group(1)),
            "stdout": completed.stdout.strip(),
            "family_log": completed.stderr.strip().splitlines(),
        }


def main() -> None:
    candidate = ROOT / "predictor.py"
    baseline = EXTERNAL / "baseline.py"
    rows = []
    for seed in SEEDS:
        candidate_result = evaluate(seed, candidate, "candidate")
        baseline_result = evaluate(seed, baseline, "baseline")
        if candidate_result["bytes"] != baseline_result["bytes"]:
            raise SystemExit("candidate and baseline byte denominators differ")
        if not candidate_result["bpb"] < REFERENCE_BPB:
            raise SystemExit(
                f"seed {seed}: candidate {candidate_result['bpb']} did not beat {REFERENCE_BPB}"
            )
        if not candidate_result["bpb"] < baseline_result["bpb"]:
            raise SystemExit(f"seed {seed}: candidate did not beat paired baseline")
        rows.append(
            {
                "seed": seed,
                "bytes": candidate_result["bytes"],
                "candidate_bpb": candidate_result["bpb"],
                "baseline_bpb": baseline_result["bpb"],
                "improvement_bpb": baseline_result["bpb"] - candidate_result["bpb"],
                "candidate_family_log": candidate_result["family_log"],
                "baseline_family_log": baseline_result["family_log"],
            }
        )
        print(json.dumps(rows[-1], indent=2, sort_keys=True), flush=True)

    total_bytes = sum(row["bytes"] for row in rows)
    weighted_candidate = sum(
        row["candidate_bpb"] * row["bytes"] for row in rows
    ) / total_bytes
    weighted_baseline = sum(
        row["baseline_bpb"] * row["bytes"] for row in rows
    ) / total_bytes
    report = {
        "schema": "data-science-god-level/autolab-adaptive-compression/1",
        "autolab_commit": "7aff5fe71dfbe152fb0b8e8ac8087210b4bc27d5",
        "python": sys.version,
        "numpy": __import__("numpy").__version__,
        "reference_bpb": REFERENCE_BPB,
        "predictor_sha256": "cfe46cccbb7f75e8fd3b3978ac88f7034dfd7e4b6d9b9c5589fb5f85ea14bb90",
        "rows": rows,
        "total_bytes": total_bytes,
        "weighted_candidate_bpb": weighted_candidate,
        "weighted_baseline_bpb": weighted_baseline,
        "weighted_improvement_bpb": weighted_baseline - weighted_candidate,
        "reference_margin_bpb": REFERENCE_BPB - weighted_candidate,
        "all_seeds_beat_reference": all(
            row["candidate_bpb"] < REFERENCE_BPB for row in rows
        ),
    }
    Path("autolab-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
