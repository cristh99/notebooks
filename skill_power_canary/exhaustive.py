from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .capsule import (
    governed_claim,
    governed_logic,
    governed_portfolio,
    governed_secrets,
    semantic_sha256,
)

SCHEMA_VERSION = "1.0"


def _evidence(evidence_id: str, stance: str, *, digest: str = "a") -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "url": "https://example.org/source",
        "locator": "page 1",
        "sha256": digest * 64,
        "stance": stance,
        "observed_at": "2026-08-05T00:00:00Z",
    }


def _claim_checks() -> tuple[int, list[dict[str, Any]]]:
    mismatches: list[dict[str, Any]] = []
    count = 0

    def check(case_id: str, payload: Mapping[str, Any], expected: str) -> None:
        nonlocal count
        count += 1
        actual = governed_claim(payload)
        if actual != expected:
            mismatches.append(
                {"domain": "claims", "id": case_id, "expected": expected, "actual": actual}
            )

    check("negative-trigger", {"task_kind": "creative", "evidence": []}, "NO_TRIGGER")
    check("empty", {"task_kind": "research", "evidence": []}, "UNKNOWN")

    stances = ("supports", "contradicts", "context")
    for mask in range(1, 1 << len(stances)):
        present = [stance for index, stance in enumerate(stances) if mask & (1 << index)]
        evidence = [
            _evidence(f"e{index}", stance, digest=chr(ord("a") + index))
            for index, stance in enumerate(present)
        ]
        has_support = "supports" in present
        has_contradiction = "contradicts" in present
        resolution_values = (False, True) if has_support and has_contradiction else (False,)
        for resolved in resolution_values:
            payload: dict[str, Any] = {"task_kind": "research", "evidence": evidence}
            if resolved:
                payload["resolution"] = "The evidence applies to distinct declared scopes."
                payload["resolution_evidence_ids"] = [item["evidence_id"] for item in evidence]
            if has_support and has_contradiction:
                expected = "PASS" if resolved else "INCONSISTENT"
            elif has_support:
                expected = "PASS"
            elif has_contradiction:
                expected = "REJECTED"
            else:
                expected = "UNKNOWN"
            check(f"stances-{mask}-resolved-{resolved}", payload, expected)

    invalid_hash = _evidence("bad-hash", "supports")
    invalid_hash["sha256"] = "invalid"
    check("invalid-hash", {"task_kind": "research", "evidence": [invalid_hash]}, "FAIL")

    duplicate = [_evidence("duplicate", "supports"), _evidence("duplicate", "context", digest="b")]
    check("duplicate-id", {"task_kind": "research", "evidence": duplicate}, "FAIL")

    missing_locator = _evidence("missing-locator", "supports")
    missing_locator["locator"] = ""
    check("missing-locator", {"task_kind": "research", "evidence": [missing_locator]}, "FAIL")

    return count, mismatches


def _logic_checks() -> tuple[int, list[dict[str, Any]]]:
    mismatches: list[dict[str, Any]] = []
    count = 0
    states = list(
        itertools.product(
            (0, 1, 2),
            (False, True),
            (False, True),
            (False, True),
            (0, 1),
        )
    )

    for conflict in (False, True):
        hypotheses = [
            {"id": "h0", "decision": "NO"},
            {"id": "h1", "decision": "YES" if conflict else "NO"},
        ]
        for budget in (0, 1, 2):
            for left_state in states:
                for right_state in states:
                    experiments = []
                    for experiment_id, state in (("e0", left_state), ("e1", right_state)):
                        cost, safe, authorized, separates, risk = state
                        experiments.append(
                            {
                                "id": experiment_id,
                                "cost": cost,
                                "safe": safe,
                                "authorized": authorized,
                                "risk": risk,
                                "observations": {
                                    "h0": "left",
                                    "h1": "right" if separates else "left",
                                },
                            }
                        )
                    payload = {
                        "task_kind": "decision",
                        "hypotheses": hypotheses,
                        "experiments": experiments,
                        "budget": budget,
                    }
                    actual, actual_cost, _ = governed_logic(payload)
                    if not conflict:
                        expected, expected_cost = "NO_ACTION", 0
                    else:
                        eligible = [
                            experiment
                            for experiment in experiments
                            if experiment["cost"] <= budget
                            and experiment["safe"]
                            and experiment["authorized"]
                            and experiment["observations"]["h0"]
                            != experiment["observations"]["h1"]
                        ]
                        if not eligible:
                            expected, expected_cost = "IMPOSSIBLE", 0
                        else:
                            selected = min(
                                eligible,
                                key=lambda item: (item["cost"], item["risk"], item["id"]),
                            )
                            expected = f"SELECT:{selected['id']}"
                            expected_cost = int(selected["cost"])
                    count += 1
                    if actual != expected or actual_cost != expected_cost:
                        mismatches.append(
                            {
                                "domain": "logic",
                                "id": f"conflict-{conflict}-budget-{budget}-{left_state}-{right_state}",
                                "expected": [expected, expected_cost],
                                "actual": [actual, actual_cost],
                            }
                        )

    actual, actual_cost, _ = governed_logic(
        {
            "task_kind": "casual",
            "hypotheses": [{"id": "h0", "decision": "NO"}, {"id": "h1", "decision": "YES"}],
            "experiments": [],
            "budget": 0,
        }
    )
    count += 1
    if actual != "NO_TRIGGER" or actual_cost != 0:
        mismatches.append(
            {
                "domain": "logic",
                "id": "negative-trigger",
                "expected": ["NO_TRIGGER", 0],
                "actual": [actual, actual_cost],
            }
        )

    return count, mismatches


def _valid_manifest(
    *,
    trust: str,
    write: bool,
    authorization: bool,
    dry_run: bool,
    kill_switch: bool,
    safe_resource: bool,
    valid_description: bool,
    name: str = "finite-skill",
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "name": name,
        "description": (
            "A sufficiently detailed finite skill description."
            if valid_description
            else "short"
        ),
        "trust_tier": trust,
        "permissions": ["github:write"] if write else ["github:read"],
        "resources": ["resource.py"] if safe_resource else ["../outside.py"],
    }
    if authorization:
        manifest["authorization_mode"] = "per-run"
    if dry_run:
        manifest["default_mode"] = "dry-run"
    if kill_switch:
        manifest["kill_switch"] = True
    return manifest


def _portfolio_checks() -> tuple[int, int, list[dict[str, Any]]]:
    mismatches: list[dict[str, Any]] = []
    count = 0
    maximum_privilege_cases = 0

    for trust, write, authorization, dry_run, kill_switch, safe_resource, valid_description in itertools.product(
        ("T0", "T1", "T2", "T3"),
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        (False, True),
    ):
        manifest = _valid_manifest(
            trust=trust,
            write=write,
            authorization=authorization,
            dry_run=dry_run,
            kill_switch=kill_switch,
            safe_resource=safe_resource,
            valid_description=valid_description,
        )
        actual = governed_portfolio({"operation": "create", "manifests": [manifest]})
        permission_safe = not write or (
            trust in {"T2", "T3"} and authorization and dry_run and kill_switch
        )
        expected = "PASS" if permission_safe and safe_resource and valid_description else "REJECTED"
        count += 1
        if write:
            maximum_privilege_cases += 1
        if actual != expected:
            mismatches.append(
                {
                    "domain": "portfolio",
                    "id": (
                        f"manifest-{trust}-{write}-{authorization}-{dry_run}-"
                        f"{kill_switch}-{safe_resource}-{valid_description}"
                    ),
                    "expected": expected,
                    "actual": actual,
                }
            )

    valid = _valid_manifest(
        trust="T1",
        write=False,
        authorization=False,
        dry_run=False,
        kill_switch=False,
        safe_resource=True,
        valid_description=True,
    )
    states = ("candidate", "draft", "canary", "verified", "deprecated")
    allowed = {
        ("candidate", "draft"),
        ("draft", "canary"),
        ("canary", "verified"),
        ("verified", "deprecated"),
    }
    for current, target in itertools.product(states, states):
        actual = governed_portfolio(
            {
                "operation": "promote",
                "manifests": [valid],
                "current": current,
                "target": target,
            }
        )
        expected = "PASS" if current == target or (current, target) in allowed else "REJECTED"
        count += 1
        if actual != expected:
            mismatches.append(
                {
                    "domain": "portfolio",
                    "id": f"transition-{current}-{target}",
                    "expected": expected,
                    "actual": actual,
                }
            )

    for reason, expected in ((None, "REJECTED"), ("A reproduced critical defect.", "PASS")):
        payload: dict[str, Any] = {
            "operation": "quarantine",
            "manifests": [valid],
            "current": "draft",
            "target": "quarantined",
        }
        if reason is not None:
            payload["manual_reason"] = reason
        actual = governed_portfolio(payload)
        count += 1
        if actual != expected:
            mismatches.append(
                {
                    "domain": "portfolio",
                    "id": f"quarantine-{reason is not None}",
                    "expected": expected,
                    "actual": actual,
                }
            )

    duplicate = dict(valid)
    actual = governed_portfolio({"operation": "create", "manifests": [valid, duplicate]})
    count += 1
    if actual != "REJECTED":
        mismatches.append(
            {"domain": "portfolio", "id": "duplicate", "expected": "REJECTED", "actual": actual}
        )

    actual = governed_portfolio({"operation": "use_existing", "manifests": [valid]})
    count += 1
    if actual != "NO_TRIGGER":
        mismatches.append(
            {
                "domain": "portfolio",
                "id": "negative-trigger",
                "expected": "NO_TRIGGER",
                "actual": actual,
            }
        )

    return count, maximum_privilege_cases, mismatches


def _secret_text(kind: str) -> str:
    if kind == "github":
        return "gh" + "p_" + ("A" * 40)
    if kind == "entropy":
        return "api_" + "key=" + "aB3_9xQp7Lm2Vt8Rk5Nz4Yw6Uc1De0Fg"
    if kind == "benign":
        return "Store the secret in an approved manager; never paste a credential."
    return "ordinary public documentation"


def _secrets_checks() -> tuple[int, int, list[dict[str, Any]]]:
    mismatches: list[dict[str, Any]] = []
    count = 0
    maximum_privilege_cases = 0

    for symlink, path_escape, write, authorization, dry_run, kill_switch, operation, text_kind in itertools.product(
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        ("local_read", "public_read", "external_write", "documentation"),
        ("none", "github", "entropy", "benign"),
    ):
        payload: dict[str, Any] = {
            "symlink": symlink,
            "path_escape": path_escape,
            "permissions": ["github:write"] if write else ["github:read"],
            "operation": operation,
            "text": _secret_text(text_kind),
        }
        if authorization:
            payload["authorization_mode"] = "per-run"
        if dry_run:
            payload["default_mode"] = "dry-run"
        if kill_switch:
            payload["kill_switch"] = True

        actual = governed_secrets(payload)
        if symlink or path_escape:
            expected = "REJECTED"
        elif write and not (authorization and dry_run and kill_switch):
            expected = "REJECTED"
        elif text_kind in {"github", "entropy"}:
            expected = "DETECTED"
        elif operation in {"local_read", "public_read", "external_write"}:
            expected = "ALLOW"
        else:
            expected = "NO_FINDING"

        count += 1
        if write:
            maximum_privilege_cases += 1
        if actual != expected:
            mismatches.append(
                {
                    "domain": "secrets",
                    "id": (
                        f"{symlink}-{path_escape}-{write}-{authorization}-{dry_run}-"
                        f"{kill_switch}-{operation}-{text_kind}"
                    ),
                    "expected": expected,
                    "actual": actual,
                }
            )

    return count, maximum_privilege_cases, mismatches


def run_exhaustive() -> dict[str, Any]:
    claims_count, claims_mismatches = _claim_checks()
    logic_count, logic_mismatches = _logic_checks()
    portfolio_count, portfolio_privilege, portfolio_mismatches = _portfolio_checks()
    secrets_count, secrets_privilege, secrets_mismatches = _secrets_checks()
    mismatches = sorted(
        claims_mismatches + logic_mismatches + portfolio_mismatches + secrets_mismatches,
        key=lambda item: (item["domain"], item["id"]),
    )
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scope": "exhaustive finite grammar extension",
        "external_spend_usd": 0,
        "network_calls": 0,
        "counts": {
            "claims": claims_count,
            "logic": logic_count,
            "portfolio": portfolio_count,
            "secrets": secrets_count,
            "total": claims_count + logic_count + portfolio_count + secrets_count,
            "maximum_privilege": portfolio_privilege + secrets_privilege,
        },
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "outcome": "PASS" if not mismatches else "FAIL",
        "claim_boundary": (
            "This enumeration covers the declared finite grammars only. It is not hidden "
            "real-world out-of-sample evidence, cross-model transfer, or production proof."
        ),
    }
    summary["digest"] = semantic_sha256(summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run_exhaustive()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
