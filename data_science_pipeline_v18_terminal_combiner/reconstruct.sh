#!/usr/bin/env bash
set -euo pipefail

component="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:-$component/runtime}"
archive="${TMPDIR:-/tmp}/data-science-v18-1-documentary-quarantine-combiner.zip"
manifest="$component/TRANSPORT_MANIFEST.json"

mkdir -p "$out"
printf '%s  %s\n' '6f2158967971dd8cb90a232dbbb4d855d973e749b6acbbb748e467f3a60f3a22' "$manifest" | sha256sum -c -

python3 - "$component" "$manifest" "$archive" "$out" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import base64
import hashlib
import json
import sys

component, manifest_path, archive, out = map(Path, sys.argv[1:])
raw = manifest_path.read_bytes()
manifest = json.loads(raw)
canonical = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
if raw != canonical:
    raise SystemExit("transport manifest is not canonical JSON")

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def git_blob(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()

transport = component / "transport"
names = manifest["part_order"]
actual_names = sorted(path.name for path in transport.glob("part_*.b64"))
if actual_names != names:
    raise SystemExit(f"transport part set mismatch: {actual_names} != {names}")

chunks = []
for name in names:
    path = transport / name
    data = path.read_bytes()
    expected = manifest["parts"][name]
    if len(data) != expected["bytes"]:
        raise SystemExit(f"transport size mismatch: {name}")
    if sha256(data) != expected["sha256"]:
        raise SystemExit(f"transport SHA-256 mismatch: {name}")
    if git_blob(data) != expected["git_blob_sha1"]:
        raise SystemExit(f"transport Git blob mismatch: {name}")
    chunks.append(data)

encoded = b"".join(chunks)
if len(encoded) != manifest["base64_characters"]:
    raise SystemExit("base64 character count mismatch")
decoded = base64.b64decode(encoded, validate=True)
if len(decoded) != manifest["decoded_bytes"]:
    raise SystemExit("decoded size mismatch")
if sha256(decoded) != manifest["decoded_sha256"]:
    raise SystemExit("decoded SHA-256 mismatch")
if git_blob(decoded) != manifest["decoded_git_blob_sha1"]:
    raise SystemExit("decoded Git blob mismatch")
archive.write_bytes(decoded)

expected = set(manifest["expected_zip_members"])
with ZipFile(archive) as zf:
    zip_names = zf.namelist()
    if len(zip_names) != len(set(zip_names)) or set(zip_names) != expected:
        raise SystemExit(f"unexpected ZIP members: {sorted(set(zip_names) ^ expected)}")
    if len(zip_names) != manifest["expected_zip_member_count"]:
        raise SystemExit("ZIP member count mismatch")
    for name in zip_names:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or len(member.parts) != 1:
            raise SystemExit(f"unsafe ZIP member: {name}")
    zf.extractall(out)
PY

python3 -m compileall -q "$out"
(
  cd "$out"
  python3 -m unittest -v test_combine.py
  python3 verify.py --output replay.json
  cmp LOCAL_RESULT.json replay.json
)

echo 'PASS_LANE_V18_1_DOCUMENTARY_QUARANTINE_COMBINED_SOFTWARE'
