#!/usr/bin/env bash
set -euo pipefail

source_id="${1:?source id required}"
output="source-fingerprint-${source_id}"

python -m ocr_real_risk_v1.openvino_prior_registry_entry_v7 \
  print-spec --source-id "$source_id" > source-spec.json

eval "$(python - <<'PY'
import json, shlex
spec = json.load(open('source-spec.json'))
for key in ('source_url', 'source_sha256', 'rows', 'artifact_id', 'artifact_sha256'):
    print(f"export {key.upper()}={shlex.quote(str(spec[key]))}")
PY
)"

cat source-spec.json

gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/${GITHUB_REPOSITORY}/actions/artifacts/${ARTIFACT_ID}/zip" \
  > terminal-artifact.zip
echo "${ARTIFACT_SHA256}  terminal-artifact.zip" \
  | sha256sum --check --strict
mkdir -p terminal-artifact
unzip -q terminal-artifact.zip -d terminal-artifact

curl --fail --location --retry 8 --retry-all-errors \
  --connect-timeout 30 --speed-limit 1024 --speed-time 300 \
  --max-time 10800 \
  "$SOURCE_URL" --output source.parquet
echo "${SOURCE_SHA256}  source.parquet" | sha256sum --check --strict

python -m ocr_real_risk_v1.openvino_prior_registry_entry_v7 \
  fingerprint-source \
  --source-id "$source_id" \
  --source-file source.parquet \
  --terminal-root terminal-artifact \
  --output-dir "$output" \
  > fingerprint-stdout.json

test "$(wc -l < "$output/physical_records.jsonl")" = "$ROWS"
(cd "$output" && sha256sum --check --strict SHA256SUMS.txt)
rm -f source.parquet terminal-artifact.zip fingerprint-stdout.json
rm -rf terminal-artifact
printf '%s\n' "$output"
