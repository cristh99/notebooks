#!/usr/bin/env bash
set -euo pipefail

root='data_science_dominance/tabarena_portfolio_v2'
logs='dominance-v2-logs'
mkdir -p "$logs" _logic_power_v10

sha256sum -c <<'SUMS'
b94c3005dd5b6e7479749a68cdb33c01328e5f459914c65372da17ca8ab19262  data_science_dominance/tabarena_portfolio_v2/SOURCE_MANIFEST_V2.json
6963697866a9aa1de8ae85db741d8dac3900372d5893f926c8d135829325b13d  data_science_dominance/tabarena_portfolio_v2/TRANSPORT_RETRY_AUTHORIZATION.json
d983e654b103467598b262ebde2a4a28405f0a36a66b05ca0e8614c4c4c6a58a  data_science_dominance/tabarena_portfolio_v2/parts/part_00.b64
442b6c7c4b53f4ee3b4bf25003e8640f5143cdc2928e33e7a930b42cdaabb85e  data_science_dominance/tabarena_portfolio_v2/parts/part_01.b64
fdaf455d4f782690cfcd066eec262fcf347323e37fcee805f26834e2389108c8  data_science_dominance/tabarena_portfolio_v2/parts/part_02.b64
cccea75b4b58192154a3ef6a6fe20d50fe0201a6f9f8c13e432fc23aadaafcef  data_science_dominance/tabarena_portfolio_v2/parts/part_03.b64
62afec7f47eb062c624fbcaa0e71ea68157a215404e545c623126a16f7404665  data_science_dominance/tabarena_portfolio_v2/parts/part_04.b64
4cd7d89c69cdcdd6f2928d7f4b71c42bcc1ba12c61514e3e089ec526b5367409  data_science_dominance/tabarena_portfolio_v2/parts/part_05.b64
3e0beb027364b7ea0d2edf8035430561b0d1519613e5af170ec8ce5a255c73f3  data_science_dominance/tabarena_portfolio_v2/parts/part_06.b64
8ed04927ca39d66dadfa313fcb76a03a09ea51a4173b1bf6c268d2975f9a31ea  data_science_dominance/tabarena_portfolio_v2/parts/part_07.b64
656d4a5a1e01b11ffaac0963909ada24ecc0ddaa3b406acecb5c0e862cc75cae  data_science_dominance/tabarena_portfolio_v2/parts/part_08.b64
6b0e275b6e60ec766ba5d8d19c27234c252bbcae22a3f7df6d0e3908f81e1c90  data_science_god_level/tabular_transfer/estimator.py
SUMS

cat "$root"/parts/part_*.b64 > /tmp/tabarena-portfolio-v2.b64
base64 -d /tmp/tabarena-portfolio-v2.b64 > /tmp/tabarena-portfolio-v2.tar.gz
echo 'd5c24947607d2401fdac3a5b5f936ac6f061990ac3e92dcd9b1f8844e48fe447  /tmp/tabarena-portfolio-v2.tar.gz' | sha256sum -c -
tar xzf /tmp/tabarena-portfolio-v2.tar.gz -C "$root"

sha256sum -c <<'SUMS'
57cdade9e4b71250b36b50ae6aaeba3c786a939a8f66ebc2e2daf41f8414b78b  data_science_dominance/tabarena_portfolio_v2/README.md
5555b5ccbaa7ba538c872fb40eac8c7a8176f1a9f7ce3be229a5a3bc8a1ab1c4  data_science_dominance/tabarena_portfolio_v2/dominance_v2.py
d6d10217da1642f68e269b7d36ce8cf801286ed4bb3f1be61851cdd126fe9dad  data_science_dominance/tabarena_portfolio_v2/logic_plan_v2.py
5ce2c48a6fbba72c2eb988bc208068af607f452090fdfd42a8b0d99cb1da1c60  data_science_dominance/tabarena_portfolio_v2/runner_v2.py
1499963d09fe1d38b19599601d017f4dbdd2875405d76a5cfe4da98d3e39bb84  data_science_dominance/tabarena_portfolio_v2/tasks_v2.json
f2424271df9862f0ca940ac92bd938e1def90b6d9232968529e942b13c81362a  data_science_dominance/tabarena_portfolio_v2/test_portfolio_v2.py
69ed84f034352d93fb50b503e353040bbe5d9480057e93b53a6ea3200ee79207  data_science_dominance/tabarena_portfolio_v2/unit-tests.txt
SUMS

python -m py_compile "$root"/{dominance_v2,logic_plan_v2,runner_v2,test_portfolio_v2}.py
python - <<'PY'
import ast, hashlib, json
from pathlib import Path
root = Path('data_science_dominance/tabarena_portfolio_v2')
manifest = json.loads((root / 'SOURCE_MANIFEST_V2.json').read_text())
retry = json.loads((root / 'TRANSPORT_RETRY_AUTHORIZATION.json').read_text())
tasks = json.loads((root / 'tasks_v2.json').read_text())
assert manifest['score_before'] == 465 and manifest['novelty_weight'] == 0
assert manifest['benchmark']['selection_frozen_before_task_values'] is True
assert manifest['candidate_contract']['test_label_access'] is False
assert manifest['candidate_contract']['dataset_identifier_access'] is False
assert manifest['candidate_contract']['post_hoc_retuning_permitted'] is False
assert manifest['selector']['minimum_anchor_weight'] == 0.55
assert retry['invalid_run']['actual_external_evaluation_count'] == 0
assert retry['invalid_run']['external_task_values_accessed'] is False
assert retry['candidate']['changed_after_invalid_run'] is False
assert retry['protocol']['task_selection_changed'] is False
assert retry['protocol']['evaluation_gates_changed'] is False
assert retry['transport']['repair_changes_source_semantics'] is False
assert retry['authorization']['one_external_evaluation_authorized'] is True
assert len(tasks['tasks']) == 12
assert sum(row['problem_type'] == 'regression' for row in tasks['tasks']) == 6
assert len({row['task_id'] for row in tasks['tasks']}) == 12
source = (root / 'dominance_v2.py').read_text()
tree = ast.parse(source)
imports, calls, names = set(), set(), set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imports.update(alias.name.split('.')[0] for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.level == 0:
        imports.add((node.module or '').split('.')[0])
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name): calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute): calls.add(node.func.attr)
    elif isinstance(node, ast.Name): names.add(node.id)
    elif isinstance(node, ast.Attribute): names.add(node.attr)
assert not imports.intersection({'openml', 'requests', 'socket', 'subprocess', 'urllib'})
assert not calls.intersection({'open', 'eval', 'exec', 'compile', 'system', 'popen', 'run', 'urlopen', 'request', 'read_csv', 'read_json'})
assert not names.intersection({'y_test', 'test_labels', 'dataset_name', 'task_id', 'openml'})
assert 'ANCHOR_WEIGHT_FLOOR = 0.55' in source
assert 'small = n_samples < 2_000' in source
audit = {
    'schema': 'data-science-dominance/tabarena-robust-static-audit/2',
    'candidate_task_values_accessed': False,
    'candidate_test_labels_access': False,
    'candidate_dataset_identifier_access': False,
    'candidate_network_or_process_access': False,
    'fixed_local_legacy_module_loading_only': True,
    'fresh_task_contract_count': 12,
    'minimum_anchor_weight': 0.55,
    'prior_invalid_external_evaluation_count': 0,
    'source_manifest_sha256': hashlib.sha256((root / 'SOURCE_MANIFEST_V2.json').read_bytes()).hexdigest(),
    'retry_authorization_sha256': hashlib.sha256((root / 'TRANSPORT_RETRY_AUTHORIZATION.json').read_bytes()).hexdigest(),
    'candidate_sha256': hashlib.sha256((root / 'dominance_v2.py').read_bytes()).hexdigest(),
    'legacy_estimator_sha256': hashlib.sha256(Path('data_science_god_level/tabular_transfer/estimator.py').read_bytes()).hexdigest(),
}
Path('dominance-v2-logs/static-audit.json').write_text(json.dumps(audit, indent=2, sort_keys=True) + '\n')
print(json.dumps(audit, indent=2, sort_keys=True))
PY

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
(cd "$root" && PYTHONPATH="${GITHUB_WORKSPACE}/_logic_power_v10" python logic_plan_v2.py) 2>&1 | tee "$logs/logic-plan-output.txt"
(cd "$root" && PYTHONPATH="${GITHUB_WORKSPACE}/$root" python -m unittest -v test_portfolio_v2.py) 2>&1 | tee "$logs/unit-tests.txt"

python - <<'PY'
import json, time
from pathlib import Path
import numpy as np
from tabicl import TabICLClassifier, TabICLRegressor
rng = np.random.default_rng(20260805)
X = rng.normal(size=(96, 6)).astype('float32')
y_cls = (X[:, 0] + X[:, 1] > 0).astype(int)
y_reg = X[:, 0] - 2 * X[:, 1] + 0.1 * rng.normal(size=len(X))
started = time.perf_counter()
clf = TabICLClassifier(n_estimators=1, batch_size=1, device='cpu', n_jobs=4, random_state=7, verbose=False)
clf.fit(X[:72], y_cls[:72]); cls = clf.predict_proba(X[72:])
reg = TabICLRegressor(n_estimators=1, batch_size=1, device='cpu', n_jobs=4, random_state=7, verbose=False)
reg.fit(X[:72], y_reg[:72]); pred = reg.predict(X[72:])
assert cls.shape == (24, 2) and np.all(np.isfinite(cls))
assert pred.shape == (24,) and np.all(np.isfinite(pred))
receipt = {
    'schema': 'data-science-dominance/tabiclv2-smoke/2',
    'classification_checkpoint_loaded': True,
    'regression_checkpoint_loaded': True,
    'external_task_values_accessed': False,
    'runtime_seconds': time.perf_counter() - started,
}
Path('dominance-v2-logs/tabiclv2-smoke.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
print(json.dumps(receipt, indent=2, sort_keys=True))
PY

set +e
PYTHONPATH="${GITHUB_WORKSPACE}/$root" python "$root/runner_v2.py" \
    --output "$logs/robust-fresh12-report.json" 2>&1 | tee "$logs/runner-output.txt"
status=${PIPESTATUS[0]}
echo "$status" > "$logs/runner-exit-status.txt"
exit 0
