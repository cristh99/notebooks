#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for pair in \
  '08db725ae5a8234d105f1044ea5fa88d72cf6a93f3c6a31cb6928857975b0e5a candidate_part_00.b64' \
  '5b2836869f1983e5fd0ff9b3b1d14e68f8ab360fc193b65333e46ba7b7d6aa91 candidate_part_01.b64' \
  '40f2e1b097f862a192448ba1edb2950a56b83a57ee3ca263aa11c35f80435e0c candidate_part_02.b64' \
  '4e595f705df75ff141bdc80a0bc1d0952cb1ed0a1ed1def526a93e454a60cce5 candidate_part_03.b64' \
  '980dfd7be236d9db6cec5a9c666c2230bc7d566c2f435081c0bfb095c938a626 candidate_part_04.b64' \
  'c4fab000b2a646ed56012764021b161b8926f358553914831e3ee9ec279e6d0b candidate_part_05.b64' \
  '8b2e8485d41a4c060460c5319c84c391f14020f511ca8e70f7dcbeaa77abd973 candidate_part_06.b64' \
  '7bd44d35ece8e57972790c03e1a540c58bf6dc8cd68781a2762251c63c951e6e candidate_part_07.b64'; do
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
