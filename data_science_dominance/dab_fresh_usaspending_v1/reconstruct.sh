#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "af616c4e761b225592cf2833cadecbbee684955295c5d23dfa1b7e1b15021d37  $ROOT/candidate.py.gz.b64" | sha256sum -c -
echo "9bbe5ff71f71dfe1432cbdf18c11d7860624ebde6e96ea7f612dafd439376d1f  $ROOT/tests.py.gz.b64" | sha256sum -c -
base64 -d "$ROOT/candidate.py.gz.b64" > "$ROOT/candidate.py.gz"
base64 -d "$ROOT/tests.py.gz.b64" > "$ROOT/tests.py.gz"
echo "bf506972123ddd3c63ca0186aede3faf72d0c404eed74a4b6f7826bf5c258078  $ROOT/candidate.py.gz" | sha256sum -c -
echo "332ec324ce4bbb451e90f4a55201aeffbcd8a792bdc797dfc328d69e9be9ac5e  $ROOT/tests.py.gz" | sha256sum -c -
gzip -dc "$ROOT/candidate.py.gz" > "$ROOT/usaspending_fresh_engine.py"
gzip -dc "$ROOT/tests.py.gz" > "$ROOT/test_usaspending_fresh_engine.py"
echo "a0afa1d615b138e46d588401d6c228ad8dd5992033abfc3486b30e2aff633976  $ROOT/usaspending_fresh_engine.py" | sha256sum -c -
echo "3dd9caadd54e208c92053e98c46e2068c11abc0d553d2d5f7f0d24fbe2c4f37a  $ROOT/test_usaspending_fresh_engine.py" | sha256sum -c -
python -m py_compile "$ROOT/usaspending_fresh_engine.py" "$ROOT/test_usaspending_fresh_engine.py"
