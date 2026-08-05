#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "1f61afee55616d36242f7debe568c9f235fcc4cb7d0a2b6f8d2501c08cfe16f6  $ROOT/candidate.py.gz.b64" | sha256sum -c -
echo "0e7b36c53997f8001598ea5f8b98f33f8bce0407602aa7c58a87e4045702b808  $ROOT/tests.py.gz.b64" | sha256sum -c -
base64 -d "$ROOT/candidate.py.gz.b64" > "$ROOT/candidate.py.gz"
base64 -d "$ROOT/tests.py.gz.b64" > "$ROOT/tests.py.gz"
echo "8d66f74f24994b6b0be8afcf6122c947b4e0896705a899d8858b13d14818a61e  $ROOT/candidate.py.gz" | sha256sum -c -
echo "fdb72af20edc2c79630374af81864a6c4069298323b2b236272196512a1e29df  $ROOT/tests.py.gz" | sha256sum -c -
gzip -dc "$ROOT/candidate.py.gz" > "$ROOT/usaspending_fresh_engine.py"
gzip -dc "$ROOT/tests.py.gz" > "$ROOT/test_usaspending_fresh_engine.py"
echo "76d240d4f4bb1ed5a87f32c18ae92e7629b971f761577eb16d2b5deccf57ef8f  $ROOT/usaspending_fresh_engine.py" | sha256sum -c -
echo "24513a312047f3537d41b00d5bc599e81a49a178c1501c70eff762dd6dd2174c  $ROOT/test_usaspending_fresh_engine.py" | sha256sum -c -
python -m py_compile "$ROOT/usaspending_fresh_engine.py" "$ROOT/test_usaspending_fresh_engine.py"
