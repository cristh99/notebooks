from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from logic_power_v10 import build_certificate, verify_certificate

from .capital_allocation import (
    make_exact_capital_allocation_problem,
    make_impossible_capital_allocation_problem,
)
from .domain_cases import all_domain_cases


LOGIC_POWER_V10_HEAD = "ba10d0edc7eb20d499d0481fda2537e782b6efb2"
FINANCE_POWER_SCHEMA = "finance-power-v1/report/2"


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _compile_case(
    name: str,
    exact_problem: object,
    impossible_problem: object,
) -> dict[str, object]:
    exact = build_certificate(exact_problem, f"{name}-exact")
    impossible = build_certificate(impossible_problem, f"{name}-impossible")

    exact_errors = verify_certificate(exact)
    impossible_errors = verify_certificate(impossible)
    if exact_errors or impossible_errors:
        raise RuntimeError(
            "certificate verification failed: "
            f"domain={name}; exact={exact_errors}; "
            f"impossible={impossible_errors}"
        )

    exact_policy = exact["payload"]["analysis"]["policy"]
    impossible_policy = impossible["payload"]["analysis"]["policy"]
    if not exact_policy["exact"]:
        raise RuntimeError(f"exact case did not compile: {name}")
    if impossible_policy["exact"]:
        raise RuntimeError(f"negative control was not impossible: {name}")

    return {
        "exact": exact,
        "impossible": impossible,
    }


def build_report() -> dict[str, Any]:
    domains = {
        "capital_allocation": (
            make_exact_capital_allocation_problem(),
            make_impossible_capital_allocation_problem(),
        ),
        **all_domain_cases(),
    }
    cases = {
        name: _compile_case(name, *domains[name])
        for name in sorted(domains)
    }

    payload: dict[str, Any] = {
        "schema": FINANCE_POWER_SCHEMA,
        "logic_power_v10_head": LOGIC_POWER_V10_HEAD,
        "domains": cases,
    }
    return {
        "payload": payload,
        "sha256": hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the deterministic Finance Power v1 evidence report."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/finance_power_v1.json"),
    )
    args = parser.parse_args()

    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(report["sha256"])


if __name__ == "__main__":
    main()
