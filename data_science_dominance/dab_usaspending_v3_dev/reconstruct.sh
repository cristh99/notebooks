#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for pair in \
  '1501ab0c2e767682579cfc00fcb8bad4e30e7f6bb82c20870b83460d27d43462 candidate_part_00.b64' \
  '85e9d417492d02e703797c87f1eaf951c623124c2723ede00823c6e4156ac023 candidate_part_01.b64' \
  'e5f10569d852b5e31307fdffcc7a027322e78b33aec890af1c2990d4927c4f99 candidate_part_02.b64' \
  '8bd6a451e341a755aaa17516cd29e47b6365b3be2b68f34c25a484abe67af1f6 candidate_part_03.b64' \
  'ac4a0d5b0fbda116098d19d6ea9ffd8bf1ddce60f4f5d25e2d82a90879525620 candidate_part_04.b64' \
  '2da228aac97fa8d03d7d3ebba7ae7c30f72335f08e31aa48ff3b54190c088ac4 candidate_part_05.b64' \
  'c4b7038fbbb03081a86bc472bae69883ae9224d77748d10ca0650f57447d280c candidate_part_06.b64' \
  'c6b70f39cfb0cbd44c59eeb6c177138c2b1f018dc0b46e80c2ebf639b72c369f candidate_part_07.b64'; do
  set -- $pair
  echo "$1  $ROOT/transport_exact/$2" | sha256sum -c -
done
echo 'ffb6fe9f5230b6c841a4ea73c92e7408950b9819623b2578bcc13a7f8ff34102  '"$ROOT"'/transport/tests.b64' | sha256sum -c -
cat "$ROOT"/transport_exact/candidate_part_*.b64 > "$ROOT/candidate.py.gz.b64"
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
