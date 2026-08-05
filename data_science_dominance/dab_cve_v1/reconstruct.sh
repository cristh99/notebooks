#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo '0cd95cc95594aa0ea06f7159018a9f88a6de25edd8cfde9b59c6f166c70004bf  '"$ROOT"'/transport/candidate_part_00.b64' | sha256sum -c -
echo 'd784253f98951e61eddec06e3ef7ed5836cdd7e5dccbf50ea5c8d9a0bffd4b47  '"$ROOT"'/transport/candidate_part_01.b64' | sha256sum -c -
echo 'ab0b2be8f63f342d583069bec8eb8923b342f8454b9d7bd3d4a78c1e80028854  '"$ROOT"'/transport/tests.b64' | sha256sum -c -
cat "$ROOT/transport/candidate_part_00.b64" "$ROOT/transport/candidate_part_01.b64" > "$ROOT/cve_engine.py.gz.b64"
echo 'e8e65b79ff3e4a8162f4bf4ce87449936b8765425dbd36d36086b66ca1d9d624  '"$ROOT"'/cve_engine.py.gz.b64' | sha256sum -c -
base64 -d "$ROOT/cve_engine.py.gz.b64" > "$ROOT/cve_engine.py.gz"
base64 -d "$ROOT/transport/tests.b64" > "$ROOT/test_cve_engine.py.gz"
echo '9369bcb380ed38134509f7f7cee5d2c5b9dc696c55215c074c225e14a404ab34  '"$ROOT"'/cve_engine.py.gz' | sha256sum -c -
echo '0ae46d8f65a9dc3792faeac5e054afecb6581b0ad957f9243c25a1908614f54d  '"$ROOT"'/test_cve_engine.py.gz' | sha256sum -c -
gzip -dc "$ROOT/cve_engine.py.gz" > "$ROOT/cve_engine.py"
gzip -dc "$ROOT/test_cve_engine.py.gz" > "$ROOT/test_cve_engine.py"
echo '0ba9dfa4f583a8c5aad5b975b913dbf2ffa5e1ec2f04d6649067e0ab46967cff  '"$ROOT"'/cve_engine.py' | sha256sum -c -
echo '18557756c32cf4aadccdf7a1e5d026ff122b5143eaf6cc3f676d7838f9dbe7bc  '"$ROOT"'/test_cve_engine.py' | sha256sum -c -
python -m py_compile "$ROOT/cve_engine.py" "$ROOT/test_cve_engine.py"
