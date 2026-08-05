#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo 'fc9718ecf8a2165c8428404a0de04a4b77c4871068754d5e11eddd833dc0524b  '"$ROOT"'/source_part_00.txt' | sha256sum -c -
echo '8d2fa67d41ab683c9f6a1d96b0f1ffcd2dc7ca1fa20978d9520a9e99b9facad6  '"$ROOT"'/source_part_01.txt' | sha256sum -c -
echo '1428e1a6cd1ccd9c09cd98a97505f2e9853e9635466e89a565f4f15e15db8bd4  '"$ROOT"'/source_part_02.txt' | sha256sum -c -
cat "$ROOT/source_part_00.txt" "$ROOT/source_part_01.txt" "$ROOT/source_part_02.txt" > "$ROOT/bookreview_engine.py"
echo 'f539ea1d8e7434ade8b8333054ba40d10a69f6e4c430e784ea321ccafde06414  '"$ROOT"'/bookreview_engine.py' | sha256sum -c -
echo '70603c0e07ad8698f659fc42709f812ab0eb68daeca2b4da18f2b3b9cb32a95a  '"$ROOT"'/test_bookreview_engine.py' | sha256sum -c -
python -m py_compile "$ROOT/bookreview_engine.py" "$ROOT/test_bookreview_engine.py"
