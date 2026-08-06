#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:?usage: install_overlay.sh <materialized-pipeline-root>}"

test -d "$TARGET/src/god_pipeline"
install -m 0644 "$ROOT/src/god_pipeline/ensemble_extract.py" "$TARGET/src/god_pipeline/ensemble_extract.py"
install -m 0644 "$ROOT/src/god_pipeline/ensemble_canary.py" "$TARGET/src/god_pipeline/ensemble_canary.py"
install -m 0644 "$ROOT/tests/test_ensemble_extract.py" "$TARGET/tests/test_ensemble_extract.py"

PYTHONPATH="$TARGET/src" python -m py_compile \
  "$TARGET/src/god_pipeline/ensemble_extract.py" \
  "$TARGET/src/god_pipeline/ensemble_canary.py" \
  "$TARGET/tests/test_ensemble_extract.py"

echo "Installed OCR ensemble v8 overlay into: $TARGET"
