#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# GitHub's text API may append or normalize trailing whitespace. Base64 is
# whitespace-insensitive, so custody is enforced on the decoded gzip and source.
tr -d '\r\n\t ' < "$ROOT/official_harness.py.gz.b64" | base64 -d > "$ROOT/official_harness.py.gz"
echo "e0dfab2c786fcca38744eadfc1af33fc33cf7748cc42fa179345da8d5beb9254  $ROOT/official_harness.py.gz" | sha256sum -c -
gzip -dc "$ROOT/official_harness.py.gz" > "$ROOT/official_harness.py"
echo "1371f02e00ea9c3dccf4eba266c7309a0e0631ecac7f0a7a7ee4ec026d907dd2  $ROOT/official_harness.py" | sha256sum -c -
python -m py_compile "$ROOT/official_harness.py"
