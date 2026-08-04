#!/usr/bin/env bash
set -euo pipefail

root='data_science_god_level/symbolic_discovery_v2'
mkdir -p srbench24-data srbench24-cache srbench24-logs _logic_power_v10 /tmp/symbolic-v2-source

# Reconstruct the exact frozen candidate.
echo 'b2a2f9604165f60b869d41c8913442f4d1f52598f746d213247970fa8380bd06  data_science_god_level/symbolic_discovery_v2/symbolic_v2_code.tar.gz.b64' | sha256sum -c -
base64 -d "$root/symbolic_v2_code.tar.gz.b64" > /tmp/symbolic-v2-source.tar.gz
echo '103e282beb5a59898b4be34334e8449e572271b20063029b47dda1267e72bd0f  /tmp/symbolic-v2-source.tar.gz' | sha256sum -c -
tar xzf /tmp/symbolic-v2-source.tar.gz -C /tmp/symbolic-v2-source
candidate="$(find /tmp/symbolic-v2-source -type f -name estimator.py -print -quit)"
test -n "$candidate"
cp -f "$(dirname "$candidate")"/* "$root"/
echo '4e80f120c08581d10497e916a86464062df157d99ec6215ad6f7bfd1b7ea557d  data_science_god_level/symbolic_discovery_v2/estimator.py' | sha256sum -c -

# Prove the two preceding failures performed zero evaluations and did not change the candidate.
python - <<'PY'
import json
from pathlib import Path
root = Path('data_science_god_level/symbolic_discovery_v2')
first = json.loads((root / 'SRBENCH24_RETRY_AUTHORIZATION.json').read_text())
second = json.loads((root / 'SRBENCH24_RETRY2_AUTHORIZATION.json').read_text())
assert first['prior_run']['actual_external_evaluation_count'] == 0
assert all(run['actual_external_evaluation_count'] == 0 for run in second['prior_runs'])
assert second['candidate']['changed_after_prior_runs'] is False
assert second['candidate']['sha256'] == '4e80f120c08581d10497e916a86464062df157d99ec6215ad6f7bfd1b7ea557d'
for field in (
    'candidate_changed', 'dataset_selection_changed', 'dataset_bytes_changed',
    'metrics_changed', 'thresholds_changed', 'baselines_changed',
    'split_randomization_changed', 'split_ratio_changed',
):
    assert second['repair'][field] is False
assert second['authorization']['one_external_evaluation_authorized'] is True
PY

python -m py_compile \
  "$root/estimator.py" \
  "$root/srbench24_runner.py" \
  "$root/srbench24_small_runner.py" \
  "$root/srbench24_data.py" \
  "$root/srbench24_plan.py" \
  "$root/test_srbench24.py" \
  "$root/srbench24_ci.py"
sha256sum "$root/srbench24_small_runner.py" > srbench24-logs/small-runner.sha256
python "$root/srbench24_ci.py" preflight --code-root "$root" --logs-dir srbench24-logs

# Replay original Logic Power v10 and all pre-data tests.
cat logic_power_v10_capsule/parts/part_00.b64 \
    logic_power_v10_capsule/parts/part_01.b64 \
    logic_power_v10_capsule/parts/part_02.b64 \
    logic_power_v10_capsule/parts/part_03.b64 \
    logic_power_v10_capsule/parts/part_04.b64 \
    logic_power_v10_capsule/parts/part_05_00.b64 \
    logic_power_v10_capsule/parts/part_05_01.b64 \
    logic_power_v10_capsule/parts/part_05_02.b64 > /tmp/lp.b64
echo '3548f31fcaa9696eabb063023c905fbb04a2b3db73c96df9f9ee8bc8e0c64fc1  /tmp/lp.b64' | sha256sum -c -
base64 -d /tmp/lp.b64 > /tmp/lp.tar.gz
echo 'ad2c363afb3fe20aa093565f278c690d423611e8270e9ad9b1491dbbdf218c31  /tmp/lp.tar.gz' | sha256sum -c -
tar xzf /tmp/lp.tar.gz -C _logic_power_v10
(cd _logic_power_v10 && sha256sum -c SOURCE_SHA256SUMS && test "$(cat PRIVATE_HEAD_SHA.txt)" = 'ba10d0edc7eb20d499d0481fda2537e782b6efb2')
(cd "$root" && PYTHONPATH="${GITHUB_WORKSPACE}/_logic_power_v10" python srbench24_plan.py) \
  2>&1 | tee srbench24-logs/logic-plan-output.txt
(cd "$root" && PYTHONPATH="${GITHUB_WORKSPACE}/$root" python -m unittest -v test_estimator.py test_srbench24.py) \
  2>&1 | tee srbench24-logs/unit-tests.txt

# Acquire every pinned dataset before importing the candidate for evaluation.
PYTHONPATH="${GITHUB_WORKSPACE}/$root" python "$root/srbench24_data.py" \
  --data-root srbench24-data \
  --cache-root srbench24-cache \
  --manifest srbench24-logs/data-manifest.json \
  2>&1 | tee srbench24-logs/data-download-output.txt
test "$(find srbench24-data -maxdepth 1 -type f -name '*.npz' | wc -l)" -eq 24
test "$(find srbench24-cache -maxdepth 1 -type f -name '*.tsv.gz' | wc -l)" -eq 24

# First and only actual external evaluation.
PYTHONPATH="${GITHUB_WORKSPACE}/$root" python "$root/srbench24_small_runner.py" \
  --data-root srbench24-data \
  --output srbench24-logs/srbench24-report.json \
  2>&1 | tee srbench24-logs/runner-output.txt
