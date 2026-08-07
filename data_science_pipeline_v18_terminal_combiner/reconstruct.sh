#!/usr/bin/env bash
set -euo pipefail

component="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:-$component/runtime}"
archive="${TMPDIR:-/tmp}/data-science-v18-terminal-combiner.zip"

mkdir -p "$out"
cat "$component"/transport/part_*.b64 | tr -d '\r\n\t ' | base64 --decode > "$archive"
printf '%s  %s\n' '7d9778fd641d81c2f9e9d80dcf09493f55fe581b9cbc42961fd02ed7d9be24b5' "$archive" | sha256sum --check

python3 - "$archive" "$out" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys
archive=Path(sys.argv[1]); out=Path(sys.argv[2])
expected={
 'COMBINED_RESULT.json','COMBINER_CONTRACT.json','FREEZE.json',
 'LANE_E_CANONICAL_RECEIPT.json','LANE_E_CANONICAL_SUBJECT.json',
 'LANE_E_EXACT_RECEIPT_ATTACHMENT_ENVELOPE.json','LANE_E_TERMINAL_EXTERNAL_RECEIPT.json',
 'LANE_M_CANONICAL_RECEIPT.json','LANE_M_SIGNATURE_SUBJECT.json','LANE_M_TERMINAL_EXTERNAL_RECEIPT.json',
 'LOCAL_RESULT.json','PACKAGE_MANIFEST.json','README.md','RELATIONSHIP_TERMINAL.json','SOURCE_NATIVE_EVENTS.jsonl',
 'combine.py','test_combine.py','verify.py'
}
with ZipFile(archive) as z:
    names=z.namelist()
    if len(names)!=len(set(names)) or set(names)!=expected:
        raise SystemExit(f'unexpected ZIP members: {sorted(set(names)^expected)}')
    for name in names:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or len(p.parts)!=1:
            raise SystemExit(f'unsafe ZIP member: {name}')
    z.extractall(out)
PY

python3 -m compileall -q "$out"
(
  cd "$out"
  python3 -m unittest -v test_combine.py
  python3 verify.py --output replay.json
  cmp LOCAL_RESULT.json replay.json
)

echo PASS_LANE_V_TERMINAL_COMBINED_SOURCE_NATIVE_SOFTWARE_ONLY
