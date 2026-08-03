from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .audit import audit_dataset, canonical
from .portfolio_engine import (
    BacktestResult,
    load_market,
    monthly_returns,
    moving_block_bootstrap_ci,
    run_backtest,
    selection_key,
)

SCHEMA = "fin-abs-002/portbench-external-benchmark/1"
BASELINES = (
    "equal_weight",
    "sixty_forty",
    "risk_parity",
    "cov_risk_parity",
    "min_variance",
    "black_litterman",
)
CHALLENGERS = (
    "robust_erc",
    "robust_erc_ntb",
    "robust_survival",
)
VALIDATION_START = "2023-01-01"
VALIDATION_END = "2023-12-31"
TEST_START = "2024-01-01"
TEST_END = "2025-12-31"
STRESS_WINDOWS = {
    "2015_china_shock": ("2015-08-01", "2016-02-29"),
    "2020_covid": ("2020-02-01", "2020-05-31"),
    "2022_crypto": ("2022-05-01", "2022-12-31"),
}
PROFILE_DRAWDOWN_TOLERANCES = {
    "conservative": 0.10,
    "balanced": 0.20,
    "aggressive": 0.35,
}


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def clean_metrics(result: BacktestResult) -> dict[str, Any]:
    return {
        "strategy": result.strategy,
        "start": result.start,
        "end": result.end,
        "pit_violations": result.pit_violations,
        "metrics": result.metrics,
    }


def choose(results: list[BacktestResult]) -> BacktestResult:
    if not results:
        raise ValueError("no strategies to select")
    return max(results, key=selection_key)


def write_result_files(
    output: Path,
    prefix: str,
    result: BacktestResult,
) -> dict[str, str]:
    daily_path = output / f"{prefix}_daily.csv"
    weights_path = output / f"{prefix}_weights.csv"
    result.daily.to_csv(daily_path, index_label="date", float_format="%.17g")
    result.weights.to_csv(weights_path, index_label="date", float_format="%.17g")
    return {
        "daily_file": daily_path.name,
        "daily_sha256": file_sha(daily_path),
        "weights_file": weights_path.name,
        "weights_sha256": file_sha(weights_path),
    }


def benchmark(dataset: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    audit = audit_dataset(dataset)
    if audit["payload"]["status"] != "PASS_DATA_AUDIT":
        raise ValueError("PortBench data audit must pass before performance testing")
    market = load_market(dataset)

    validation_baselines = [
        run_backtest(market, name, VALIDATION_START, VALIDATION_END)
        for name in BASELINES
    ]
    validation_challengers = [
        run_backtest(market, name, VALIDATION_START, VALIDATION_END)
        for name in CHALLENGERS
    ]
    selected_baseline_validation = choose(validation_baselines)
    selected_challenger_validation = choose(validation_challengers)

    test_baseline = run_backtest(
        market,
        selected_baseline_validation.strategy,
        TEST_START,
        TEST_END,
    )
    test_challenger = run_backtest(
        market,
        selected_challenger_validation.strategy,
        TEST_START,
        TEST_END,
    )

    baseline_monthly = monthly_returns(test_baseline.daily)
    challenger_monthly = monthly_returns(test_challenger.daily)
    common_months = baseline_monthly.index.intersection(challenger_monthly.index)
    paired_differences = (
        challenger_monthly.loc[common_months]
        - baseline_monthly.loc[common_months]
    )
    bootstrap = moving_block_bootstrap_ci(paired_differences.tolist())

    stress_results: dict[str, dict[str, Any]] = {}
    for name, (start, end) in STRESS_WINDOWS.items():
        result = run_backtest(
            market,
            selected_challenger_validation.strategy,
            start,
            end,
        )
        loss = float(result.metrics["max_drawdown_loss"] or 0.0)
        stress_results[name] = {
            **clean_metrics(result),
            "profile_pass": {
                profile: loss <= tolerance
                for profile, tolerance in PROFILE_DRAWDOWN_TOLERANCES.items()
            },
        }

    baseline_metrics = test_baseline.metrics
    challenger_metrics = test_challenger.metrics
    python_gates = {
        "data_audit_pass": audit["payload"]["status"] == "PASS_DATA_AUDIT",
        "zero_pit_violations": (
            all(result.pit_violations == 0 for result in validation_baselines)
            and all(result.pit_violations == 0 for result in validation_challengers)
            and test_baseline.pit_violations == 0
            and test_challenger.pit_violations == 0
            and all(
                value["pit_violations"] == 0 for value in stress_results.values()
            )
        ),
        "sealed_selection_from_validation": (
            selected_baseline_validation.start == VALIDATION_START
            and selected_challenger_validation.start == VALIDATION_START
            and test_baseline.start == TEST_START
            and test_challenger.start == TEST_START
        ),
        "challenger_higher_test_sharpe": float(
            challenger_metrics["sharpe"] or -1e9
        )
        > float(baseline_metrics["sharpe"] or -1e9),
        "drawdown_within_100bps": float(
            challenger_metrics["max_drawdown_loss"] or 1e9
        )
        <= float(baseline_metrics["max_drawdown_loss"] or 1e9) + 0.01,
        "expected_shortfall_within_100bps": float(
            challenger_metrics["expected_shortfall_95_loss"] or 1e9
        )
        <= float(baseline_metrics["expected_shortfall_95_loss"] or 1e9) + 0.01,
        "paired_bootstrap_lower_bound_positive": float(
            bootstrap["lower_95"] or -1e9
        )
        > 0.0,
        "all_profile_stress_gates": all(
            all(value["profile_pass"].values())
            for value in stress_results.values()
        ),
    }
    performance_candidate_pass = all(python_gates.values())

    baseline_files = write_result_files(output, "test_baseline", test_baseline)
    challenger_files = write_result_files(output, "test_challenger", test_challenger)
    validation_payload = {
        "baselines": [clean_metrics(result) for result in validation_baselines],
        "challengers": [clean_metrics(result) for result in validation_challengers],
        "selected_baseline": selected_baseline_validation.strategy,
        "selected_challenger": selected_challenger_validation.strategy,
        "selection_rule": (
            "highest net Sharpe; ties by lower drawdown, lower ES, lower turnover, then name"
        ),
    }
    (output / "validation.json").write_text(
        json.dumps(validation_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paired_payload = {
        "months": [str(value) for value in common_months],
        "baseline": [float(value) for value in baseline_monthly.loc[common_months]],
        "challenger": [
            float(value) for value in challenger_monthly.loc[common_months]
        ],
        "difference": [float(value) for value in paired_differences],
        "bootstrap": bootstrap,
    }
    (output / "paired_monthly.json").write_text(
        json.dumps(paired_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "stress.json").write_text(
        json.dumps(stress_results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    payload = {
        "schema": SCHEMA,
        "source": {
            "dataset_sha256": market.dataset_sha256,
            "data_audit_sha256": audit["sha256"],
            "portbench_source_commit": (
                "5e7cce2e1214a5dd026578c8814953f358b5a475"
            ),
        },
        "protocol": {
            "validation": [VALIDATION_START, VALIDATION_END],
            "sealed_test": [TEST_START, TEST_END],
            "baselines": list(BASELINES),
            "challengers": list(CHALLENGERS),
            "transaction_cost_rate": 0.0015,
            "score_delta_if_every_gate_passes": 28,
        },
        "validation": validation_payload,
        "sealed_test": {
            "baseline": clean_metrics(test_baseline),
            "challenger": clean_metrics(test_challenger),
            "paired_monthly": paired_payload,
            "files": {
                "baseline": baseline_files,
                "challenger": challenger_files,
            },
        },
        "stress": stress_results,
        "python_gate_checks": python_gates,
        "performance_candidate_pass": performance_candidate_pass,
        "independent_weight_reimplementation": "PENDING",
        "status": (
            "CANDIDATE_PASS_PENDING_INDEPENDENT_WEIGHT_REPLAY"
            if performance_candidate_pass
            else "FALSIFIED_OR_OPEN_ON_PORTBENCH"
        ),
        "absolute_score": {
            "before": 423,
            "after": 423,
            "delta": 0,
            "boundary": (
                "No absolute points are awarded until an independent implementation "
                "reconstructs portfolio weights and every non-compensable gate passes."
            ),
        },
    }
    payload_canonical = canonical(payload)
    report = {
        "payload": payload,
        "payload_canonical": payload_canonical,
        "sha256": hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest(),
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.input, args.output_dir)
    payload = report["payload"]
    print(
        json.dumps(
            {
                "status": payload["status"],
                "selected_baseline": payload["validation"]["selected_baseline"],
                "selected_challenger": payload["validation"][
                    "selected_challenger"
                ],
                "baseline_test_sharpe": payload["sealed_test"]["baseline"][
                    "metrics"
                ]["sharpe"],
                "challenger_test_sharpe": payload["sealed_test"]["challenger"][
                    "metrics"
                ]["sharpe"],
                "bootstrap_lower_95": payload["sealed_test"]["paired_monthly"][
                    "bootstrap"
                ]["lower_95"],
                "report_sha256": report["sha256"],
                "absolute_score": payload["absolute_score"]["after"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
