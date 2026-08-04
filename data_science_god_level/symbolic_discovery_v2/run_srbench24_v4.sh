#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
import json
from pathlib import Path
root = Path('data_science_god_level/symbolic_discovery_v2')
auth = json.loads((root / 'SRBENCH24_RETRY3_AUTHORIZATION.json').read_text())
assert all(run['actual_external_evaluation_count'] == 0 for run in auth['prior_runs'])
assert auth['candidate']['changed_after_prior_runs'] is False
assert auth['candidate']['sha256'] == '4e80f120c08581d10497e916a86464062df157d99ec6215ad6f7bfd1b7ea557d'
assert auth['repair']['source_commit'] == 'dc3f6daa93bf10955df8775256a6f8644f38fd93'
assert auth['repair']['train_fraction'] == 0.75
assert auth['repair']['test_fraction'] == 0.25
for field in (
    'candidate_changed', 'dataset_selection_changed', 'dataset_bytes_changed',
    'metrics_changed', 'thresholds_changed', 'baselines_changed',
    'random_seed_function_changed',
):
    assert auth['repair'][field] is False
assert auth['authorization']['one_external_evaluation_authorized'] is True
PY

bash data_science_god_level/symbolic_discovery_v2/run_srbench24_v3.sh
