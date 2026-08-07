#!/usr/bin/env bash
set -euo pipefail

component="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
archive="${TMPDIR:-/tmp}/data-science-v17-cross-source-role-safe-canary.zip"
work="$(mktemp -d)"
trap 'rm -rf "$work" "$archive"' EXIT

python3 - "$component" "$archive" <<'PY'
from pathlib import Path
import base64, hashlib, sys
component = Path(sys.argv[1])
archive = Path(sys.argv[2])
parts = sorted((component / 'transport').glob('part_*.b64'))
expected_parts = [
 '3b4ebe8b067b167db9b8991bd515a83ee70ea2c59c8e11ebc97e71a786ded2e5',
 '7b19ef85ef96d33189bd844826fca7a97c1033bc85ba9ba757be980f3286c4ec',
 'abc04d784051cc3028e26c9b674f55c563aa3116585fe2acf2bdd8429f16bcbe',
 '4b6c166036e2d2e8933e56ddb7b90e52aac78a708bb03a79e98cfcb288385022',
 'ba72e7d056a6bac2e8a1ee67ddb33934b9d285f9cb97bd2ce923e50df783c4b1',
 'ec217c765bf77fd8aedbf14b0d58e27c3d451268f4a4c80a68100d91af6dfb51',
]
if len(parts) != len(expected_parts):
    raise SystemExit(f'expected 6 transport parts, got {len(parts)}')
chunks=[]
for path, expected in zip(parts, expected_parts):
    text=''.join(path.read_text().split())
    actual=hashlib.sha256(text.encode()).hexdigest()
    if actual != expected:
        raise SystemExit(f'part hash mismatch: {path.name}: {actual}')
    chunks.append(text)
data=base64.b64decode(''.join(chunks), validate=True)
if len(data) != 16605:
    raise SystemExit(f'decoded size mismatch: {len(data)}')
sha256=hashlib.sha256(data).hexdigest()
if sha256 != '2fe3645c5791b0e1c22b057c7138f17c8c6145ceee45a9ce28e435a56042b5c5':
    raise SystemExit(f'decoded SHA-256 mismatch: {sha256}')
git_blob=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
if git_blob != '234e2ba16d7cf7ed032ee27cf14038ec9b6aaba0':
    raise SystemExit(f'decoded Git blob mismatch: {git_blob}')
archive.write_bytes(data)
PY

python3 - "$archive" "$work" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import sys
archive=Path(sys.argv[1]); out=Path(sys.argv[2])
prefix='data_science_pipeline_v17_cross_source_role_safe_canary/'
expected={
 prefix+'FREEZE.json', prefix+'LANE_E_RECEIPT.json', prefix+'LANE_M_RECEIPT.json',
 prefix+'MANIFEST.json', prefix+'PROTOCOL.json', prefix+'PUBLIC_RECEIPT.json',
 prefix+'README.md', prefix+'SELECTION_RECEIPT.json', prefix+'TEST_RESULT.json',
 prefix+'VERIFY_OUTPUT.json', prefix+'canary.py', prefix+'test_canary.py', prefix+'verify.py'
}
with ZipFile(archive) as zf:
    names=zf.namelist()
    if len(names)!=len(set(names)) or set(names)!=expected:
        raise SystemExit('unexpected or duplicate ZIP member')
    for name in names:
        member=PurePosixPath(name)
        if member.is_absolute() or '..' in member.parts:
            raise SystemExit(f'unsafe ZIP member: {name}')
    zf.extractall(out)
PY

extracted="$work/data_science_pipeline_v17_cross_source_role_safe_canary"
(
  cd "$extracted"
  python3 -m unittest -v test_canary.py
  python3 verify.py
)

echo 'PASS_CROSS_SOURCE_ROLE_SEPARATION_CANARY_BLOCKED_OPERATIONAL_FIELDS'
