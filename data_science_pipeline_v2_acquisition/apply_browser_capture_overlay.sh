#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERLAY="$ROOT/browser_capture_overlay"
TARGET="${1:?usage: apply_browser_capture_overlay.sh <materialized-v2-root>}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

check() {
  local digest="$1" path="$2"
  printf '%s  %s\n' "$digest" "$path" | sha256sum -c -
}

check bd23e380db9610095f7fc3fd38d4c65d0168c421fc989fb14534c5d09115276b "$OVERLAY/part_00.b64"
check 9f9cb3d8901445039919c1de0de250f9cd07f2b1238b32a20eb5141fc1a10bb3 "$OVERLAY/part_01.b64"
cat "$OVERLAY/part_00.b64" "$OVERLAY/part_01.b64" > "$TMP/browser-overlay.b64"
check e0723066c37d62181536ae8be0c20eb06d6145cef601cc6e65bb7a4f168e64ae "$TMP/browser-overlay.b64"
base64 -d "$TMP/browser-overlay.b64" > "$TMP/browser-overlay.tar.gz"
check 21be4eb3d4d73cb763806bb2f1bb7bb68c18926b9a4099054a409fcb03353197 "$TMP/browser-overlay.tar.gz"

test -d "$TARGET/src/god_pipeline"
tar xzf "$TMP/browser-overlay.tar.gz" -C "$TARGET"

check 60fd85515aaa5aa4d82e373cc7d9a6df3d70b680aba5797a4ebd067937e84469 "$TARGET/src/god_pipeline/browser_capture.py"
check a4f32c01191bef22d429f02b388843bbc8522e08d8cb5880f2c0a0fbb6ad47d7 "$TARGET/src/god_pipeline/browser_canary.py"
check 0d1beda49651d1b72e654e21693443aae5147b19e370725e11777a0597db7972 "$TARGET/src/god_pipeline/__init__.py"
check 025e3b31f2618722d1236b7e138063555ebfe466dbbef3c571e3e1861daf3d0b "$TARGET/src/god_pipeline/cli.py"
check 557e92c17a28d51efc054764bf24cd76b6691eb269c5b01c39411e9de1b3b79a "$TARGET/tests/test_browser_capture.py"
check 1f99b08e3b2bed9b47aaf84a5eb2d24d5c2aa4764b5e006b42da808ecf749711 "$TARGET/canary/iaip-ip-348-browser-capture.json"
check 3fe3702c7f735ee7414c9a0437ae0f11108c5a63dd41618165bbb082ea820a69 "$TARGET/README.md"
check 4685b1e83c485e15668bb4577469f88d51f382e72799ec23a84651c7f342fec7 "$TARGET/BROWSER_CAPTURE.md"
check c68556a7811d87b6843341b45fe4c33ff56643130e88f78ae7c14bf0c3dbeb64 "$TARGET/CHANGE_REVIEW_BROWSER_CAPTURE.md"
check 02f48da73706d41bc42c912ac3f4ffe19e37b77113d5e4e102ed83ce0935e20b "$TARGET/pyproject.toml"

echo "Applied browser-capture overlay to: $TARGET"
echo "Overlay SHA-256: 21be4eb3d4d73cb763806bb2f1bb7bb68c18926b9a4099054a409fcb03353197"
