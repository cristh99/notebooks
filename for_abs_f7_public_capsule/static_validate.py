from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
ALLOWED_SUFFIXES = {".py", ".json", ".md"}
REQUIRED = {
    "README.md",
    "verify.py",
    "test_verify.py",
    "static_validate.py",
    "receipts/case-bundle.json",
    "receipts/adversarial-replay-v2.json",
    "receipts/operational-pointer-v2.json",
    "receipts/promotion-v2.json",
}
SECRET_PATTERNS = {
    "private_key": re.compile(r"BEGIN (?:RSA |EC )?PRIVATE KEY"),
    "google_key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "openai_key": re.compile(r"sk-(?:proj-)?[0-9A-Za-z_-]{16,}"),
    "github_token": re.compile(r"gh[opsu]_[0-9A-Za-z]{20,}"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
}
RAW_LOCATOR_PATTERNS = {
    "http_url": re.compile(r"https?://", re.I),
    "gcs_uri": re.compile(r"gs://", re.I),
    "honducompras_path": re.compile(r"honducompras", re.I),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    findings = []
    secret_findings = []
    locator_findings = []
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or "artifacts" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        files.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            findings.append({"path": relative, "finding": "UNEXPECTED_SUFFIX"})
        text = data.decode("utf-8")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                secret_findings.append({"path": relative, "pattern": name})
        if relative.startswith("receipts/"):
            for name, pattern in RAW_LOCATOR_PATTERNS.items():
                if pattern.search(text):
                    locator_findings.append({"path": relative, "pattern": name})
            json.loads(text)
    observed = {row["path"] for row in files}
    missing = sorted(REQUIRED - observed)
    extra = sorted(
        path
        for path in observed - REQUIRED
        if not path.startswith("__pycache__/")
    )
    if missing:
        findings.append({"finding": "MISSING_REQUIRED_FILES", "files": missing})
    if secret_findings:
        findings.append({"finding": "SECRET_PATTERN", "rows": secret_findings})
    if locator_findings:
        findings.append({"finding": "RAW_LOCATOR_PATTERN", "rows": locator_findings})
    report = {
        "schema_version": "for_abs_f7_public_static_validation/v1",
        "status": "PASS" if not findings else "FAIL",
        "file_count": len(files),
        "files": files,
        "required_file_count": len(REQUIRED),
        "missing_required_files": missing,
        "extra_files": extra,
        "finding_count": len(findings),
        "secret_findings": len(secret_findings),
        "raw_locator_findings": len(locator_findings),
        "findings": findings,
        "network_permissions": 0,
        "write_permissions": 0,
        "external_spend_usd": 0,
    }
    body = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report["report_digest"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "static-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
