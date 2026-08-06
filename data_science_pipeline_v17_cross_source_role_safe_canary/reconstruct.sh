#!/usr/bin/env bash
set -euo pipefail

component="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
archive="$component/capsule.zip"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

printf '%s  %s\n' '2fe3645c5791b0e1c22b057c7138f17c8c6145ceee45a9ce28e435a56042b5c5' "$archive" | sha256sum --check
python3 - "$archive" "$work" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys

archive = Path(sys.argv[1])
out = Path(sys.argv[2])
prefix = PurePosixPath("data_science_pipeline_v17_cross_source_role_safe_canary")
expected = {
    str(prefix / name)
    for name in {
        "README.md", "PROTOCOL.json", "FREEZE.json", "SELECTION_RECEIPT.json",
        "LANE_E_RECEIPT.json", "LANE_M_RECEIPT.json", "PUBLIC_RECEIPT.json",
        "VERIFY_OUTPUT.json", "TEST_RESULT.json", "MANIFEST.json",
        "canary.py", "test_canary.py", "verify.py"
    }
}
with ZipFile(archive) as zf:
    names = zf.namelist()
    if len(names) != len(set(names)):
        raise SystemExit("duplicate ZIP member")
    if set(names) != expected:
        raise SystemExit(f"unexpected ZIP members: {sorted(set(names) ^ expected)}")
    for name in names:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts:
            raise SystemExit(f"unsafe ZIP member: {name}")
    zf.extractall(out)
PY

cd "$work/data_science_pipeline_v17_cross_source_role_safe_canary"
python3 verify.py
echo 'PASS_CROSS_SOURCE_ROLE_SEPARATION_CANARY_BLOCKED_OPERATIONAL_FIELDS'
