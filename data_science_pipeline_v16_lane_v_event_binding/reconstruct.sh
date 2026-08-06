#!/usr/bin/env bash
set -euo pipefail

component="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
archive="$component/capsule.zip"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

(
  cd "$component"
  sha256sum --check CAPSULE_SHA256.txt
)

python3 - "$archive" "$work" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys

archive = Path(sys.argv[1])
out = Path(sys.argv[2])
expected = {
    "EVENT_BINDING_PROTOCOL.json",
    "FREEZE.json",
    "README.md",
    "PUBLIC_RECEIPT.json",
    "VERIFY_OUTPUT.json",
    "lane_v_binding.py",
    "test_lane_v_binding.py",
    "run_live_canary.py",
    "verify.py",
    "tests.stderr",
    "tests.stdout",
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

python3 -m compileall -q "$work"
(
  cd "$work"
  python3 verify.py
)

echo 'PASS_EVENT_BINDING_CANARY_FAIL_CLOSED_NO_TRUST'
