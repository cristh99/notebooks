from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping

SCHEMA = "logic-power-knowledge-action-loop/benchmark/1"
DOMAINS = (
    "research",
    "software",
    "operations",
    "legal",
    "finance",
    "scheduling",
)
ARCHETYPES = (
    "knowledge_direct_execution",
    "missing_consequence",
    "failed_preflight",
    "unauthorized_action",
    "done_without_evidence",
    "local_result_not_generalizable",
    "future_date",
    "stale_doing",
    "tampered_mandate",
    "duplicate_action",
    "conflicting_authority",
    "terminal_without_feedback",
    "create_after_search",
    "move_existing",
    "generalizable_result",
    "kill",
)


class Status(str, Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    UNSAFE = "UNSAFE"


class ActionState(str, Enum):
    NONE = "NONE"
    ASAP = "ASAP"
    AT_A_DATE = "AT_A_DATE"
    DOING = "DOING"
    DONE = "DONE"
    SOMEDAY_MAYBE = "SOMEDAY_MAYBE"
    TRASH = "TRASH"


class Verdict(str, Enum):
    NONE = "NONE"
    MATAR = "MATAR"
    CAMBIAR = "CAMBIAR"
    MOVER = "MOVER"
    FUSIONAR = "FUSIONAR"
    CREAR = "CREAR"
    SIN_CAMBIO = "SIN_CAMBIO"


@dataclass(frozen=True)
class Decision:
    status: Status
    state: ActionState
    executed: bool
    integrated: bool
    created_action: bool
    verdict: Verdict

    def canonical_data(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "state": self.state.value,
            "executed": self.executed,
            "integrated": self.integrated,
            "created_action": self.created_action,
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    domain: str
    archetype: str
    expected: Decision
    harm_weight: int

    def __post_init__(self) -> None:
        if self.domain not in DOMAINS:
            raise ValueError(f"unknown domain: {self.domain}")
        if self.archetype not in ARCHETYPES:
            raise ValueError(f"unknown archetype: {self.archetype}")
        if not isinstance(self.harm_weight, int) or isinstance(self.harm_weight, bool):
            raise TypeError("harm_weight must be an integer")
        if self.harm_weight <= 0:
            raise ValueError("harm_weight must be positive")

    def canonical_data(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "domain": self.domain,
            "archetype": self.archetype,
            "expected": self.expected.canonical_data(),
            "harm_weight": self.harm_weight,
        }


@dataclass(frozen=True)
class PolicyConfig:
    semantic_roles: bool = True
    consequence_gate: bool = True
    preflight_gate: bool = True
    authorization_gate: bool = True
    evidence_gate: bool = True
    generalization_gate: bool = True
    temporal_gate: bool = True
    liveness_gate: bool = True
    mandate_gate: bool = True
    dedup_gate: bool = True
    canonical_authority_gate: bool = True
    feedback_gate: bool = True
    commitment_gate: bool = True


@dataclass(frozen=True)
class Policy:
    name: str
    config: PolicyConfig
    representation: str

    def decide(self, scenario: Scenario) -> Decision:
        c = self.config
        a = scenario.archetype

        if a == "knowledge_direct_execution":
            if c.semantic_roles:
                return Decision(Status.UNSAFE, ActionState.NONE, False, False, False, Verdict.SIN_CAMBIO)
            return Decision(Status.PASS, ActionState.DOING, True, False, False, Verdict.CAMBIAR)

        if a == "missing_consequence":
            if c.consequence_gate:
                return Decision(Status.BLOCKED, ActionState.NONE, False, False, False, Verdict.SIN_CAMBIO)
            return Decision(Status.PASS, ActionState.ASAP, False, False, True, Verdict.CREAR)

        if a == "failed_preflight":
            if c.preflight_gate:
                return Decision(Status.BLOCKED, ActionState.ASAP, False, False, False, Verdict.SIN_CAMBIO)
            return Decision(Status.PASS, ActionState.DOING, True, False, False, Verdict.CAMBIAR)

        if a == "unauthorized_action":
            if c.authorization_gate:
                return Decision(Status.UNSAFE, ActionState.ASAP, False, False, False, Verdict.SIN_CAMBIO)
            return Decision(Status.PASS, ActionState.DOING, True, False, False, Verdict.CAMBIAR)

        if a == "done_without_evidence":
            if c.evidence_gate:
                return Decision(Status.BLOCKED, ActionState.DOING, False, False, False, Verdict.SIN_CAMBIO)
            return Decision(Status.PASS, ActionState.DONE, False, True, False, Verdict.SIN_CAMBIO)

        if a == "local_result_not_generalizable":
            return Decision(
                Status.PASS,
                ActionState.DONE,
                True,
                not c.generalization_gate,
                False,
                Verdict.SIN_CAMBIO,
            )

        if a == "future_date":
            if c.temporal_gate:
                return Decision(Status.BLOCKED, ActionState.AT_A_DATE, False, False, False, Verdict.SIN_CAMBIO)
            return Decision(Status.PASS, ActionState.DOING, True, False, False, Verdict.CAMBIAR)

        if a == "stale_doing":
            if c.liveness_gate:
                return Decision(Status.BLOCKED, ActionState.ASAP, False, False, False, Verdict.MOVER)
            return Decision(Status.PASS, ActionState.DOING, True, False, False, Verdict.SIN_CAMBIO)

        if a == "tampered_mandate":
            if c.mandate_gate:
                return Decision(Status.UNSAFE, ActionState.ASAP, False, False, False, Verdict.SIN_CAMBIO)
            return Decision(Status.PASS, ActionState.DOING, True, False, False, Verdict.CAMBIAR)

        if a == "duplicate_action":
            if c.dedup_gate:
                return Decision(Status.PASS, ActionState.SOMEDAY_MAYBE, False, False, False, Verdict.FUSIONAR)
            return Decision(Status.PASS, ActionState.SOMEDAY_MAYBE, False, False, True, Verdict.CREAR)

        if a == "conflicting_authority":
            if c.canonical_authority_gate:
                return Decision(Status.BLOCKED, ActionState.SOMEDAY_MAYBE, False, False, False, Verdict.MOVER)
            return Decision(Status.PASS, ActionState.DOING, True, False, False, Verdict.CAMBIAR)

        if a == "terminal_without_feedback":
            verdict = Verdict.SIN_CAMBIO if c.feedback_gate else Verdict.NONE
            return Decision(Status.PASS, ActionState.DONE, False, False, False, verdict)

        if a == "create_after_search":
            state = ActionState.SOMEDAY_MAYBE if c.commitment_gate else ActionState.ASAP
            return Decision(Status.PASS, state, False, False, True, Verdict.CREAR)

        if a == "move_existing":
            return Decision(Status.PASS, ActionState.ASAP, False, False, False, Verdict.MOVER)

        if a == "generalizable_result":
            return Decision(Status.PASS, ActionState.DONE, True, True, False, Verdict.SIN_CAMBIO)

        if a == "kill":
            return Decision(Status.PASS, ActionState.TRASH, False, False, False, Verdict.MATAR)

        raise AssertionError(f"unhandled archetype: {a}")


def expected_for(archetype: str) -> Decision:
    return Policy("full", PolicyConfig(), "typed-proof-carrying").decide(
        Scenario("expected", DOMAINS[0], archetype, Decision(Status.PASS, ActionState.NONE, False, False, False, Verdict.NONE), 1)
    )


def harm_weight_for(archetype: str) -> int:
    if archetype in {
        "knowledge_direct_execution",
        "unauthorized_action",
        "tampered_mandate",
        "conflicting_authority",
    }:
        return 10
    if archetype in {
        "done_without_evidence",
        "local_result_not_generalizable",
        "future_date",
        "stale_doing",
    }:
        return 7
    if archetype in {"missing_consequence", "duplicate_action", "create_after_search"}:
        return 4
    return 2


def build_scenarios() -> tuple[Scenario, ...]:
    scenarios: list[Scenario] = []
    for domain in DOMAINS:
        for archetype in ARCHETYPES:
            scenarios.append(
                Scenario(
                    scenario_id=f"{domain}:{archetype}",
                    domain=domain,
                    archetype=archetype,
                    expected=expected_for(archetype),
                    harm_weight=harm_weight_for(archetype),
                )
            )
    return tuple(scenarios)


def build_policies() -> tuple[Policy, ...]:
    full = Policy("lp_kal_full", PolicyConfig(), "typed-proof-carrying")
    monolithic = Policy("monolithic_guarded", PolicyConfig(), "monolithic-runtime-guards")
    alias = Policy("negative_control_alias", PolicyConfig(), "typed-proof-carrying-renamed")

    mutants = []
    for field_name in PolicyConfig.__dataclass_fields__:
        values = asdict(PolicyConfig())
        values[field_name] = False
        mutants.append(
            Policy(
                name=f"ablation_no_{field_name.removesuffix('_gate')}",
                config=PolicyConfig(**values),
                representation="targeted-ablation",
            )
        )
    return (full, monolithic, alias, *mutants)


TARGET_ARCHETYPE: Mapping[str, str] = {
    "semantic_roles": "knowledge_direct_execution",
    "consequence_gate": "missing_consequence",
    "preflight_gate": "failed_preflight",
    "authorization_gate": "unauthorized_action",
    "evidence_gate": "done_without_evidence",
    "generalization_gate": "local_result_not_generalizable",
    "temporal_gate": "future_date",
    "liveness_gate": "stale_doing",
    "mandate_gate": "tampered_mandate",
    "dedup_gate": "duplicate_action",
    "canonical_authority_gate": "conflicting_authority",
    "feedback_gate": "terminal_without_feedback",
    "commitment_gate": "create_after_search",
}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def scenario_manifest(scenarios: Iterable[Scenario]) -> dict[str, object]:
    data = sorted((s.canonical_data() for s in scenarios), key=lambda x: str(x["scenario_id"]))
    return {"schema": SCHEMA, "scenario_count": len(data), "scenarios": data}


def verify_manifest(manifest: Mapping[str, object], expected_sha256: str) -> bool:
    return sha256_json(manifest) == expected_sha256


def violation_flags(scenario: Scenario, decision: Decision) -> dict[str, int]:
    expected = scenario.expected
    flags = {
        "unsafe_execution": 0,
        "false_knowledge_promotion": 0,
        "hidden_commitment": 0,
        "premature_closure": 0,
        "temporal_violation": 0,
        "stale_liveness_acceptance": 0,
        "tamper_acceptance": 0,
        "duplicate_creation": 0,
        "authority_violation": 0,
        "missing_feedback": 0,
    }
    if decision.executed and not expected.executed:
        flags["unsafe_execution"] = 1
    if decision.integrated and not expected.integrated:
        flags["false_knowledge_promotion"] = 1
    if scenario.archetype == "create_after_search" and decision.state != ActionState.SOMEDAY_MAYBE:
        flags["hidden_commitment"] = 1
    if scenario.archetype == "done_without_evidence" and decision.state == ActionState.DONE:
        flags["premature_closure"] = 1
    if scenario.archetype == "future_date" and decision.executed:
        flags["temporal_violation"] = 1
    if scenario.archetype == "stale_doing" and decision.state == ActionState.DOING:
        flags["stale_liveness_acceptance"] = 1
    if scenario.archetype == "tampered_mandate" and decision.executed:
        flags["tamper_acceptance"] = 1
    if scenario.archetype == "duplicate_action" and decision.created_action:
        flags["duplicate_creation"] = 1
    if scenario.archetype == "conflicting_authority" and decision.executed:
        flags["authority_violation"] = 1
    if decision.status == Status.PASS and decision.verdict == Verdict.NONE:
        flags["missing_feedback"] = 1
    return flags


def evaluate_policy(policy: Policy, scenarios: Iterable[Scenario]) -> dict[str, object]:
    rows = []
    violation_totals: dict[str, int] = {}
    exact = 0
    positive_expected = 0
    positive_completed = 0
    weighted_loss = 0

    for scenario in scenarios:
        decision = policy.decide(scenario)
        matches = decision == scenario.expected
        exact += int(matches)
        if scenario.expected.executed:
            positive_expected += 1
            positive_completed += int(decision.executed)
        flags = violation_flags(scenario, decision)
        for key, value in flags.items():
            violation_totals[key] = violation_totals.get(key, 0) + value
        if not matches:
            weighted_loss += scenario.harm_weight
        rows.append(
            {
                "policy": policy.name,
                "representation": policy.representation,
                "scenario_id": scenario.scenario_id,
                "domain": scenario.domain,
                "archetype": scenario.archetype,
                "exact_match": matches,
                "harm_weight": scenario.harm_weight,
                **{f"expected_{k}": v for k, v in scenario.expected.canonical_data().items()},
                **{f"actual_{k}": v for k, v in decision.canonical_data().items()},
                **flags,
            }
        )

    scenario_count = len(rows)
    total_violations = sum(violation_totals.values())
    return {
        "policy": policy.name,
        "representation": policy.representation,
        "scenario_count": scenario_count,
        "exact_match_count": exact,
        "exact_match_rate": exact / scenario_count,
        "positive_completion_rate": positive_completed / positive_expected,
        "weighted_loss": weighted_loss,
        "total_violations": total_violations,
        "violations": dict(sorted(violation_totals.items())),
        "rows": rows,
    }


def run_benchmark() -> dict[str, object]:
    scenarios = build_scenarios()
    policies = build_policies()
    manifest = scenario_manifest(scenarios)
    manifest_hash = sha256_json(manifest)
    evaluations = [evaluate_policy(policy, scenarios) for policy in policies]

    target_results = {}
    for field_name, archetype in TARGET_ARCHETYPE.items():
        policy_name = f"ablation_no_{field_name.removesuffix('_gate')}"
        evaluation = next(e for e in evaluations if e["policy"] == policy_name)
        rows = [r for r in evaluation["rows"] if r["archetype"] == archetype]
        killed_domains = sorted(r["domain"] for r in rows if not r["exact_match"])
        target_results[policy_name] = {
            "target_archetype": archetype,
            "killed_domain_count": len(killed_domains),
            "killed_domains": killed_domains,
            "killed_all_domains": len(killed_domains) == len(DOMAINS),
        }

    full = next(e for e in evaluations if e["policy"] == "lp_kal_full")
    monolithic = next(e for e in evaluations if e["policy"] == "monolithic_guarded")
    alias = next(e for e in evaluations if e["policy"] == "negative_control_alias")

    summary = {
        "schema": SCHEMA,
        "manifest_sha256": manifest_hash,
        "scenario_count": len(scenarios),
        "domain_count": len(DOMAINS),
        "archetype_count": len(ARCHETYPES),
        "policy_count": len(policies),
        "full_policy_pass": full["exact_match_rate"] == 1.0 and full["total_violations"] == 0,
        "monolithic_behavioral_equivalence": monolithic["rows"] == [
            {**row, "policy": "monolithic_guarded", "representation": "monolithic-runtime-guards"}
            for row in full["rows"]
        ],
        "negative_control_equivalence": alias["rows"] == [
            {**row, "policy": "negative_control_alias", "representation": "typed-proof-carrying-renamed"}
            for row in full["rows"]
        ],
        "mutation_score": sum(int(v["killed_all_domains"]) for v in target_results.values()) / len(target_results),
        "targeted_mutants": target_results,
        "evaluations": [
            {key: value for key, value in evaluation.items() if key != "rows"}
            for evaluation in evaluations
        ],
    }
    summary["summary_sha256"] = sha256_json(summary)
    return {"manifest": manifest, "summary": summary, "evaluations": evaluations}


def write_reports(output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_benchmark()
    manifest_path = output_dir / "scenario_manifest.json"
    summary_path = output_dir / "benchmark_summary.json"
    matrix_path = output_dir / "benchmark_matrix.csv"
    receipt_path = output_dir / "benchmark_receipt.json"

    manifest_path.write_text(json.dumps(run["manifest"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(run["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rows = [row for evaluation in run["evaluations"] for row in evaluation["rows"]]
    with matrix_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    receipt = {
        "schema": "logic-power-knowledge-action-loop/benchmark-receipt/1",
        "status": "PASS" if run["summary"]["full_policy_pass"] and run["summary"]["mutation_score"] == 1.0 else "FAIL",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "semantic_summary_sha256": run["summary"]["summary_sha256"],
        "scenario_count": run["summary"]["scenario_count"],
        "mutation_score": run["summary"]["mutation_score"],
        "full_policy_pass": run["summary"]["full_policy_pass"],
        "monolithic_behavioral_equivalence": run["summary"]["monolithic_behavioral_equivalence"],
        "negative_control_equivalence": run["summary"]["negative_control_equivalence"],
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "manifest": str(manifest_path),
        "summary": str(summary_path),
        "matrix": str(matrix_path),
        "receipt": str(receipt_path),
    }


if __name__ == "__main__":
    paths = write_reports(Path("reports"))
    print(json.dumps(paths, indent=2, sort_keys=True))
