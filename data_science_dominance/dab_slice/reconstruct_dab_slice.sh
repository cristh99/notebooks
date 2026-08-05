#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARTS="$ROOT/transport_gz"
OUT="$ROOT/dab_slice_agent.py"
TMP_B64="$(mktemp)"
TMP_GZ="$(mktemp)"
trap 'rm -f "$TMP_B64" "$TMP_GZ"' EXIT

echo '8b063a0afa3d7526f0e6f4207916aec49b95f092f03107247540218f9e508493  '"$PARTS"'/part_00.b64' | sha256sum -c -
echo '1674cf45d58af056d313fcfb2d81efcea85938c6af08e7a17d154086772b9878  '"$PARTS"'/part_01.b64' | sha256sum -c -
echo 'b8424b6221b7729bce893dc98f2a1d680e0479076f772c69749cfefc8dcb60b4  '"$PARTS"'/part_02.b64' | sha256sum -c -
cat "$PARTS"/part_*.b64 > "$TMP_B64"
echo '7918803dffc7f698f2dab39c584f2253d3e6f1aeaf992b3a6b1eb577f05258a8  '"$TMP_B64" | sha256sum -c -
base64 -d "$TMP_B64" > "$TMP_GZ"
echo '1b825b9879b34541763a5ea89a8f1e6c6d0405ac07e31416a806a8bc1b87c49d  '"$TMP_GZ" | sha256sum -c -
gzip -dc "$TMP_GZ" > "$OUT"
echo '8ad0fbfa88c5ca62afd0110c249f72c097bc8bb938978092f9f3c5e178c6fd1e  '"$OUT" | sha256sum -c -
python -m py_compile "$OUT"
echo "Reconstructed $OUT"
