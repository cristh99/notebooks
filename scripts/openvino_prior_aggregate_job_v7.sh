#!/usr/bin/env bash
set -euo pipefail

bundle_root="${1:-prior-source-bundles}"
output="${2:-prior-registry}"

mapfile -t roots < <(find "$bundle_root" -mindepth 1 -maxdepth 1 -type d | sort)
test "${#roots[@]}" = 13

python -m ocr_real_risk_v1.openvino_prior_registry_entry_v7 \
  aggregate "${roots[@]}" \
  --output-dir "$output" \
  > aggregate-build.json
python -m ocr_real_risk_v1.openvino_prior_registry_entry_v7 \
  verify "$output" \
  > aggregate-replay.json
(cd "$output" && sha256sum --check --strict SHA256SUMS.txt)

OUTPUT_DIR="$output" python - <<'PY'
import json
import os
from pathlib import Path
registry = json.load(open(Path(os.environ['OUTPUT_DIR']) / 'prior_registry.json'))
assert registry['complete'] is True
assert registry['population_rows'] == 38601
assert registry['openvino_scientific_images_opened'] == 0
assert registry['annotation_columns_read'] is False
assert registry['ocr_runs'] == 0
print(json.dumps({
    'registry_stable': registry['stable_payload_sha256'],
    'population_rows': registry['population_rows'],
    'unique_encoded': registry['unique_encoded_sha256'],
    'unique_pixels': registry['unique_pixel_sha256'],
    'cross_corpus_groups': registry['cross_corpus_duplicate_groups'],
}, sort_keys=True))
PY

rm -f aggregate-build.json aggregate-replay.json
