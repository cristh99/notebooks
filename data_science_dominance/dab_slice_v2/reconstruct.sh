#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
encoded="$root/agent.py.gz.b64"
gzip_file="/tmp/dab_slice_agent.py.gz"
output="$root/dab_slice_agent.py"
echo 'e50bcbdf4316f26606766cee3a5afc60e34dcdcd8a11093ad77936b217144bb2  '"$encoded" | sha256sum -c -
base64 -d "$encoded" > "$gzip_file"
echo '3f3438e9b9a01dcddd01f37cbf5bd2a09490fec86cb335ef1cc99d00ef8b6b2b  '"$gzip_file" | sha256sum -c -
gzip -dc "$gzip_file" > "$output"
echo '0796f1d66d944e832181034f6e8e8800461b60d71e66716d5b19fe3fd1957dec  '"$output" | sha256sum -c -
python -m py_compile "$output"
