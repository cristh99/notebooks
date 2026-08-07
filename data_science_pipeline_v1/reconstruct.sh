#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSPORT="$ROOT/transport"
OUT="${1:-$ROOT/materialized}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

check() {
  local digest="$1" path="$2"
  printf '%s  %s\n' "$digest" "$path" | sha256sum -c -
}

check a5b617bcf4afca425e8c19d413791ab1d21d8d0a7db86bf713cdea37f289808c "$TRANSPORT/part_00.b64"
check 57f6db95adb740adeb9a6a3540327de3d8c4ff0bc67bbb0d06b1896edda26909 "$TRANSPORT/part_01.b64"
check 132cc8db2ddafa7417190c0e91c051c817176f05afdc3f76d8e292fe9b1ff270 "$TRANSPORT/part_02_00.b64"
check c4cebd8f490e155e31c06bf4050d7bcaa1c1f8de45bc226e834651b187d27e00 "$TRANSPORT/part_02_01.b64"
check 320c336b11472e158be7f77397742557c6a88c1e049475a750b026b7c3110cc4 "$TRANSPORT/part_02_02.b64"
check 74cbb252f2c0d3e00317c10c1201cf44f00756d09a3b4b7af356362b32b1bbe7 "$TRANSPORT/part_02_03.b64"
check e51f0b592f52f659f68d17b5ea34f6618027eeb7bfb796279fa2373cd95e52f6 "$TRANSPORT/part_03.b64"
check 006ee5f1353066f8e13b3ddf6a8d7906ec65ee4a1e24b7212c54482d3d949f2c "$TRANSPORT/part_04.b64"

cat \
  "$TRANSPORT/part_00.b64" \
  "$TRANSPORT/part_01.b64" \
  "$TRANSPORT/part_02_00.b64" \
  "$TRANSPORT/part_02_01.b64" \
  "$TRANSPORT/part_02_02.b64" \
  "$TRANSPORT/part_02_03.b64" \
  "$TRANSPORT/part_03.b64" \
  "$TRANSPORT/part_04.b64" > "$TMP/bundle.b64"

check 4fffb98811ef04ed72604626800922ed8d52e4bef3cd4222c0487f8276d67453 "$TMP/bundle.b64"
base64 -d "$TMP/bundle.b64" > "$TMP/bundle.zip"
check d2116de142fc94daaa833b949daadbc3ff7052c6c8e421348d49aa7d5022ea3f "$TMP/bundle.zip"

rm -rf "$OUT"
mkdir -p "$OUT"
unzip -q "$TMP/bundle.zip" -d "$OUT"

echo "Materialized: $OUT/canonical_data_science_pipeline_v1"
echo "Bundle SHA-256: d2116de142fc94daaa833b949daadbc3ff7052c6c8e421348d49aa7d5022ea3f"
