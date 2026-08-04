from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path.cwd()
CODE = ROOT / "data_science_god_level" / "time_series_transfer"
DATA = ROOT / "public-data"
LOGS = ROOT / "public-logs"
DATA.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)

EXPECTED = {
    "forecaster.py": "1bec64d84784ab81a8b8da13a800b2ea679ec59e87fd542af95a7a2e70ad3562",
    "benchmark.py": "b9ea871c52a72594019058e6834ba4557591fb80bfe45a4bae98a2dc226fe3d5",
    "test_forecaster.py": "fd7970a6d181d7cbfd83bb01f965c277e32954c4d584e9bfc8e80e63d7d723e9",
    "logic_plan.py": "5bcfced722f7e624194529dddfd765b9479e8d7b608e385dd414d96cda41c313",
}


def digest(path: str | Path) -> str | None:
    target = Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None


def audit_and_test() -> dict[str, object]:
    actual = {name: digest(CODE / name) for name in EXPECTED}
    assert actual == EXPECTED
    tree = ast.parse((CODE / "forecaster.py").read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: list[str] = []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imports.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    assert not (imports - {"__future__", "dataclasses", "typing", "numpy", "scipy", "sklearn", "statsmodels"})
    assert not (set(calls) & {"open", "eval", "exec", "compile", "__import__", "system", "popen", "run", "urlopen", "request", "read_csv", "read_json"})
    assert not (names & {"Path", "dataset_name", "filename", "requests", "socket", "subprocess", "pandas", "test_values"})

    sys.path.insert(0, str(CODE.resolve()))
    from forecaster import forecast_series
    assert list(inspect.signature(forecast_series).parameters) == ["values", "horizon", "seasonal_periods", "interval_level"]

    suite = unittest.defaultTestLoader.discover(str(CODE), pattern="test_forecaster.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    assert result.wasSuccessful()

    receipt: dict[str, object] = {
        "schema": "data-science-god-level/time-series-static-audit/3",
        "capsule_sha256": "390627f78a876fbc73c1937631dcfaa7af4997f43decdebec992eccf9bef457e",
        "hashes": actual,
        "candidate_future_access": False,
        "candidate_dataset_identifier_access": False,
        "candidate_filesystem_network_process_access": False,
        "official_suite_accessed": False,
        "prior_invalid_run_id": 30876298533,
        "prior_invalid_run_accessed_public_data": False,
        "prior_public_fail_run_id": 30876563848,
        "prior_public_fail_official_suite_accessed": False,
        "calibration_change": "finite_sample_absolute_residual_conformal_without_duplicate_inflation",
    }
    (LOGS / "static-audit.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def download_public() -> tuple[dict[str, object], dict[str, object]]:
    ref = "080b5340366b8df25e048f4cfd11ca99e3806e97"
    base = f"https://raw.githubusercontent.com/unit8co/darts/{ref}/datasets"
    specs = {
        "p01": {"source": "AirPassengers.csv", "time_column": "Month", "value_column": "#Passengers", "seasonal_periods": [12], "horizon": 18},
        "p02": {"source": "ausbeer.csv", "time_column": "date", "value_column": "Y", "seasonal_periods": [4], "horizon": 12},
        "p03": {"source": "monthly-milk.csv", "time_column": "Month", "value_column": "Pounds per cow", "seasonal_periods": [12], "horizon": 18},
        "p04": {"source": "monthly-sunspots.csv", "time_column": "Month", "value_column": "Sunspots", "seasonal_periods": [132], "horizon": 24, "max_history": 1800},
        "p05": {"source": "temps.csv", "time_column": "Date", "value_column": "Daily minimum temperatures", "seasonal_periods": [7, 365], "horizon": 30, "max_history": 3650},
        "p06": {"source": "us_gasoline.csv", "time_column": "Week", "value_column": "Gasoline", "seasonal_periods": [52], "horizon": 26, "max_history": 1800},
    }
    files: list[dict[str, object]] = []
    datasets: list[dict[str, object]] = []
    for role in sorted(specs):
        spec = specs[role]
        path = DATA / f"{role}.csv"
        urllib.request.urlretrieve(f"{base}/{spec['source']}", path)
        files.append({"role": role, "source_file": spec["source"], "bytes": path.stat().st_size, "sha256": digest(path)})
        datasets.append({"role": role, "path": str(path.resolve()), **{key: value for key, value in spec.items() if key != "source"}})
    data_manifest: dict[str, object] = {
        "schema": "data-science-god-level/time-series-public-data/2",
        "source_repository": "unit8co/darts",
        "source_commit": ref,
        "public_files": files,
        "official_suite_accessed": False,
    }
    benchmark_manifest: dict[str, object] = {
        "schema": "data-science-god-level/time-series-manifest/1",
        "suite": "public-development",
        "interval_level": 0.90,
        "datasets": datasets,
        "candidate_future_access": False,
        "official_suite_accessed": False,
    }
    (LOGS / "data-manifest.json").write_text(json.dumps(data_manifest, indent=2, sort_keys=True) + "\n")
    (LOGS / "benchmark-manifest.json").write_text(json.dumps(benchmark_manifest, indent=2, sort_keys=True) + "\n")
    return data_manifest, benchmark_manifest


def evaluate(manifest: dict[str, object]) -> dict[str, object]:
    sys.path.insert(0, str(CODE.resolve()))
    import benchmark
    report = benchmark.run(manifest)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (LOGS / "public-report.json").write_text(payload)
    print(payload)
    return report


def adjudicate(report: dict[str, object] | None) -> dict[str, object]:
    thresholds = {
        "dataset_count": 6,
        "candidate_mean_mase_max": 1.20,
        "candidate_mean_smape_max": 25.0,
        "candidate_mean_owa_max": 1.00,
        "mean_advantage_vs_best_min": -0.05,
        "wins_vs_best_min": 3,
        "worst_advantage_vs_best_min": -0.35,
        "candidate_mean_coverage_min": 0.70,
        "candidate_mean_normalized_width_max": 8.0,
    }
    if report:
        summary = report["summary"]
        checks = {
            "dataset_count": summary["dataset_count"] == thresholds["dataset_count"],
            "finite_all": bool(summary["finite_all"]),
            "candidate_mean_mase": summary["candidate_mean_mase"] <= thresholds["candidate_mean_mase_max"],
            "candidate_mean_smape": summary["candidate_mean_smape"] <= thresholds["candidate_mean_smape_max"],
            "candidate_mean_owa": summary["candidate_mean_owa"] <= thresholds["candidate_mean_owa_max"],
            "mean_advantage_vs_best": summary["mean_advantage_vs_best"] >= thresholds["mean_advantage_vs_best_min"],
            "wins_vs_best": summary["wins_vs_best"] >= thresholds["wins_vs_best_min"],
            "worst_advantage_vs_best": summary["worst_advantage_vs_best"] >= thresholds["worst_advantage_vs_best_min"],
            "candidate_mean_coverage": summary["candidate_mean_coverage"] >= thresholds["candidate_mean_coverage_min"],
            "candidate_mean_normalized_width": summary["candidate_mean_normalized_width"] <= thresholds["candidate_mean_normalized_width_max"],
        }
        verdict = "PASS" if all(checks.values()) else "FAIL"
    else:
        summary = None
        checks = {"report_exists": False}
        verdict = "INVALID_RUN"
    receipt = {
        "schema": "data-science-god-level/time-series-public-freeze/3",
        "verdict": verdict,
        "thresholds": thresholds,
        "checks": checks,
        "summary": summary,
        "candidate_future_access": False,
        "official_suite_accessed": False,
        "post_hoc_retuning_permitted_after_official_evaluation": False,
        "prior_invalid_run_id": 30876298533,
        "prior_invalid_run_accessed_public_data": False,
        "prior_public_fail_run_id": 30876563848,
        "prior_public_fail_artifact_id": 8879739154,
        "prior_public_fail_artifact_sha256": "36c67a2faadb8680bfc9db8b3fc58359c746b7062666b2c51c0c974716173696",
        "prior_public_fail_official_suite_accessed": False,
        "calibration_change": "finite_sample_absolute_residual_conformal_without_duplicate_inflation",
        "hashes": {
            "capsule_sha256": "390627f78a876fbc73c1937631dcfaa7af4997f43decdebec992eccf9bef457e",
            "forecaster_sha256": EXPECTED["forecaster.py"],
            "benchmark_sha256": EXPECTED["benchmark.py"],
            "logic_plan_receipt_sha256": digest(CODE / "logic-plan-receipt.json"),
            "static_audit_sha256": digest(LOGS / "static-audit.json"),
            "data_manifest_sha256": digest(LOGS / "data-manifest.json"),
            "report_sha256": digest(LOGS / "public-report.json"),
        },
    }
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    (LOGS / "public-freeze-receipt.json").write_text(payload)
    (LOGS / "public-freeze-receipt.sha256").write_text(hashlib.sha256(payload.encode()).hexdigest() + "  public-freeze-receipt.json\n")
    print(payload)
    return receipt


def main() -> None:
    audit_and_test()
    _, manifest = download_public()
    report = evaluate(manifest)
    adjudicate(report)


if __name__ == "__main__":
    main()
