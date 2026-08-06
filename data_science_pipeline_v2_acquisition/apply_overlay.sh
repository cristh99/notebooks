#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERLAY="$ROOT/overlay"
DNS_PIN_PATCH="$ROOT/dns_pin.patch"
TARGET="${1:?usage: apply_overlay.sh <materialized-v1-root>}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

check() {
  local digest="$1" path="$2"
  printf '%s  %s\n' "$digest" "$path" | sha256sum -c -
}

check ccea5809defa92381c16416a0129cfc325358820d7a95444e278209f94d2c587 "$OVERLAY/part_00.b64"
check fa62172d5790aad598fc5322f2f2c0736171438dcdc77a0b5ebdfb076a5e587b "$OVERLAY/part_01.b64"
cat "$OVERLAY/part_00.b64" "$OVERLAY/part_01.b64" > "$TMP/overlay.b64"
check 228671b4feb0389bf2f488ebae86d9d445225975acda1f88f8bc9cb1bdd0073e "$TMP/overlay.b64"
base64 -d "$TMP/overlay.b64" > "$TMP/overlay.tar.gz"
check 11da5eea97bf3e2e8febdebba8109cbbd4d01d21de26d44356c20024602f3b23 "$TMP/overlay.tar.gz"
check 360cc0fcaa33322233bb3ccb05dd3e2e55fd614194855fe6393fdc22c03aa42b "$DNS_PIN_PATCH"

test -d "$TARGET/src/god_pipeline"
tar xzf "$TMP/overlay.tar.gz" -C "$TARGET"

check 66bf6cebba06ac9c11e189759201d45dba64a7a98b2d265639c4c65e77da3a57 "$TARGET/src/god_pipeline/acquisition.py"
check 62f7ba0f848c2e51412408e497797ee71d865e04daeea9f870027bd61989dae1 "$TARGET/tests/test_acquisition.py"
patch --batch --forward --fuzz=0 -p1 -d "$TARGET" < "$DNS_PIN_PATCH"
check 761e89f99031d2bc305259d55b6dd8e35cadce94ae16e71b056b73a977ba024c "$TARGET/src/god_pipeline/acquisition.py"
check 33619abe33a4b3908281c6ffad47e30abd6775bca159e6c8448c1415fd7deec7 "$TARGET/tests/test_acquisition.py"

check 2808bb6e0fab48433d4c8d8ca811d0cd919072b9130936d317fdff062c5448b5 "$TARGET/src/god_pipeline/canary.py"
check 80d63dc1e19ad185861ea1b3ef0ac0f581b292d446270d3ced3d4c0309e552fb "$TARGET/src/god_pipeline/__init__.py"
check 45c8d7d1cc28fefa17a45db713303f11ed67fed45e7f4f8690cbe53886e3995e "$TARGET/src/god_pipeline/cli.py"
check cd38bb067c95dfd7993dd6692907af32b04f58cc7699a1fce055b5ff3bd3f73d "$TARGET/pyproject.toml"
check 63fde0184580b93886694ee6dedffa7e2c7c8a3be66c4e4cf861ad3817e58109 "$TARGET/README.md"
check e581ac5cd19b6fc275e1000e11506de2924e1cd7cd8d24ac9ce52f0f927393c5 "$TARGET/canary/oncae-2025-md5.json"
check 4b3bec32bb662c0514df09761b734d02050c6a9173c72383715435ce35c949ec "$TARGET/canary/iaip-portal-home.json"

echo "Applied acquisition v2 overlay to: $TARGET"
echo "Overlay SHA-256: 11da5eea97bf3e2e8febdebba8109cbbd4d01d21de26d44356c20024602f3b23"
echo "DNS pin patch SHA-256: 360cc0fcaa33322233bb3ccb05dd3e2e55fd614194855fe6393fdc22c03aa42b"
