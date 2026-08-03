from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREDICTOR = ROOT / "predictor.py"
EXPECTED_SHA256 = "cfe46cccbb7f75e8fd3b3978ac88f7034dfd7e4b6d9b9c5589fb5f85ea14bb90"
ALLOWED_IMPORT_ROOTS = {"__future__", "collections", "itertools", "numpy"}
FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__"}


def validate(dist: object) -> None:
    if not hasattr(dist, "__len__") or len(dist) != 256:
        raise ValueError("distribution length")
    total = 0.0
    for value in dist:
        probability = float(value)
        if not math.isfinite(probability) or probability < -1e-9 or probability > 1.001:
            raise ValueError("invalid probability")
        total += max(0.0, probability)
    if abs(total - 1.0) > 0.01:
        raise ValueError("distribution sum")


def main() -> None:
    digest = hashlib.sha256(PREDICTOR.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"predictor digest mismatch: {digest}")

    tree = ast.parse(PREDICTOR.read_text(encoding="utf-8"))
    imports = set()
    forbidden_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                forbidden_calls.append(node.func.id)
    if not imports <= ALLOWED_IMPORT_ROOTS:
        raise SystemExit(f"forbidden imports: {sorted(imports - ALLOWED_IMPORT_ROOTS)}")
    if forbidden_calls:
        raise SystemExit(f"forbidden calls: {forbidden_calls}")

    spec = importlib.util.spec_from_file_location("candidate_predictor", PREDICTOR)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load predictor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    predictor = module.Predictor()
    predictor.reset()
    state = 0x12345678
    for _ in range(4096):
        dist = predictor.predict()
        validate(dist)
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        predictor.update((state >> 16) & 0xFF)

    negative_control_rejected = False
    try:
        validate([1.0] * 256)
    except ValueError:
        negative_control_rejected = True
    if not negative_control_rejected:
        raise SystemExit("invalid-distribution negative control escaped")

    receipt = {
        "schema": "data-science-god-level/evaluator-integrity/1",
        "predictor_sha256": digest,
        "allowed_imports": sorted(imports),
        "stream_steps": 4096,
        "negative_control_rejected": negative_control_rejected,
        "all_passed": True,
    }
    Path("integrity-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
