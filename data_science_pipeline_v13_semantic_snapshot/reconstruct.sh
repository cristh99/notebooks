#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-.}"
component="$repo_root/data_science_pipeline_v13_semantic_snapshot"
archive="${TMPDIR:-/tmp}/data-science-v13-semantic-snapshot.zip"

cat "$component"/transport/part_*.b64 | base64 --decode > "$archive"
printf '%s  %s\n' \
  'dcd591d430012ea713acc81c1b65cf6b6c6c599a77552a432b35c6cbde188408' \
  "$archive" | sha256sum --check

python3 - "$archive" "$repo_root" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys

archive = Path(sys.argv[1])
repo_root = Path(sys.argv[2]).resolve()
prefix = PurePosixPath("data_science_pipeline_v13_semantic_snapshot")
expected = {
    str(prefix) + "/",
    str(prefix / "FREEZE.json"),
    str(prefix / "LOCAL_RESULT.json"),
    str(prefix / "README.md"),
    str(prefix / "SEMANTIC_CONTRACT.json"),
    str(prefix / "SYNTHETIC_RESOLVED_EVENTS.jsonl"),
    str(prefix / "SYNTHETIC_SEMANTIC_SNAPSHOT.json"),
    str(prefix / "VERIFY_OUTPUT.json"),
    str(prefix / "semantic.py"),
    str(prefix / "test_semantic.py"),
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
    '942462fc6d7c08a2b6cee558e61ddb68dd93f251221b92a04f79c6921fdc2d1c' \
    'LOCAL_RESULT.json' | sha256sum --check
)

echo 'PASS_STAGE08_SEMANTIC_ROLE_SAFE_SOFTWARE_ONLY'
