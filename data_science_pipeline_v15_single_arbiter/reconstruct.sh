#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-.}"
component="$repo_root/data_science_pipeline_v15_single_arbiter"
archive="${TMPDIR:-/tmp}/data-science-v15-single-arbiter.zip"

cat "$component"/transport/part_*.b64 | base64 --decode > "$archive"
printf '%s  %s\n' \
  'ab51a786a4f284b88747af76ca8090791c071ba6a92b17135c3d94ff549d85ba' \
  "$archive" | sha256sum --check

python3 - "$archive" "$repo_root" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys

archive = Path(sys.argv[1])
repo_root = Path(sys.argv[2]).resolve()
prefix = PurePosixPath("data_science_pipeline_v15_single_arbiter")
expected = {
    str(prefix / "ARBITER_CONTRACT.json"),
    str(prefix / "ARBITER_RESULT.json"),
    str(prefix / "ARBITRATED_EVENTS.jsonl"),
    str(prefix / "FREEZE.json"),
    str(prefix / "LOCAL_RESULT.json"),
    str(prefix / "README.md"),
    str(prefix / "SYNTHETIC_AMOUNT_DATE_RECEIPT.json"),
    str(prefix / "SYNTHETIC_ENTITY_PROVIDER_RECEIPT.json"),
    str(prefix / "arbiter.py"),
    str(prefix / "test_arbiter.py"),
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
    '6e5137461b00f81a2c6aeb71662ff75aaa485a893b38d022d242821bab917a62' \
    'LOCAL_RESULT.json' | sha256sum --check
)

echo 'PASS_STAGE07_SINGLE_ARBITER_SOFTWARE_ONLY'
