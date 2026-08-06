#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-.}"
component="$repo_root/data_science_pipeline_v14_analyze_contract"
archive="$component/capsule.zip"

printf '%s  %s\n' \
  '2b26ed665b9c55b040e6f222c58a8c0a8a89542d714e0d847610a7e15e66b148' \
  "$archive" | sha256sum --check

python3 - "$archive" "$repo_root" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys

archive = Path(sys.argv[1])
repo_root = Path(sys.argv[2]).resolve()
prefix = PurePosixPath("data_science_pipeline_v14_analyze_contract")
expected = {
    str(prefix) + "/",
    str(prefix / "ANALYSIS_CONTRACT.json"),
    str(prefix / "FREEZE.json"),
    str(prefix / "LOCAL_RESULT.json"),
    str(prefix / "README.md"),
    str(prefix / "SYNTHETIC_ANALYSIS_RESULT.json"),
    str(prefix / "SYNTHETIC_SEMANTIC_SNAPSHOT.json"),
    str(prefix / "VERIFY_OUTPUT.json"),
    str(prefix / "analyze.py"),
    str(prefix / "test_analyze.py"),
    str(prefix / "verify.py"),
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
    zf.extractall(repo_root)
PY

python3 -m compileall -q "$component"
(
  cd "$component"
  python3 verify.py > verification.stdout
  printf '%s  %s\n' \
    'f70d45ed9341a7c82a190a0cf7ece6c347d0529136d3571088fccbb06cad241c' \
    'LOCAL_RESULT.json' | sha256sum --check
)

echo 'PASS_STAGE09_ANALYZE_ROLE_SAFE_SOFTWARE_ONLY'
