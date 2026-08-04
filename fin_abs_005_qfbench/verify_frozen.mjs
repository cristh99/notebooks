#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [reportPath, outputsPath, solversPath, outputPath] = process.argv.slice(2);
if (![reportPath, outputsPath, solversPath, outputPath].every(Boolean)) {
  console.error(
    'usage: verify_frozen.mjs <freeze-report> <outputs> <solvers> <receipt>'
  );
  process.exit(2);
}

const TASKS = [
  'structured-note-risk',
  'swap-curve-bootstrap-ois',
  'double-sort',
  'bs-greeks-pde',
  'kelly-var-sizing',
];
const EXPECTED = {
  'structured-note-risk': ['results.json', 'solution.json'],
  'swap-curve-bootstrap-ois': [
    'ois_discount_curve.csv',
    'libor_forward_curve.csv',
    'repriced_quotes.csv',
    'swap_valuation.json',
    'summary.json',
  ],
  'double-sort': ['strategy_returns.csv'],
  'bs-greeks-pde': [
    'calibration.json',
    'greeks_surface.csv',
    'pde_verification.csv',
    'summary.json',
  ],
  'kelly-var-sizing': ['results.json', 'solution.json'],
};
const SOLVERS = {
  'structured-note-risk': 'structured_note_risk.py',
  'swap-curve-bootstrap-ois': 'swap_curve_bootstrap_ois.py',
  'double-sort': 'double_sort.py',
  'bs-greeks-pde': 'bs_greeks_pde.py',
  'kelly-var-sizing': 'kelly_var_sizing.py',
};

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value)
      .sort()
      .map(key => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}
const shaText = value =>
  crypto.createHash('sha256').update(value, 'utf8').digest('hex');
const shaFile = file =>
  crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

function finiteJson(value) {
  if (value === null || ['string', 'boolean'].includes(typeof value)) return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(finiteJson);
  if (typeof value === 'object') return Object.values(value).every(finiteJson);
  return false;
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const errors = [];
if (payload.schema !== 'fin-abs-005/qfbench-frozen-solutions/1') {
  errors.push('schema');
}
if (shaText(report.payload_canonical ?? '') !== report.sha256) {
  errors.push('report-hash');
}
try {
  if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) {
    errors.push('canonical-payload');
  }
} catch {
  errors.push('canonical-json');
}
if (payload.status !== 'FROZEN_BEFORE_HIDDEN_VERIFIER') errors.push('status');
if (canonical(payload.tasks) !== canonical(TASKS)) errors.push('tasks');

const outputManifest = [];
for (const task of TASKS) {
  const root = path.join(outputsPath, task);
  if (!fs.existsSync(root)) {
    errors.push(`output-directory-${task}`);
    continue;
  }
  const actual = fs
    .readdirSync(root, {withFileTypes: true})
    .filter(entry => entry.isFile())
    .map(entry => entry.name)
    .sort();
  if (canonical(actual) !== canonical([...EXPECTED[task]].sort())) {
    errors.push(`output-files-${task}`);
  }
  for (const name of EXPECTED[task]) {
    const file = path.join(root, name);
    if (!fs.existsSync(file) || fs.statSync(file).size <= 0) {
      errors.push(`output-missing-${task}-${name}`);
      continue;
    }
    if (name.endsWith('.json')) {
      try {
        if (!finiteJson(JSON.parse(fs.readFileSync(file, 'utf8')))) {
          errors.push(`output-nonfinite-${task}-${name}`);
        }
      } catch {
        errors.push(`output-json-${task}-${name}`);
      }
    }
    outputManifest.push({
      task_id: task,
      path: `${task}/${name}`,
      bytes: fs.statSync(file).size,
      sha256: shaFile(file),
    });
  }
}
outputManifest.sort((left, right) => {
  const leftKey = `${left.task_id}|${left.path}`;
  const rightKey = `${right.task_id}|${right.path}`;
  return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
});
if (canonical(payload.output_manifest) !== canonical(outputManifest)) {
  errors.push('output-manifest');
}
if (payload.output_manifest_sha256 !== shaText(canonical(outputManifest))) {
  errors.push('output-manifest-sha');
}

const solverManifest = TASKS.map(task => {
  const file = path.join(solversPath, SOLVERS[task]);
  return {
    task_id: task,
    path: SOLVERS[task],
    bytes: fs.existsSync(file) ? fs.statSync(file).size : 0,
    sha256: fs.existsSync(file) ? shaFile(file) : null,
  };
}).sort((left, right) =>
  left.task_id < right.task_id ? -1 : left.task_id > right.task_id ? 1 : 0
);
if (canonical(payload.solver_manifest) !== canonical(solverManifest)) {
  errors.push('solver-manifest');
}
if (payload.solver_manifest_sha256 !== shaText(canonical(solverManifest))) {
  errors.push('solver-manifest-sha');
}
const gates = payload.gate_checks ?? {};
if (!Object.keys(gates).length || !Object.values(gates).every(Boolean)) {
  errors.push('gates');
}
if (
  canonical(payload.absolute_score) !==
  canonical({before: 423, after: 423, delta: 0})
) {
  errors.push('score-boundary');
}

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema: 'fin-abs-005/qfbench-frozen-node-receipt/1',
  valid: uniqueErrors.length === 0,
  errors: uniqueErrors,
  freeze_report_sha256: report.sha256 ?? null,
  output_manifest_sha256: shaText(canonical(outputManifest)),
  solver_manifest_sha256: shaText(canonical(solverManifest)),
  absolute_score: payload.absolute_score ?? null,
};
const receipt = {
  payload: receiptPayload,
  sha256: shaText(canonical(receiptPayload)),
};
fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
