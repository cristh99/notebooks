#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "54868c4faafecf1ae5474f7f7f27193d6250c11aa943c0c2d1db7e307dfb1704  $ROOT/official_harness.py.gz.b64" | sha256sum -c -
base64 -d "$ROOT/official_harness.py.gz.b64" > "$ROOT/official_harness.py.gz"
echo "4454e44111a37c4ee0be4e8f2ad45d33c78bca80658434b946bd9819fd72d94a  $ROOT/official_harness.py.gz" | sha256sum -c -
gzip -dc "$ROOT/official_harness.py.gz" > "$ROOT/official_harness.py"
echo "4893bfa4a24d1385d2f71b4e22676124c533f98a6e24d3bbc45b3d2c30f75412  $ROOT/official_harness.py" | sha256sum -c -
python -m py_compile "$ROOT/official_harness.py"
