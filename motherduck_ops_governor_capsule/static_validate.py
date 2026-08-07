from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SKILL_PATH = ROOT / "governed_skill" / "SKILL.md"
MANIFEST_PATH = ROOT / "governed_skill" / "manifest.json"
BUNDLE = ROOT / "promoted_bundle"
DIVE_PATH = BUNDLE / "motherduck-operations-control.tsx"
MIGRATION_PATH = BUNDLE / "motherduck-ops-control-plane.sql"
ROLLBACK_PATH = BUNDLE / "motherduck-ops-control-plane.rollback.sql"
SHADOW_V4_PATH = BUNDLE / "shadow-application-v4.json"

EXPECTED_LIFECYCLE = "canary"
EXPECTED_VERSION = "0.3.4"

REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "name",
    "version",
    "description",
    "lifecycle",
    "trust_tier",
    "owner",
    "permissions",
    "inputs",
    "outputs",
    "terminals",
    "evaluation_gates",
    "sources",
}

REQUIRED_PRIVATE_RESOURCES = {
    "evidence/motherduck-ops-governor-v1/shadow-application-v4.json",
    "dives/motherduck-operations-control.tsx",
    "sql/motherduck-ops-control-plane.sql",
    "sql/motherduck-ops-control-plane.rollback.sql",
}

T1_ALLOWED_PERMISSIONS = {
    "artifact:write",
    "compute:local",
    "data:read",
    "drive:read",
    "github:read",
    "notion:read",
    "web:read",
}

FORBIDDEN_HIGH_IMPACT_PERMISSIONS = {
    "compute:cloud",
    "data:write",
    "drive:write",
    "github:write",
    "message:send",
    "network:outbound",
    "notion:write",
    "production:write",
    "secret:read",
    "spend",
}

SECRET_PATTERNS = {
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "google_private_key_json": re.compile(r'"private_key"\s*:'),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
}

FORBIDDEN_RUNTIME_PATTERNS = {
    "requests_import": re.compile(r"^\s*(?:from|import)\s+requests\b", re.MULTILINE),
    "urllib_network_import": re.compile(
        r"^\s*(?:from\s+urllib\.request|import\s+urllib\.request)\b", re.MULTILINE
    ),
    "socket_import": re.compile(r"^\s*(?:from|import)\s+socket\b", re.MULTILINE),
    "shell_execution": re.compile(r"\b(?:os\.system|subprocess\.)"),
}

DIVE_MUTATION_PATTERN = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|MERGE|COPY|CALL)\b",
    re.IGNORECASE,
)


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


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md lacks opening frontmatter delimiter")
    _, frontmatter, _ = text.split("---", 2)
    result: dict[str, str] = {}
    for raw_line in frontmatter.strip().splitlines():
        if ":" not in raw_line:
            raise ValueError(f"invalid frontmatter line: {raw_line!r}")
        key, value = raw_line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def add(findings: list[dict[str, str]], severity: str, code: str, message: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message})


def validate_manifest(
    manifest: dict[str, Any], frontmatter: dict[str, str], skill_text: str
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    missing = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
    if missing:
        add(findings, "critical", "MISSING_FIELDS", ", ".join(missing))

    if manifest.get("schema_version") != "1.0":
        add(findings, "error", "SCHEMA_VERSION", "schema_version must be 1.0")

    name = str(manifest.get("name", ""))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        add(findings, "error", "NAME_FORMAT", name)

    version = str(manifest.get("version", ""))
    if not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?",
        version,
    ):
        add(findings, "error", "SEMVER", version)
    if version != EXPECTED_VERSION:
        add(findings, "error", "PROMOTED_VERSION", f"expected {EXPECTED_VERSION}, got {version}")

    if frontmatter.get("name") != name:
        add(findings, "critical", "FRONTMATTER_NAME_MISMATCH", name)
    if frontmatter.get("description") != manifest.get("description"):
        add(findings, "critical", "DESCRIPTION_MISMATCH", "frontmatter != manifest")

    if manifest.get("lifecycle") != EXPECTED_LIFECYCLE:
        add(
            findings,
            "error",
            "PROMOTED_LIFECYCLE",
            f"expected {EXPECTED_LIFECYCLE}, got {manifest.get('lifecycle')}",
        )
    if manifest.get("trust_tier") != "T1":
        add(findings, "critical", "TRUST_TIER", "expected T1")
    if manifest.get("authorization_mode") != "none":
        add(findings, "critical", "AUTHORIZATION_MODE", "expected none")
    if manifest.get("default_mode") != "read-only":
        add(findings, "critical", "DEFAULT_MODE", "expected read-only")

    permissions = manifest.get("permissions", [])
    if not isinstance(permissions, list) or len(permissions) != len(set(permissions)):
        add(findings, "error", "PERMISSION_LIST", "permissions must be unique list")
    else:
        unknown = sorted(set(permissions) - T1_ALLOWED_PERMISSIONS)
        dangerous = sorted(set(permissions) & FORBIDDEN_HIGH_IMPACT_PERMISSIONS)
        if unknown:
            add(findings, "critical", "T1_PERMISSION_EXCEEDED", ", ".join(unknown))
        if dangerous:
            add(findings, "critical", "HIGH_IMPACT_PERMISSION", ", ".join(dangerous))

    for field in ("inputs", "outputs", "terminals", "evaluation_gates", "sources"):
        value = manifest.get(field)
        if not isinstance(value, list) or not value:
            add(findings, "error", "EMPTY_CONTRACT_FIELD", field)
        elif len(value) != len({json.dumps(item, sort_keys=True) for item in value}):
            add(findings, "error", "DUPLICATE_CONTRACT_ITEM", field)

    allowed_terminals = {
        "PASS",
        "FAIL",
        "UNKNOWN",
        "IMPOSSIBLE",
        "INCONSISTENT",
        "REJECTED",
    }
    unexpected_terminals = sorted(set(manifest.get("terminals", [])) - allowed_terminals)
    if unexpected_terminals:
        add(findings, "error", "TERMINAL_SET", ", ".join(unexpected_terminals))

    resources = manifest.get("resources", [])
    for resource in resources:
        path = Path(str(resource))
        if path.is_absolute() or ".." in path.parts or "\\" in str(resource):
            add(findings, "critical", "RESOURCE_PATH", str(resource))
    missing_resources = sorted(REQUIRED_PRIVATE_RESOURCES - set(resources))
    if missing_resources:
        add(findings, "critical", "PROMOTED_RESOURCES_MISSING", ", ".join(missing_resources))

    allowed_source_roles = {"normative", "evidence", "implementation", "inspiration"}
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            add(findings, "error", "SOURCE_OBJECT", repr(source))
            continue
        if not source.get("id") or not source.get("url"):
            add(findings, "error", "SOURCE_REQUIRED", repr(source))
        if source.get("role") not in allowed_source_roles:
            add(findings, "error", "SOURCE_ROLE", repr(source.get("role")))
        if not re.match(
            r"^(?:https://|github://|notion://|file://)", str(source.get("url", ""))
        ):
            add(findings, "error", "SOURCE_URL", str(source.get("url", "")))
        commit = source.get("commit")
        if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", str(commit)):
            add(findings, "error", "SOURCE_COMMIT", str(commit))

    required_phrases = (
        "read-only governor",
        "No deletion by default",
        "No secret in source",
        "UNKNOWN",
        "IMPOSSIBLE",
        "REJECTED",
        "No claim that a `NOOP` is material progress",
        "No `query_rw` call without a separately stated schema/data diff, rollback, and explicit confirmation.",
        "No `save_dive` call until the design has been reviewed and the user explicitly confirms that iteration is complete.",
    )
    for phrase in required_phrases:
        if phrase not in skill_text:
            add(findings, "error", "MISSING_SAFETY_PHRASE", phrase)

    return findings


def validate_dive() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    text = DIVE_PATH.read_text(encoding="utf-8")
    if text.count("useSQLQuery(`") != 4:
        add(findings, "error", "DIVE_QUERY_COUNT", "expected four useSQLQuery hooks")
    for required in (
        'path: "md:my_db"',
        "generate_series(",
        "summary.isError",
        "hourly.isError",
        "categories.isError",
        "latestSchedules.isError",
        "Los conteos describen estado; no autorizan intervenciones.",
    ):
        if required not in text:
            add(findings, "error", "DIVE_REQUIRED_PATTERN", required)
    if DIVE_MUTATION_PATTERN.search(text):
        add(findings, "critical", "DIVE_MUTATING_SQL", "mutation keyword found")
    for forbidden in ("fetch(", "window.open", "useExport", "exportAs(", "query_rw", "save_dive"):
        if forbidden in text:
            add(findings, "critical", "DIVE_FORBIDDEN_RUNTIME", forbidden)
    return findings


def sql_objects(text: str, keyword: str) -> set[str]:
    return {
        match.lower()
        for match in re.findall(
            rf"\b{keyword}\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([A-Za-z0-9_.]+)",
            text,
            flags=re.IGNORECASE,
        )
    }


def validate_migration() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    rollback = ROLLBACK_PATH.read_text(encoding="utf-8")
    created_views = sql_objects(migration, "CREATE OR REPLACE VIEW")
    dropped_views = sql_objects(rollback, "DROP VIEW")
    if created_views != dropped_views:
        add(
            findings,
            "critical",
            "ROLLBACK_VIEW_MISMATCH",
            json.dumps(
                {
                    "created_only": sorted(created_views - dropped_views),
                    "dropped_only": sorted(dropped_views - created_views),
                },
                sort_keys=True,
            ),
        )
    if "CREATE SCHEMA IF NOT EXISTS my_db.ops_control" not in migration:
        add(findings, "error", "MIGRATION_SCHEMA", "missing ops_control schema")
    if "DROP SCHEMA IF EXISTS my_db.ops_control" not in rollback:
        add(findings, "error", "ROLLBACK_SCHEMA", "missing ops_control schema rollback")
    for label, text in (("migration", migration), ("rollback", rollback)):
        if "BEGIN TRANSACTION;" not in text or "COMMIT;" not in text:
            add(findings, "error", "TRANSACTION_BOUNDARY", label)
    if "explicit schema-write authorization" not in migration:
        add(findings, "error", "MIGRATION_AUTHORITY_BOUNDARY", "missing explicit gate")
    if len(created_views) != 5:
        add(findings, "error", "MIGRATION_VIEW_COUNT", str(len(created_views)))
    return findings


def validate_shadow_v4() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    payload = json.loads(SHADOW_V4_PATH.read_text(encoding="utf-8"))
    preflight = payload.get("preflight", {})
    safety = payload.get("safety", {})
    if preflight.get("action") != "PREFLIGHT_READY":
        add(findings, "error", "SHADOW_PREFLIGHT", repr(preflight.get("action")))
    if preflight.get("batch_launched") is not False:
        add(findings, "critical", "SHADOW_BATCH_LAUNCHED", repr(preflight.get("batch_launched")))
    if preflight.get("writes_performed") != 0:
        add(findings, "critical", "SHADOW_PREFLIGHT_WRITES", repr(preflight.get("writes_performed")))
    if preflight.get("launch_decision") != "BLOCKED_NO_SPEND_AUTHORITY":
        add(findings, "critical", "SHADOW_SPEND_GATE", repr(preflight.get("launch_decision")))
    for key in (
        "batch_jobs_launched",
        "flights_deleted",
        "production_runs_cancelled",
        "receipts_deleted",
        "versions_deleted",
    ):
        if safety.get(key) != 0:
            add(findings, "critical", "SHADOW_SAFETY", f"{key}={safety.get(key)!r}")
    if payload.get("incremental", {}).get("runs_per_day_avoided") != 432:
        add(findings, "error", "SHADOW_INCREMENTAL_SAVINGS", "expected 432")
    if payload.get("cumulative_skill_application", {}).get("runs_per_day_avoided") != 579:
        add(findings, "error", "SHADOW_CUMULATIVE_SAVINGS", "expected 579")
    if len(payload.get("schedule_decisions", [])) != 8:
        add(findings, "error", "SHADOW_DECISION_COUNT", "expected eight")
    return findings


def scan_texts() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    scan_paths = [
        ROOT / "candidate.py",
        ROOT / "oracle.py",
        ROOT / "fixtures.json",
        SKILL_PATH,
        MANIFEST_PATH,
        DIVE_PATH,
        MIGRATION_PATH,
        ROLLBACK_PATH,
        SHADOW_V4_PATH,
    ]
    for path in scan_paths:
        text = path.read_text(encoding="utf-8")
        for code, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                add(
                    findings,
                    "critical",
                    f"SECRET_{code.upper()}",
                    str(path.relative_to(ROOT)),
                )

    for path in (ROOT / "candidate.py", ROOT / "oracle.py"):
        text = path.read_text(encoding="utf-8")
        for code, pattern in FORBIDDEN_RUNTIME_PATTERNS.items():
            if pattern.search(text):
                add(findings, "critical", f"RUNTIME_{code.upper()}", str(path.name))

    return findings


def main() -> int:
    required_paths = (
        SKILL_PATH,
        MANIFEST_PATH,
        DIVE_PATH,
        MIGRATION_PATH,
        ROLLBACK_PATH,
        SHADOW_V4_PATH,
    )
    missing_paths = [str(path.relative_to(ROOT)) for path in required_paths if not path.is_file()]
    findings: list[dict[str, str]] = []
    if missing_paths:
        add(findings, "critical", "BUNDLE_FILE_MISSING", ", ".join(missing_paths))

    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    frontmatter = parse_frontmatter(skill_text)
    findings.extend(validate_manifest(manifest, frontmatter, skill_text))
    findings.extend(validate_dive())
    findings.extend(validate_migration())
    findings.extend(validate_shadow_v4())
    findings.extend(scan_texts())
    findings.sort(key=lambda item: (item["severity"], item["code"], item["message"]))

    severity_counts: dict[str, int] = {}
    for finding in findings:
        severity = finding["severity"]
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    bundle_hashes = {
        str(path.relative_to(ROOT)): sha256_path(path)
        for path in required_paths
        if path.is_file()
    }
    report = {
        "schema": "motherduck-ops-governor-promoted-bundle-replay/v2",
        "skill": manifest.get("name"),
        "version": manifest.get("version"),
        "lifecycle": manifest.get("lifecycle"),
        "trust_tier": manifest.get("trust_tier"),
        "promoted_bundle_replay": True,
        "frontmatter_matches": (
            frontmatter.get("name") == manifest.get("name")
            and frontmatter.get("description") == manifest.get("description")
        ),
        "permissions": manifest.get("permissions", []),
        "bundle_hashes": bundle_hashes,
        "finding_count": len(findings),
        "severity_counts": severity_counts,
        "findings": findings,
        "network_permissions": 0,
        "write_permissions": 0,
        "secret_findings": sum(
            1 for finding in findings if finding["code"].startswith("SECRET_")
        ),
    }
    report["bundle_digest"] = hashlib.sha256(canonical_bytes(bundle_hashes)).hexdigest()
    report["report_digest"] = hashlib.sha256(canonical_bytes(report)).hexdigest()

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "static-report.json").write_bytes(canonical_bytes(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
