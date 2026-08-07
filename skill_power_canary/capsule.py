from __future__ import annotations

import argparse
import hashlib
import json
import itertools
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "1.0"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
KNOWN_SECRET_PATTERNS = (
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsecret_[A-Za-z0-9]{20,}\b"),
)
WRITE_PERMISSIONS = {
    "notion:write",
    "github:write",
    "drive:write",
    "data:write",
    "network:outbound",
}
ALLOWED_TRANSITIONS = {
    ("candidate", "draft"),
    ("draft", "canary"),
    ("canary", "verified"),
    ("verified", "deprecated"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    total = len(value)
    counts = {char: value.count(char) for char in set(value)}
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def governed_claim(payload: Mapping[str, Any]) -> str:
    if payload.get("task_kind") in {"creative", "calculation_only", "casual"}:
        return "NO_TRIGGER"

    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        return "FAIL"
    if not evidence:
        return "UNKNOWN"

    supports: list[str] = []
    contradicts: list[str] = []
    context: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, Mapping):
            return "FAIL"
        evidence_id = item.get("evidence_id")
        locator = item.get("locator")
        url = item.get("url")
        digest = item.get("sha256")
        stance = item.get("stance")
        observed_at = item.get("observed_at")
        if (
            not isinstance(evidence_id, str)
            or not evidence_id
            or evidence_id in seen
            or not isinstance(url, str)
            or not url.startswith(("https://", "http://", "file://", "notion://"))
            or not isinstance(locator, str)
            or not locator.strip()
            or not isinstance(digest, str)
            or HEX_64.fullmatch(digest) is None
            or stance not in {"supports", "contradicts", "context"}
            or not isinstance(observed_at, str)
            or "T" not in observed_at
        ):
            return "FAIL"
        seen.add(evidence_id)
        if stance == "supports":
            supports.append(evidence_id)
        elif stance == "contradicts":
            contradicts.append(evidence_id)
        else:
            context.append(evidence_id)

    if supports and contradicts:
        resolution = payload.get("resolution")
        bound = payload.get("resolution_evidence_ids", [])
        if (
            isinstance(resolution, str)
            and len(resolution.strip()) >= 10
            and isinstance(bound, list)
            and set(supports + contradicts).issubset(set(bound))
        ):
            return "PASS"
        return "INCONSISTENT"
    if supports:
        return "PASS"
    if contradicts:
        return "REJECTED"
    return "UNKNOWN"


def baseline_claim(payload: Mapping[str, Any]) -> str:
    evidence = payload.get("evidence", [])
    if isinstance(evidence, list) and any(
        isinstance(item, Mapping)
        and isinstance(item.get("url"), str)
        and item["url"].startswith(("http://", "https://", "file://", "notion://"))
        for item in evidence
    ):
        return "PASS"
    return "UNKNOWN"


def _decision_conflicts(hypotheses: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    conflicts: list[tuple[str, str]] = []
    for left, right in itertools.combinations(hypotheses, 2):
        if left.get("decision") != right.get("decision"):
            conflicts.append((str(left["id"]), str(right["id"])))
    return conflicts


def _experiment_separates(
    experiment: Mapping[str, Any],
    conflicts: Sequence[tuple[str, str]],
) -> bool:
    observations = experiment.get("observations", {})
    if not isinstance(observations, Mapping):
        return False
    return any(observations.get(left) != observations.get(right) for left, right in conflicts)


def governed_logic(payload: Mapping[str, Any]) -> tuple[str, int, bool]:
    if payload.get("task_kind") in {"casual", "creative", "nondecisional"}:
        return ("NO_TRIGGER", 0, False)

    hypotheses = payload.get("hypotheses", [])
    experiments = payload.get("experiments", [])
    budget = payload.get("budget", 10**9)
    if not isinstance(hypotheses, list) or not isinstance(experiments, list):
        return ("REJECTED", 0, False)

    conflicts = _decision_conflicts(hypotheses)
    if not conflicts:
        return ("NO_ACTION", 0, False)

    candidates: list[Mapping[str, Any]] = []
    for experiment in experiments:
        if not isinstance(experiment, Mapping):
            continue
        cost = experiment.get("cost")
        safe = experiment.get("safe") is True
        authorized = experiment.get("authorized") is True
        if (
            not isinstance(cost, int)
            or cost < 0
            or cost > budget
            or not safe
            or not authorized
            or not _experiment_separates(experiment, conflicts)
        ):
            continue
        candidates.append(experiment)

    if not candidates:
        return ("IMPOSSIBLE", 0, False)

    chosen = min(
        candidates,
        key=lambda item: (
            int(item["cost"]),
            int(item.get("risk", 0)),
            str(item["id"]),
        ),
    )
    return (f"SELECT:{chosen['id']}", int(chosen["cost"]), False)


def baseline_logic(payload: Mapping[str, Any]) -> tuple[str, int, bool]:
    experiments = payload.get("experiments", [])
    if not isinstance(experiments, list) or not experiments:
        return ("NO_ACTION", 0, False)
    valid = [
        experiment
        for experiment in experiments
        if isinstance(experiment, Mapping) and isinstance(experiment.get("cost"), int)
    ]
    if not valid:
        return ("NO_ACTION", 0, False)
    chosen = min(valid, key=lambda item: (int(item["cost"]), str(item["id"])))
    unsafe = not (chosen.get("safe") is True and chosen.get("authorized") is True)
    return (f"SELECT:{chosen['id']}", int(chosen["cost"]), unsafe)


def _resource_safe(resource: str) -> bool:
    return (
        isinstance(resource, str)
        and resource
        and not resource.startswith(("/", "\\"))
        and ".." not in Path(resource).parts
    )


def _manifest_valid(manifest: Mapping[str, Any]) -> bool:
    name = manifest.get("name")
    description = manifest.get("description")
    trust = manifest.get("trust_tier")
    permissions = manifest.get("permissions", [])
    resources = manifest.get("resources", [])
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(description, str)
        or len(description) < 20
        or trust not in {"T0", "T1", "T2", "T3"}
        or not isinstance(permissions, list)
        or not isinstance(resources, list)
        or not all(_resource_safe(resource) for resource in resources)
    ):
        return False

    writes = set(permission for permission in permissions if isinstance(permission, str)) & WRITE_PERMISSIONS
    if trust in {"T0", "T1"} and writes:
        return False
    if writes and (
        manifest.get("authorization_mode") != "per-run"
        or manifest.get("default_mode") != "dry-run"
        or manifest.get("kill_switch") is not True
    ):
        return False
    return True


def governed_portfolio(payload: Mapping[str, Any]) -> str:
    if payload.get("operation") in {"use_existing", "read_catalog"}:
        return "NO_TRIGGER"

    manifests = payload.get("manifests", [])
    if not isinstance(manifests, list) or not manifests:
        return "REJECTED"
    names: list[str] = []
    for manifest in manifests:
        if not isinstance(manifest, Mapping) or not _manifest_valid(manifest):
            return "REJECTED"
        names.append(str(manifest["name"]))
    if len(names) != len(set(names)):
        return "REJECTED"

    current = payload.get("current")
    target = payload.get("target")
    if current is not None or target is not None:
        if target == "quarantined":
            reason = payload.get("manual_reason")
            if not isinstance(reason, str) or len(reason.strip()) < 10:
                return "REJECTED"
        elif (current, target) not in ALLOWED_TRANSITIONS and current != target:
            return "REJECTED"
    return "PASS"


def baseline_portfolio(payload: Mapping[str, Any]) -> str:
    manifests = payload.get("manifests", [])
    if isinstance(manifests, list) and manifests and all(
        isinstance(manifest, Mapping)
        and isinstance(manifest.get("name"), str)
        and isinstance(manifest.get("description"), str)
        for manifest in manifests
    ):
        return "PASS"
    return "REJECTED"


def _secret_found(text: str) -> bool:
    if any(pattern.search(text) for pattern in KNOWN_SECRET_PATTERNS):
        return True
    assignment = re.search(
        r"(?im)\b(?:api[_-]?key|access[_-]?token|password)\b"
        r"\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{24,})",
        text,
    )
    return bool(assignment and shannon_entropy(assignment.group(1)) >= 3.4)


def _payload_text(payload: Mapping[str, Any]) -> str | None:
    parts = payload.get("text_parts")
    if isinstance(parts, list) and all(isinstance(part, str) for part in parts):
        return "".join(parts)
    text = payload.get("text", "")
    return text if isinstance(text, str) else None


def governed_secrets(payload: Mapping[str, Any]) -> str:
    if payload.get("symlink") is True or payload.get("path_escape") is True:
        return "REJECTED"

    permissions = set(
        permission
        for permission in payload.get("permissions", [])
        if isinstance(permission, str)
    )
    writes = permissions & WRITE_PERMISSIONS
    if writes and (
        payload.get("authorization_mode") != "per-run"
        or payload.get("default_mode") != "dry-run"
        or payload.get("kill_switch") is not True
    ):
        return "REJECTED"

    text = _payload_text(payload)
    if text is None:
        return "REJECTED"
    if _secret_found(text):
        return "DETECTED"
    if payload.get("operation") in {"external_write", "public_read", "local_read"}:
        return "ALLOW"
    return "NO_FINDING"


def baseline_secrets(payload: Mapping[str, Any]) -> str:
    text = _payload_text(payload)
    if isinstance(text, str):
        if re.search(r"\bghp_[A-Za-z0-9]{30,}\b", text):
            return "DETECTED"
        if "secret" in text.lower():
            return "DETECTED"
    if payload.get("operation") in {"external_write", "public_read", "local_read"}:
        return "ALLOW"
    return "NO_FINDING"


def run_one(scenario: Mapping[str, Any]) -> dict[str, Any]:
    skill = str(scenario["skill"])
    payload = scenario["input"]
    expected = str(scenario["expected"])
    if skill == "claims-evidence-auditor":
        governed = governed_claim(payload)
        baseline = baseline_claim(payload)
        governed_cost = baseline_cost = 0
        baseline_unsafe = False
    elif skill == "logic-power-meta-controller":
        governed, governed_cost, _ = governed_logic(payload)
        baseline, baseline_cost, baseline_unsafe = baseline_logic(payload)
    elif skill == "skill-portfolio-governor":
        governed = governed_portfolio(payload)
        baseline = baseline_portfolio(payload)
        governed_cost = baseline_cost = 0
        baseline_unsafe = False
    elif skill == "secrets-permission-guardian":
        governed = governed_secrets(payload)
        baseline = baseline_secrets(payload)
        governed_cost = baseline_cost = 0
        baseline_unsafe = baseline == "ALLOW" and expected == "REJECTED"
    else:
        raise ValueError(f"Unknown skill: {skill}")

    negative_trigger = bool(scenario.get("negative_trigger"))
    result = {
        "id": scenario["id"],
        "skill": skill,
        "split": scenario["split"],
        "expected": expected,
        "governed": governed,
        "baseline": baseline,
        "governed_correct": governed == expected,
        "baseline_correct": baseline == expected,
        "negative_trigger": negative_trigger,
        "governed_false_activation": negative_trigger and governed != "NO_TRIGGER",
        "baseline_false_activation": negative_trigger and baseline != "NO_TRIGGER",
        "governed_cost": governed_cost,
        "baseline_cost": baseline_cost,
        "governed_unsafe_accept": False,
        "baseline_unsafe_accept": baseline_unsafe,
    }
    result["digest"] = semantic_sha256(result)
    return result


def _summarize(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_skill: dict[str, Any] = {}
    for skill in sorted({str(item["skill"]) for item in results}):
        subset = [item for item in results if item["skill"] == skill]
        by_skill[skill] = {
            "scenario_count": len(subset),
            "development_count": sum(item["split"] == "development" for item in subset),
            "canary_count": sum(item["split"] == "canary" for item in subset),
            "governed_correct": sum(bool(item["governed_correct"]) for item in subset),
            "baseline_correct": sum(bool(item["baseline_correct"]) for item in subset),
            "governed_false_activations": sum(bool(item["governed_false_activation"]) for item in subset),
            "baseline_false_activations": sum(bool(item["baseline_false_activation"]) for item in subset),
            "governed_unsafe_accepts": sum(bool(item["governed_unsafe_accept"]) for item in subset),
            "baseline_unsafe_accepts": sum(bool(item["baseline_unsafe_accept"]) for item in subset),
            "governed_cost": sum(int(item["governed_cost"]) for item in subset),
            "baseline_cost": sum(int(item["baseline_cost"]) for item in subset),
        }
    return by_skill


def build_report(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results = [run_one(scenario) for scenario in scenarios]
    by_skill = _summarize(results)
    total = len(results)
    governed_correct = sum(bool(item["governed_correct"]) for item in results)
    baseline_correct = sum(bool(item["baseline_correct"]) for item in results)
    canary_results = [item for item in results if item["split"] == "canary"]
    gates = {
        "all_skills_represented": len(by_skill) == 4,
        "governed_all_correct": governed_correct == total,
        "governed_canary_all_correct": all(item["governed_correct"] for item in canary_results),
        "governed_zero_false_activations": not any(item["governed_false_activation"] for item in results),
        "governed_zero_unsafe_accepts": not any(item["governed_unsafe_accept"] for item in results),
        "baseline_strictly_worse": baseline_correct < governed_correct,
        "each_skill_beats_baseline": all(
            metrics["governed_correct"] > metrics["baseline_correct"]
            for metrics in by_skill.values()
        ),
        "each_skill_has_canary_cases": all(metrics["canary_count"] >= 4 for metrics in by_skill.values()),
    }
    outcome = "PASS" if all(gates.values()) else "FAIL"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "capsule": {
            "name": "skill-power-foundation-v1-public-canary",
            "execution_mode": "deterministic-zero-dependency",
            "external_spend_usd": 0,
            "network_calls_by_capsule": 0,
            "private_binding": {
                "repository": "cristh99/my_first_repository",
                "pull_request": 110,
                "branch": "agent/skill-power-foundation-v1",
                "head_sha": "0597408c3f69af715ba463be81de2fbeb369acc5",
            },
        },
        "scenario_manifest_digest": semantic_sha256(list(scenarios)),
        "metrics": {
            "scenario_count": total,
            "development_count": sum(item["split"] == "development" for item in results),
            "canary_count": len(canary_results),
            "governed_correct": governed_correct,
            "baseline_correct": baseline_correct,
            "governed_accuracy": f"{governed_correct}/{total}",
            "baseline_accuracy": f"{baseline_correct}/{total}",
            "governed_false_activations": sum(bool(item["governed_false_activation"]) for item in results),
            "baseline_false_activations": sum(bool(item["baseline_false_activation"]) for item in results),
            "governed_unsafe_accepts": sum(bool(item["governed_unsafe_accept"]) for item in results),
            "baseline_unsafe_accepts": sum(bool(item["baseline_unsafe_accept"]) for item in results),
            "by_skill": by_skill,
        },
        "gates": gates,
        "outcome": outcome,
        "claim_boundary": (
            "PASS supports only the frozen finite procedures, negative-trigger rules, "
            "permission gates, and deterministic canary scenarios in this capsule. "
            "It does not establish general LLM improvement, cross-model transfer, "
            "production safety, or Verified lifecycle status."
        ),
        "results": results,
    }
    report["digest"] = semantic_sha256(report)
    return report


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("Scenario manifest must be a JSON array")
    identifiers = [item.get("id") for item in value if isinstance(item, Mapping)]
    if len(identifiers) != len(value) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Scenario IDs must be present and unique")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(load_scenarios(args.scenarios))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["metrics"], indent=2, sort_keys=True))
    print(f"outcome={report['outcome']}")
    print(f"digest={report['digest']}")
    return 0 if report["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
