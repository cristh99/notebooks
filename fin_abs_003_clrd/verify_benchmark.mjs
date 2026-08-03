#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [reportPath, outputPath] = process.argv.slice(2);
if (![reportPath, outputPath].every(Boolean)) {
  console.error('usage: verify_benchmark.mjs <report> <output>');
  process.exit(2);
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const shaText = value => crypto.createHash('sha256').update(value, 'utf8').digest('hex');
const shaFile = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const close = (a, b, tolerance = 1e-9) => Math.abs(Number(a) - Number(b)) <= tolerance * Math.max(1, Math.abs(Number(a)), Math.abs(Number(b)));
const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const root = path.dirname(reportPath);
const rowsPath = path.join(root, payload.sealed_test?.verification_rows_file ?? '');
const errors = [];

if (payload.schema !== 'fin-abs-003/clrd-sealed-benchmark/1') errors.push('schema');
if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push('report-hash');
try {
  if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) errors.push('canonical-payload');
} catch {
  errors.push('canonical-json');
}
if (!fs.existsSync(rowsPath)) errors.push('verification-rows-file');
else if (shaFile(rowsPath) !== payload.sealed_test?.verification_rows_sha256) errors.push('verification-rows-sha');
if (canonical(payload.absolute_score) !== canonical({
  before: 423,
  after: 423,
  delta: 0,
  boundary: 'No absolute points are awarded until a separate implementation reconstructs predictions and all non-compensable gates pass.',
})) errors.push('score-boundary');
if (payload.independent_prediction_reimplementation !== 'PENDING') errors.push('independent-boundary');

const rows = fs.existsSync(rowsPath)
  ? fs.readFileSync(rowsPath, 'utf8').trim().split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line))
  : [];

function quantile(values, probability) {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  const position = (ordered.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return ordered[lower];
  const weight = position - lower;
  return ordered[lower] * (1 - weight) + ordered[upper] * weight;
}

function metric(group) {
  const actual = group.map(row => Number(row.actual_reserve));
  const predicted = group.map(row => Number(row.prediction));
  const errorsLocal = predicted.map((value, index) => value - actual[index]);
  const denominator = actual.reduce((sum, value) => sum + value, 0);
  const calibration = denominator > 0 ? predicted.reduce((sum, value) => sum + value, 0) / denominator : null;
  const ape = errorsLocal.flatMap((value, index) => actual[index] > 0 ? [Math.abs(value) / actual[index]] : []);
  const lobWape = {};
  const cutoffWape = {};
  for (const key of [...new Set(group.map(row => row.LOB))].sort()) {
    const selected = group.filter(row => row.LOB === key);
    const denom = selected.reduce((sum, row) => sum + Number(row.actual_reserve), 0);
    lobWape[key] = denom > 0 ? selected.reduce((sum, row) => sum + Math.abs(Number(row.prediction) - Number(row.actual_reserve)), 0) / denom : null;
  }
  for (const key of [...new Set(group.map(row => String(row.cutoff)))].sort()) {
    const selected = group.filter(row => String(row.cutoff) === key);
    const denom = selected.reduce((sum, row) => sum + Number(row.actual_reserve), 0);
    cutoffWape[key] = denom > 0 ? selected.reduce((sum, row) => sum + Math.abs(Number(row.prediction) - Number(row.actual_reserve)), 0) / denom : null;
  }
  return {
    cases: group.length,
    actual_total: denominator,
    predicted_total: predicted.reduce((sum, value) => sum + value, 0),
    wape: denominator > 0 ? errorsLocal.reduce((sum, value) => sum + Math.abs(value), 0) / denominator : null,
    calibration_ratio: calibration,
    calibration_error: calibration === null ? null : Math.abs(calibration - 1),
    median_ape: quantile(ape, 0.5),
    p95_ape: quantile(ape, 0.95),
    under_reserving_frequency: predicted.filter((value, index) => value < actual[index]).length / group.length,
    aggregate_under_reserve: predicted.reduce((sum, value, index) => sum + Math.max(actual[index] - value, 0), 0),
    lob_wape: lobWape,
    cutoff_wape: cutoffWape,
  };
}

function allMetrics(split) {
  const selected = rows.filter(row => row.split === split);
  const output = {};
  for (const method of [...new Set(selected.map(row => row.method))].sort()) {
    output[method] = metric(selected.filter(row => row.method === method));
  }
  return output;
}

function selectionKey(name, metrics) {
  return [Number(metrics.wape), Number(metrics.calibration_error), Number(metrics.p95_ape), name];
}
function compareKeys(left, right) {
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}
function select(metrics, methods) {
  return [...methods].sort((a, b) => compareKeys(selectionKey(a, metrics[a]), selectionKey(b, metrics[b])))[0];
}

function lcgIndices(seed, count, modulus) {
  let state = seed >>> 0;
  const output = [];
  for (let index = 0; index < count; index += 1) {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0;
    output.push(state % modulus);
  }
  return output;
}

function entityBootstrap(testRows, baseline, challenger, replicates = 5000) {
  const selected = testRows.filter(row => row.method === baseline || row.method === challenger);
  const byEntity = new Map();
  for (const row of selected) {
    if (!byEntity.has(row.GRCODE)) byEntity.set(row.GRCODE, new Map());
    const cases = byEntity.get(row.GRCODE);
    if (!cases.has(row.case_id)) cases.set(row.case_id, {actual: Number(row.actual_reserve)});
    cases.get(row.case_id)[row.method] = Number(row.prediction);
  }
  const improvements = [];
  for (const entity of [...byEntity.keys()].sort()) {
    const cases = [...byEntity.get(entity).values()].filter(item => Number.isFinite(item[baseline]) && Number.isFinite(item[challenger]));
    const denominator = cases.reduce((sum, item) => sum + item.actual, 0);
    if (denominator <= 0) continue;
    const base = cases.reduce((sum, item) => sum + Math.abs(item[baseline] - item.actual), 0) / denominator;
    const chall = cases.reduce((sum, item) => sum + Math.abs(item[challenger] - item.actual), 0) / denominator;
    improvements.push(base - chall);
  }
  if (!improvements.length) return {entities:0, mean_improvement:null, lower_95:null, upper_95:null, replicates:0, seed:20260803};
  const indices = lcgIndices(20260803, replicates * improvements.length, improvements.length);
  const means = [];
  let cursor = 0;
  for (let replicate = 0; replicate < replicates; replicate += 1) {
    let total = 0;
    for (let index = 0; index < improvements.length; index += 1) total += improvements[indices[cursor++]];
    means.push(total / improvements.length);
  }
  means.sort((a, b) => a - b);
  return {
    entities: improvements.length,
    mean_improvement: improvements.reduce((a, b) => a + b, 0) / improvements.length,
    lower_95: means[Math.floor(0.025 * (replicates - 1))],
    upper_95: means[Math.ceil(0.975 * (replicates - 1))],
    replicates,
    seed: 20260803,
  };
}

function deepClose(left, right, location) {
  if (left === null || right === null) {
    if (left !== right) errors.push(location);
    return;
  }
  if (typeof left === 'number' || typeof right === 'number') {
    if (!close(left, right)) errors.push(location);
    return;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) { errors.push(location); return; }
    left.forEach((value, index) => deepClose(value, right[index], `${location}[${index}]`));
    return;
  }
  if (typeof left === 'object' && typeof right === 'object') {
    const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
    for (const key of keys) {
      if (!(key in left) || !(key in right)) errors.push(`${location}.${key}`);
      else deepClose(left[key], right[key], `${location}.${key}`);
    }
    return;
  }
  if (left !== right) errors.push(location);
}

const validation = allMetrics('validation');
const test = allMetrics('test');
const baselines = payload.protocol?.baselines ?? [];
const challengers = payload.protocol?.challengers ?? [];
const selectedBaseline = select(validation, baselines);
const selectedChallenger = select(validation, challengers);
if (selectedBaseline !== payload.validation?.selected_baseline) errors.push('selected-baseline');
if (selectedChallenger !== payload.validation?.selected_challenger) errors.push('selected-challenger');
deepClose(validation, payload.validation?.metrics ?? {}, 'validation-metrics');
deepClose(test[selectedBaseline], payload.sealed_test?.baseline?.metrics, 'test-baseline');
deepClose(test[selectedChallenger], payload.sealed_test?.challenger?.metrics, 'test-challenger');
const bootstrap = entityBootstrap(rows.filter(row => row.split === 'test'), selectedBaseline, selectedChallenger);
deepClose(bootstrap, payload.sealed_test?.entity_bootstrap, 'bootstrap');

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema: 'fin-abs-003/clrd-node-metric-receipt/1',
  valid: uniqueErrors.length === 0,
  errors: uniqueErrors,
  report_sha256: report.sha256,
  verification_rows_sha256: fs.existsSync(rowsPath) ? shaFile(rowsPath) : null,
  selected_baseline: selectedBaseline,
  selected_challenger: selectedChallenger,
  performance_candidate_pass: payload.performance_candidate_pass ?? false,
  independent_prediction_reimplementation: payload.independent_prediction_reimplementation ?? null,
  absolute_score: payload.absolute_score ?? null,
};
const receipt = {payload: receiptPayload, sha256: shaText(canonical(receiptPayload))};
fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
