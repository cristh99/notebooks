#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for pair in \
  'e96b6387c33bdb5abe5414d36181818b9d4e63c02e057474af2847ef723f6c1e candidate_part_00.b64' \
  '8cb422929f59eb0c9f95220c222f5b455563590f573e741681fe17096086eb1d candidate_part_01.b64' \
  'd3ef9869fe25d607dfafd3d3ec83d335fd7b48cb559c2f5526d68c601be76f96 candidate_part_02.b64' \
  '7da606f16942e12794c3eac090dfd537b27d9c08ed65d6535317de64715eb2a7 candidate_part_03.b64' \
  'ffb6fe9f5230b6c841a4ea73c92e7408950b9819623b2578bcc13a7f8ff34102 tests.b64'; do
  set -- $pair
  echo "$1  $ROOT/transport/$2" | sha256sum -c -
done
cat "$ROOT"/transport/candidate_part_*.b64 > "$ROOT/candidate.py.gz.b64"
echo 'b8e08a0c6444ce0a3be735074bfd4c13828e6623ea98406ef175e8c8346dcc1d  '"$ROOT"'/candidate.py.gz.b64' | sha256sum -c -
base64 -d "$ROOT/candidate.py.gz.b64" > "$ROOT/candidate.py.gz"
base64 -d "$ROOT/transport/tests.b64" > "$ROOT/tests.py.gz"
echo '641f65069ba66fe984e16669022315f1f0f48384168a1c90b27376c47f5889f3  '"$ROOT"'/candidate.py.gz' | sha256sum -c -
echo '3c2d663e9f77df5b5ee17cf527a747a74d7a7fb5e81d40c7cbe35ad60f27c12c  '"$ROOT"'/tests.py.gz' | sha256sum -c -
gzip -dc "$ROOT/candidate.py.gz" > "$ROOT/usaspending_fresh_engine.py"
gzip -dc "$ROOT/tests.py.gz" > "$ROOT/test_usaspending_fresh_engine.py"
echo 'fbd9fcb87f03471f843b659a00a21dbd424adb4e53faba1ce0501b094a99e07e  '"$ROOT"'/usaspending_fresh_engine.py' | sha256sum -c -
echo '1fe7d0c6399ef4105200aecf576a53b58422de0d8d77e0ba700333a1a8481cdb  '"$ROOT"'/test_usaspending_fresh_engine.py' | sha256sum -c -
python -m py_compile "$ROOT/usaspending_fresh_engine.py" "$ROOT/test_usaspending_fresh_engine.py"
