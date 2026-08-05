#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for pair in \
  '04bb3d042c22c72ec34de81528452ba6b7d8d97e3ba06a7fc9ec83848802c400 part_00.b64' \
  'e287fcb0edbe0ba4197bda2754f518052cf9b1ab778ecde6a7a3b8a71a808c43 part_01.b64' \
  '4d5d905417f7ca28c4a886f668e8e7196f3655559468dbdf8504ad5f17f81117 part_02.b64'; do
  set -- $pair
  echo "$1  $ROOT/regression_transport/$2" | sha256sum -c -
done
cat "$ROOT"/regression_transport/part_*.b64 > "$ROOT/regression_harness.py.gz.b64"
echo 'e34669f3ad4c84c90691f68a88b1032c640015fdcecc745858c033a591c97a7b  '"$ROOT"'/regression_harness.py.gz.b64' | sha256sum -c -
base64 -d "$ROOT/regression_harness.py.gz.b64" > "$ROOT/regression_harness.py.gz"
echo 'e89552a585b49566dc18cfde2b90a00c67f03365a52b3a5775a2fef1fd3427c5  '"$ROOT"'/regression_harness.py.gz' | sha256sum -c -
gzip -dc "$ROOT/regression_harness.py.gz" > "$ROOT/regression_harness.py"
echo 'a1091f40903fda29cbe330f29ac9d4e4365935a6e75eca429a2c4a3086699e14  '"$ROOT"'/regression_harness.py' | sha256sum -c -
python -m py_compile "$ROOT/regression_harness.py"
