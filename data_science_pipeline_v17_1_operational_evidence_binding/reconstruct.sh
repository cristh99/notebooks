#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${1:-$HERE/capsule.zip}"

python3 - "$HERE" "$OUTPUT" <<'PY'
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

here = Path(sys.argv[1])
output = Path(sys.argv[2])
manifest = json.loads((here / 'TRANSPORT_MANIFEST.json').read_text())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()

chunks: list[str] = []
for record in manifest['parts']:
    path = here / record['path']
    raw = path.read_bytes()
    if len(raw) != record['file_bytes']:
        raise SystemExit(f'part byte length mismatch: {record["path"]}')
    if sha256(raw) != record['sha256']:
        raise SystemExit(f'part SHA-256 mismatch: {record["path"]}')
    if git_blob(raw) != record['git_blob_sha1']:
        raise SystemExit(f'part Git blob mismatch: {record["path"]}')
    text = ''.join(raw.decode('ascii').split())
    if len(text) != record['payload_chars']:
        raise SystemExit(f'part payload length mismatch: {record["path"]}')
    chunks.append(text)

encoded = ''.join(chunks)
archive = manifest['canonical_archive']
if len(encoded) != archive['base64_payload_chars']:
    raise SystemExit('total Base64 payload length mismatch')
data = base64.b64decode(encoded, validate=True)
if len(data) != archive['size_bytes']:
    raise SystemExit('decoded archive size mismatch')
if sha256(data) != archive['sha256']:
    raise SystemExit('decoded archive SHA-256 mismatch')
if git_blob(data) != archive['git_blob_sha1']:
    raise SystemExit('decoded archive Git blob mismatch')

expected = {row['path']: row for row in manifest['archive_members']}
with zipfile.ZipFile(io.BytesIO(data)) as zf:
    names = sorted(zf.namelist())
    if names != sorted(expected):
        raise SystemExit('ZIP member set mismatch')
    for name in names:
        payload = zf.read(name)
        row = expected[name]
        if len(payload) != row['bytes'] or sha256(payload) != row['sha256']:
            raise SystemExit(f'ZIP member integrity mismatch: {name}')

output.parent.mkdir(parents=True, exist_ok=True)
fd, temp_name = tempfile.mkstemp(prefix=f'.{output.name}.', suffix='.tmp', dir=output.parent)
try:
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_name, output)
finally:
    if os.path.exists(temp_name):
        os.unlink(temp_name)

print(json.dumps({
    'archive': str(output),
    'size_bytes': len(data),
    'sha256': sha256(data),
    'git_blob_sha1': git_blob(data),
    'parts_verified': len(manifest['parts']),
    'members_verified': len(expected),
    'verification_receipt_sha256': manifest['verification_binding']['receipt_sha256'],
    'stage08_unblocked': manifest['stage08_unblocked'],
}, sort_keys=True))
PY
