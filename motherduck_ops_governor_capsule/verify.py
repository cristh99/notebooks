from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import candidate  # noqa: E402
import oracle  # noqa: E402


Decision = tuple[str, str]
Baseline = Callable[[Mapping[str, Any]], Decision]


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_fixtures() -> dict[str, Any]:
    return json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))


def normalize_case(case_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    case = dict(payload)
    case["case_id"] = case_id
    return case


def candidate_decision(case: Mapping[str, Any]) -> Decision:
    packet = candidate.evaluate_case(case)
    return str(packet["recommendation"]), str(packet["terminal"])


def has_lease(case: Mapping[str, Any]) -> bool:
    return any(bool(case.get(key, False)) for key in oracle.LEASE_KEYS)


def baseline_perform_all(case: Mapping[str, Any]) -> Decision:
    return "KEEP_ACTIVE", "PASS"


def baseline_disable_all(case: Mapping[str, Any]) -> Decision:
    if bool(case.get("scheduled", False)):
        return "RETIRE_SCHEDULE", "PASS"
    return "NO_CHANGE", "PASS"


def baseline_status_only(case: Mapping[str, Any]) -> Decision:
    if has_lease(case):
        return "KEEP_ACTIVE", "PASS"
    return "NO_CHANGE", "PASS"


def baseline_cheapest_first(case: Mapping[str, Any]) -> Decision:
    if bool(case.get("scheduled", False)):
        return "BACKOFF", "PASS"
    return "NO_CHANGE", "PASS"


def baseline_ignore_leases(case: Mapping[str, Any]) -> Decision:
    stripped = dict(case)
    for key in oracle.LEASE_KEYS:
        stripped[key] = False
    return candidate_decision(stripped)


BASELINES: dict[str, Baseline] = {
    "perform_all": baseline_perform_all,
    "disable_all": baseline_disable_all,
    "status_only": baseline_status_only,
    "cheapest_first": baseline_cheapest_first,
    "ignore_leases": baseline_ignore_leases,
}


def frozen_fixture_check() -> dict[str, Any]:
    fixture_bundle = load_fixtures()
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for item in fixture_bundle["cases"]:
        case_id = str(item["case_id"])
        case = normalize_case(case_id, item["input"])
        expected = item["expected"]
        packet = candidate.evaluate_case(case)
        observed = (packet["recommendation"], packet["terminal"])
        oracle_observed = oracle.decide(case)
        target = (expected["recommendation"], expected["terminal"])
        digest_ok = expected.get("digest") in (None, packet["digest"])
        passed = observed == target and oracle_observed == target and digest_ok
        row = {
            "case_id": case_id,
            "expected": list(target),
            "candidate": list(observed),
            "oracle": list(oracle_observed),
            "digest": packet["digest"],
            "digest_checked": "digest" in expected,
            "passed": passed,
        }
        rows.append(row)
        if not passed:
            failures.append(row)

        reversed_case = dict(reversed(list(case.items())))
        if candidate.evaluate_case(reversed_case) != packet:
            failures.append(
                {
                    "case_id": case_id,
                    "failure": "semantic replay changed packet",
                }
            )

    invalid_input_rejected = False
    try:
        candidate.evaluate_case(
            normalize_case(
                "invalid-count",
                {
                    "authorized": True,
                    "reversible": True,
                    "receipt_preserved": True,
                    "identical_noop_count": "three",
                },
            )
        )
    except TypeError:
        invalid_input_rejected = True

    if not invalid_input_rejected:
        failures.append({"case_id": "invalid-count", "failure": "not rejected"})

    return {
        "fixture_count": len(rows),
        "fixture_passed": sum(1 for row in rows if row["passed"]),
        "invalid_input_rejected": invalid_input_rejected,
        "failures": failures,
        "rows": rows,
    }


def exhaustive_cases():
    authority = list(itertools.product((False, True), repeat=3))
    lease_modes = (
        {},
        {"run_active": True},
        {"external_job_active": True},
    )
    failure_counts = (0, 2, 3)
    terminal_modes = (
        {},
        {"external_terminal": True, "stable_observations": 1},
        {"external_terminal": True, "stable_observations": 2},
    )
    successors = ("", "flight-v6")
    purposes = ("durable incremental integration", "audit once")
    scheduled_values = (False, True)
    noop_counts = (0, 3, 12)
    timing_modes = (
        {"interval_seconds": 0, "p95_runtime_seconds": 0},
        {"interval_seconds": 120, "p95_runtime_seconds": 20},
        {"interval_seconds": 900, "p95_runtime_seconds": 400},
    )
    status_questions = (False, True)
    material_values = (False, True)

    index = 0
    for (
        authority_values,
        lease_values,
        failure_count,
        terminal_values,
        successor,
        purpose,
        scheduled,
        noop_count,
        timing_values,
        repeated_status_questions,
        material_delta,
    ) in itertools.product(
        authority,
        lease_modes,
        failure_counts,
        terminal_modes,
        successors,
        purposes,
        scheduled_values,
        noop_counts,
        timing_modes,
        status_questions,
        material_values,
    ):
        index += 1
        authorized, reversible, receipt_preserved = authority_values
        case: dict[str, Any] = {
            "case_id": f"exhaustive-{index:06d}",
            "authorized": authorized,
            "reversible": reversible,
            "receipt_preserved": receipt_preserved,
            "same_failure_count": failure_count,
            "superseded_by": successor,
            "purpose": purpose,
            "scheduled": scheduled,
            "identical_noop_count": noop_count,
            "repeated_status_questions": repeated_status_questions,
            "material_delta": material_delta,
            **lease_values,
            **terminal_values,
            **timing_values,
        }
        yield case


def classify_baseline_failure(
    case: Mapping[str, Any], oracle_result: Decision, baseline_result: Decision
) -> str | None:
    if oracle_result == baseline_result:
        return None
    if oracle_result[1] == "REJECTED" and baseline_result[1] != "REJECTED":
        return "unsafe_accept"
    if oracle_result[0] == "KEEP_ACTIVE" and baseline_result[0] != "KEEP_ACTIVE":
        return "lease_violation"
    if oracle_result[1] == "UNKNOWN" and baseline_result[1] == "PASS":
        return "unsupported_action"
    return "wrong_terminal"


def exhaustive_check() -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    terminal_counts: dict[str, int] = {}
    recommendation_counts: dict[str, int] = {}
    baseline_stats = {
        name: {
            "matches": 0,
            "mismatches": 0,
            "unsafe_accept": 0,
            "lease_violation": 0,
            "unsupported_action": 0,
            "wrong_terminal": 0,
        }
        for name in BASELINES
    }

    total = 0
    for case in exhaustive_cases():
        total += 1
        expected = oracle.decide(case)
        observed = candidate_decision(case)
        terminal_counts[expected[1]] = terminal_counts.get(expected[1], 0) + 1
        recommendation_counts[expected[0]] = (
            recommendation_counts.get(expected[0], 0) + 1
        )
        if observed != expected and len(mismatches) < 20:
            mismatches.append(
                {
                    "case_id": case["case_id"],
                    "candidate": list(observed),
                    "oracle": list(expected),
                    "case": case,
                }
            )

        for name, baseline in BASELINES.items():
            result = baseline(case)
            category = classify_baseline_failure(case, expected, result)
            if category is None:
                baseline_stats[name]["matches"] += 1
            else:
                baseline_stats[name]["mismatches"] += 1
                baseline_stats[name][category] += 1

    return {
        "cases": total,
        "candidate_oracle_mismatches": len(mismatches),
        "mismatch_examples": mismatches,
        "terminal_counts": dict(sorted(terminal_counts.items())),
        "recommendation_counts": dict(sorted(recommendation_counts.items())),
        "baselines": baseline_stats,
    }


def main() -> int:
    frozen = frozen_fixture_check()
    exhaustive = exhaustive_check()
    report = {
        "schema": "motherduck-ops-governor-public-capsule/v1",
        "claim_boundary": (
            "Finite declared grammar only; no production authority, hidden "
            "out-of-sample claim, or lifecycle promotion."
        ),
        "network_calls": 0,
        "external_writes": 0,
        "external_spend_usd": 0,
        "source_hashes": {
            "candidate_py": sha256_file(ROOT / "candidate.py"),
            "oracle_py": sha256_file(ROOT / "oracle.py"),
            "fixtures_json": sha256_file(ROOT / "fixtures.json"),
        },
        "frozen": frozen,
        "exhaustive": exhaustive,
    }
    report["report_digest"] = hashlib.sha256(canonical_bytes(report)).hexdigest()

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    report_path = artifacts / "report.json"
    report_path.write_bytes(canonical_bytes(report))
    sums = [
        f"{sha256_file(report_path)}  report.json",
        f"{sha256_file(ROOT / 'candidate.py')}  ../candidate.py",
        f"{sha256_file(ROOT / 'oracle.py')}  ../oracle.py",
        f"{sha256_file(ROOT / 'fixtures.json')}  ../fixtures.json",
    ]
    (artifacts / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")

    summary = {
        "fixtures": f"{frozen['fixture_passed']}/{frozen['fixture_count']}",
        "exhaustive_cases": exhaustive["cases"],
        "candidate_oracle_mismatches": exhaustive[
            "candidate_oracle_mismatches"
        ],
        "report_digest": report["report_digest"],
        "network_calls": 0,
        "external_spend_usd": 0,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    success = (
        not frozen["failures"]
        and frozen["invalid_input_rejected"]
        and exhaustive["candidate_oracle_mismatches"] == 0
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
