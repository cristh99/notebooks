#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARTS="$ROOT/transport_gz"
OUT="$ROOT/dab_slice_agent.py"
TMP_B64="$(mktemp)"
TMP_GZ="$(mktemp)"
trap 'rm -f "$TMP_B64" "$TMP_GZ"' EXIT

echo '97f3781fac1f91ccb5987657a2121fe6fdfb1e4c00b980fc99bddb2051be7d0a  '"$PARTS"'/part_00.b64' | sha256sum -c -
echo '792c0a56583f31a86b6449236052cfa89e4f0a60fd762249e71f5100ee1e865e  '"$PARTS"'/part_01.b64' | sha256sum -c -
echo '2c62d0ee046d134cc4094a0a0ba83853a343309e0a11612952e93e7dc5647515  '"$PARTS"'/part_02.b64' | sha256sum -c -
cat "$PARTS"/part_*.b64 > "$TMP_B64"
echo '3ac7eb11748b0e8899c4aac1d885adbdb8b1854431e9632c42e7f33f5bc1160c  '"$TMP_B64" | sha256sum -c -
base64 -d "$TMP_B64" > "$TMP_GZ"
echo 'a0ad0478d43942078b74f00680d8b0203f1b56c5c0d52fb7ccb7174f67a63ab1  '"$TMP_GZ" | sha256sum -c -
gzip -dc "$TMP_GZ" > "$OUT"
echo '77ad131788a384cf030c2dad0ad7628fac4ad5a30c221f5e7206004a9403d1b2  '"$OUT" | sha256sum -c -
python -m py_compile "$OUT"
echo "Reconstructed $OUT"
