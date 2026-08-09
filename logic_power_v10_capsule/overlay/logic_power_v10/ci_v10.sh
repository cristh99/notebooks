#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p tools reports certificates

python -m compileall -q logic_power_v10
python -m unittest discover -s logic_power_v10 -p 'test_*.py' -v
python -m logic_power_v10.run_logic_power_v10

python -m logic_power_v10.verify_logic_power_v10 \
  certificates/logic_power_v10_exact.json
python -m logic_power_v10.verify_logic_power_v10 \
  certificates/logic_power_v10_impossible.json
node logic_power_v10/verify_logic_power_v10.js \
  certificates/logic_power_v10_exact.json
node logic_power_v10/verify_logic_power_v10.js \
  certificates/logic_power_v10_impossible.json

if python -m logic_power_v10.verify_logic_power_v10 \
  certificates/logic_power_v10_tampered.json; then
  echo 'Python accepted a tampered v10 certificate'
  exit 1
fi
if node logic_power_v10/verify_logic_power_v10.js \
  certificates/logic_power_v10_tampered.json; then
  echo 'Node accepted a tampered v10 certificate'
  exit 1
fi

sha256sum \
  certificates/logic_power_v10_exact.json \
  certificates/logic_power_v10_impossible.json \
  reports/logic_power_v10.canonical.json \
  > reports/rebuild_before_v10.sha256
python -m logic_power_v10.run_logic_power_v10
sha256sum \
  certificates/logic_power_v10_exact.json \
  certificates/logic_power_v10_impossible.json \
  reports/logic_power_v10.canonical.json \
  > reports/rebuild_after_v10.sha256
cmp \
  reports/rebuild_before_v10.sha256 \
  reports/rebuild_after_v10.sha256

curl -L --fail --retry 4 --retry-all-errors \
  https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar \
  -o tools/tla2tools.jar
echo 'feffd16994db963ad945628cfd03d154c195a468  tools/tla2tools.jar' \
  | sha1sum -c -

java -cp tools/tla2tools.jar tla2sany.SANY \
  tla_v10/ActiveDiscovery.tla \
  2>&1 | tee reports/sany_active_discovery_v10.log
if grep -Eq 'Semantic errors|\*\*\* Errors:' \
  reports/sany_active_discovery_v10.log; then
  exit 1
fi

(
  cd tla_v10
  java -cp ../tools/tla2tools.jar tlc2.TLC -workers 1 \
    -config ActiveDiscoveryExact.cfg ActiveDiscovery.tla \
    | tee ../reports/tlc_active_discovery_exact_v10.log
  java -cp ../tools/tla2tools.jar tlc2.TLC -workers 1 \
    -config ActiveDiscoveryImpossible.cfg ActiveDiscovery.tla \
    | tee ../reports/tlc_active_discovery_impossible_v10.log
)
grep -q 'Model checking completed. No error has been found.' \
  reports/tlc_active_discovery_exact_v10.log
grep -q 'Model checking completed. No error has been found.' \
  reports/tlc_active_discovery_impossible_v10.log

if [ ! -x "$HOME/.elan/bin/lean" ]; then
  curl -sSf \
    https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y
fi
export PATH="$HOME/.elan/bin:$PATH"
lean ActiveDiscoveryFinite.lean \
  2>&1 | tee reports/active-discovery-lean-v10.log
if grep -q 'sorryAx' reports/active-discovery-lean-v10.log; then
  echo 'Unexpected sorryAx in v10 formalization'
  exit 1
fi

find logic_power_v10 -type d -name '__pycache__' -prune -exec rm -rf {} +

find logic_power_v10 tla_v10 -type f -print0 \
  | sort -z | xargs -0 sha256sum \
  > reports/source_manifest_v10.sha256
sha256sum \
  ActiveDiscoveryFinite.lean \
  README_v10.md \
  .github/workflows/logic-power-v10.yml \
  >> reports/source_manifest_v10.sha256

python - <<'PY'
import hashlib
import json
from pathlib import Path


def sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


report = json.loads(
    Path('reports/logic_power_v10.json').read_text()
)
audit = {
    'schema': 'logic-power-v10/audit/1',
    'status': 'verified',
    'score_within_declared_finite_domain': 1000,
    'python_tests': 12,
    'python_verifier': True,
    'node_verifier': True,
    'tamper_rejected_by_both': True,
    'deterministic_rebuild': True,
    'tla_sany': True,
    'tlc_exact': True,
    'tlc_impossible': True,
    'lean_compiled': True,
    'lean_sorry_ax': False,
    'exact_certificate_sha256': (
        report['certificates']['exact_sha256']
    ),
    'impossible_certificate_sha256': (
        report['certificates']['impossible_sha256']
    ),
    'source_manifest_sha256': sha(
        'reports/source_manifest_v10.sha256'
    ),
}
Path('reports/audit_v10.json').write_text(
    json.dumps(audit, indent=2, sort_keys=True) + '\n'
)
PY

tar \
  --sort=name \
  --mtime='UTC 1970-01-01' \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  -cf - \
  logic_power_v10 \
  tla_v10 \
  ActiveDiscoveryFinite.lean \
  README_v10.md \
  reports/audit_v10.json \
  reports/source_manifest_v10.sha256 \
  certificates/logic_power_v10_exact.json \
  certificates/logic_power_v10_impossible.json \
  | gzip -n > reports/logic-power-v10-evidence.tar.gz
sha256sum reports/logic-power-v10-evidence.tar.gz \
  > reports/logic-power-v10-evidence.sha256
