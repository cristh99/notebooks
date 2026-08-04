#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [reportPath, sourcePath, outputPath] = process.argv.slice(2);
if (![reportPath, sourcePath, outputPath].every(Boolean)) {
  console.error('usage: verify_audit.mjs <report> <source> <output>');
  process.exit(2);
}

const COMMIT = 'd2fc28b3492f2d73d192fa7eabadf150a19a62fb';
const SEED = 'FIN-ABS-005-QFBENCH-CALIBRATION-V1';
const TASKS = [
  'structured-note-risk',
  'swap-curve-bootstrap-ois',
  'double-sort',
  'bs-greeks-pde',
  'kelly-var-sizing',
];
const SELECTION_SHA =
  'ece4ec97f61fa1e0c3422498024207734aaa167b90d5587944b436672da79474';

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

function listFiles(root, current = root) {
  const output = [];
  for (const entry of fs.readdirSync(current, {withFileTypes: true})) {
    if (entry.name === '.git') continue;
    const absolute = path.join(current, entry.name);
    if (entry.isDirectory()) output.push(...listFiles(root, absolute));
    else if (entry.isFile()) output.push(absolute);
  }
  return output.sort((left, right) =>
    path.relative(root, left).localeCompare(path.relative(root, right))
  );
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const errors = [];

if (payload.schema !== 'fin-abs-005/qfbench-blind-audit/1') {
  errors.push('schema');
}
if (typeof report.payload_canonical !== 'string') {
  errors.push('payload-canonical-shape');
} else {
  if (shaText(report.payload_canonical) !== report.sha256) {
    errors.push('payload-hash');
  }
  try {
    if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) {
      errors.push('payload-canonical-mismatch');
    }
  } catch {
    errors.push('payload-canonical-json');
  }
}

if (payload.source?.repository !== 'QF-Bench/QuantitativeFinance-Bench') {
  errors.push('source-repository');
}
if (payload.source?.commit !== COMMIT || payload.source?.observed_commit !== COMMIT) {
  errors.push('source-commit');
}
if (payload.selection?.seed !== SEED) errors.push('selection-seed');
if (canonical(payload.selection?.tasks) !== canonical(TASKS)) {
  errors.push('selection-tasks');
}
const selection = {seed: SEED, source_commit: COMMIT, tasks: TASKS};
if (shaText(canonical(selection)) !== SELECTION_SHA) {
  errors.push('verifier-selection-contract');
}
if (payload.selection?.sha256 !== SELECTION_SHA) {
  errors.push('selection-sha');
}

const files = listFiles(sourcePath);
const manifest = files.map(file => ({
  path: path.relative(sourcePath, file).split(path.sep).join('/'),
  bytes: fs.statSync(file).size,
  sha256: shaFile(file),
}));
if (payload.workspace?.file_count !== files.length) errors.push('file-count');
if (canonical(payload.workspace?.file_manifest) !== canonical(manifest)) {
  errors.push('file-manifest');
}
if (payload.workspace?.file_manifest_sha256 !== shaText(canonical(manifest))) {
  errors.push('file-manifest-sha');
}

const relative = manifest.map(item => item.path);
const forbidden = relative.filter(
  name =>
    `/${name}`.includes('/solution/') || `/${name}`.includes('/tests/')
);
if (forbidden.length) errors.push('forbidden-path-present');
if (canonical(payload.workspace?.forbidden_paths) !== canonical(forbidden)) {
  errors.push('forbidden-path-report');
}
if ((payload.workspace?.missing_paths ?? []).length !== 0) {
  errors.push('missing-path-report');
}
if (!relative.includes('README.md')) errors.push('root-readme');
if (!relative.includes('LICENSE')) errors.push('root-license');

const reportTasks = payload.tasks ?? [];
if (reportTasks.length !== TASKS.length) errors.push('task-count');
for (const task of TASKS) {
  const prefix = `tasks/${task}/`;
  const instruction = `${prefix}instruction.md`;
  const metadata = `${prefix}task.toml`;
  const environment = relative.filter(name =>
    name.startsWith(`${prefix}environment/`)
  );
  if (!relative.includes(instruction)) errors.push(`instruction-${task}`);
  if (!relative.includes(metadata)) errors.push(`task-toml-${task}`);
  if (!environment.length) errors.push(`environment-${task}`);
  const item = reportTasks.find(value => value.task_id === task);
  if (!item) {
    errors.push(`task-report-${task}`);
    continue;
  }
  const instructionRow = manifest.find(value => value.path === instruction);
  const metadataRow = manifest.find(value => value.path === metadata);
  if (item.instruction_sha256 !== instructionRow?.sha256) {
    errors.push(`instruction-sha-${task}`);
  }
  if (item.task_toml_sha256 !== metadataRow?.sha256) {
    errors.push(`task-toml-sha-${task}`);
  }
  if (item.environment_file_count !== environment.length) {
    errors.push(`environment-count-${task}`);
  }
  const expectedEnvironment = manifest.filter(value =>
    value.path.startsWith(`${prefix}environment/`)
  );
  if (canonical(item.environment_manifest) !== canonical(expectedEnvironment)) {
    errors.push(`environment-manifest-${task}`);
  }
}

const gates = payload.gate_checks ?? {};
if (!Object.keys(gates).length || !Object.values(gates).every(Boolean)) {
  errors.push('gate-checks');
}
if (payload.status !== 'PASS_BLIND_STAGE0') errors.push('status');
if (
  canonical(payload.absolute_score) !==
  canonical({
    before: 423,
    after: 423,
    delta: 0,
    boundary:
      'Source and anti-leakage audit only; no QFBench task has been solved or scored.',
  })
) {
  errors.push('score-boundary');
}

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema: 'fin-abs-005/qfbench-blind-audit-node-receipt/1',
  valid: uniqueErrors.length === 0,
  errors: uniqueErrors,
  report_sha256: report.sha256 ?? null,
  workspace_manifest_sha256: shaText(canonical(manifest)),
  observed_commit: payload.source?.observed_commit ?? null,
  tasks: TASKS,
  forbidden_paths: forbidden,
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
