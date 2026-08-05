from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SKILL_PATH = ROOT / "governed_skill" / "SKILL.md"
MANIFEST_PATH = ROOT / "governed_skill" / "manifest.json"

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
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?", version):
        add(findings, "error", "SEMVER", version)

    if frontmatter.get("name") != name:
        add(findings, "critical", "FRONTMATTER_NAME_MISMATCH", name)
    if frontmatter.get("description") != manifest.get("description"):
        add(findings, "critical", "DESCRIPTION_MISMATCH", "frontmatter != manifest")

    if manifest.get("lifecycle") != "candidate":
        add(findings, "error", "FROZEN_LIFECYCLE", "public snapshot must be candidate")
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

    for resource in manifest.get("resources", []):
        path = Path(str(resource))
        if path.is_absolute() or ".." in path.parts or "\\" in str(resource):
            add(findings, "critical", "RESOURCE_PATH", str(resource))

    allowed_source_roles = {"normative", "evidence", "implementation", "inspiration"}
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            add(findings, "error", "SOURCE_OBJECT", repr(source))
            continue
        if not source.get("id") or not source.get("url"):
            add(findings, "error", "SOURCE_REQUIRED", repr(source))
        if source.get("role") not in allowed_source_roles:
            add(findings, "error", "SOURCE_ROLE", repr(source.get("role")))
        if not re.match(r"^(?:https://|github://|notion://|file://)", str(source.get("url", ""))):
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
    )
    for phrase in required_phrases:
        if phrase not in skill_text:
            add(findings, "error", "MISSING_SAFETY_PHRASE", phrase)

    return findings


def scan_texts() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    scan_paths = [
        ROOT / "candidate.py",
        ROOT / "oracle.py",
        ROOT / "fixtures.json",
        SKILL_PATH,
        MANIFEST_PATH,
    ]
    for path in scan_paths:
        text = path.read_text(encoding="utf-8")
        for code, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                add(findings, "critical", f"SECRET_{code.upper()}", str(path.relative_to(ROOT)))

    for path in (ROOT / "candidate.py", ROOT / "oracle.py"):
        text = path.read_text(encoding="utf-8")
        for code, pattern in FORBIDDEN_RUNTIME_PATTERNS.items():
            if pattern.search(text):
                add(findings, "critical", f"RUNTIME_{code.upper()}", str(path.name))

    return findings


def main() -> int:
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    frontmatter = parse_frontmatter(skill_text)
    findings = validate_manifest(manifest, frontmatter, skill_text) + scan_texts()
    findings.sort(key=lambda item: (item["severity"], item["code"], item["message"]))
    severity_counts: dict[str, int] = {}
    for finding in findings:
        severity = finding["severity"]
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    report = {
        "schema": "motherduck-ops-governor-static-validation/v1",
        "skill": manifest.get("name"),
        "version": manifest.get("version"),
        "lifecycle": manifest.get("lifecycle"),
        "trust_tier": manifest.get("trust_tier"),
        "frontmatter_matches": (
            frontmatter.get("name") == manifest.get("name")
            and frontmatter.get("description") == manifest.get("description")
        ),
        "permissions": manifest.get("permissions", []),
        "finding_count": len(findings),
        "severity_counts": severity_counts,
        "findings": findings,
        "network_permissions": 0,
        "write_permissions": 0,
        "secret_findings": sum(
            1 for finding in findings if finding["code"].startswith("SECRET_")
        ),
    }
    report["report_digest"] = hashlib.sha256(canonical_bytes(report)).hexdigest()

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "static-report.json").write_bytes(canonical_bytes(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
