#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSPORT="$ROOT/transport"
STRICT_JSON_PATCH="$ROOT/strict_json.patch"
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
check d24323dc2483ac1623c8a0175a71edb7bdfc291f5f130a268f26e991b1ee31de "$STRICT_JSON_PATCH"

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
PIPELINE="$OUT/canonical_data_science_pipeline_v1"

check 4efedb65453bf316b1161fd8a8885f6a245fcd01ae719285efe9bbdfc5925ec6 "$PIPELINE/src/god_pipeline/models.py"
check 02235b0783921d5a64d57635f0c5a4298859d6688946b79686aa0043de56376f "$PIPELINE/src/god_pipeline/ledger.py"
check 7f4c14e5d7e5dbc594e5b4bc15919fbeedb0a008f365cb96f88fcbf944fb4a60 "$PIPELINE/src/god_pipeline/stages.py"
check e368a79a7a0140589a366b99cb77a176d81be58d68c669faa388a5da38ec0470 "$PIPELINE/src/god_pipeline/orchestrator.py"
check 8049a616b270770ff75b0aae845292d78bbd9d11c69cc37893f1f3cd4d29b60c "$PIPELINE/src/god_pipeline/cli.py"
check fd780e74c692f685762a7c9f8f1225322556eb02bdc2b1ebaf751009eeac5d0f "$PIPELINE/tests/test_pipeline.py"

patch --batch --forward --fuzz=0 -p1 -d "$PIPELINE" < "$STRICT_JSON_PATCH"

check ea976df1d5d963dd6f6cc0405c0549f82ddda913e1d21653b4db9e59f3504c88 "$PIPELINE/src/god_pipeline/models.py"
check 1b335dc5ff03837a29ca8aa835b552f895789d5a7857680f429c2640ce25bdbf "$PIPELINE/src/god_pipeline/ledger.py"
check 740f8566507e05c77faefaf2a4a38cfc15eeeebbfe7ca7f05091f6057d38b636 "$PIPELINE/src/god_pipeline/stages.py"
check f38f530c8c83bb878fc53095e72831da84d698d272d8e154f1adb2be381ca586 "$PIPELINE/src/god_pipeline/orchestrator.py"
check 16a940a9561c78ce5355dc810dc134f28d6690b3d4bc8723e3d08030a2105148 "$PIPELINE/src/god_pipeline/cli.py"
check 864ddc473fbc14ba919d95dd00d095fbc034a3242bfb0dbb286916c176526d2f "$PIPELINE/tests/test_pipeline.py"

echo "Materialized: $PIPELINE"
echo "Bundle SHA-256: d2116de142fc94daaa833b949daadbc3ff7052c6c8e421348d49aa7d5022ea3f"
echo "Strict JSON patch SHA-256: d24323dc2483ac1623c8a0175a71edb7bdfc291f5f130a268f26e991b1ee31de"
