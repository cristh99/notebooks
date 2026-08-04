#!/usr/bin/env node
import childProcess from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const [reportPath, outputPath] = process.argv.slice(2);
if (![reportPath, outputPath].every(Boolean)) {
  console.error('usage: verify_benchmark_v3.mjs <report> <output>');
  process.exit(2);
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const shaText = text => crypto.createHash('sha256').update(text, 'utf8').digest('hex');
const shaFile = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const close = (left, right, tolerance = 1e-8) => {
  if (left === null || right === null) return left === right;
  return Math.abs(Number(left) - Number(right)) <= tolerance * Math.max(1, Math.abs(Number(left)), Math.abs(Number(right)));
};

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const root = path.dirname(reportPath);
const errors = [];

const temporaryReceipt = path.join(os.tmpdir(), `fdic-v2-${process.pid}.json`);
const v2Path = path.join(path.dirname(new URL(import.meta.url).pathname), 'verify_benchmark_v2.mjs');
const replay = childProcess.spawnSync(
  process.execPath,
  [v2Path, reportPath, temporaryReceipt],
  {encoding:'utf8'},
);
if (replay.status !== 0) errors.push('v2-replay');
const v2Receipt = fs.existsSync(temporaryReceipt)
  ? JSON.parse(fs.readFileSync(temporaryReceipt, 'utf8'))
  : null;
if (!v2Receipt?.payload?.valid) errors.push('v2-receipt');

if (canonical(payload.protocol?.test_years) !== canonical([2012, 2013, 2014])) {
  errors.push('test-years');
}
if (payload.protocol?.windows?.test?.[0] !== '2012-03-31' || payload.protocol?.windows?.test?.[1] !== '2014-12-31') {
  errors.push('test-window');
}

const predictionsPath = path.join(root, payload.sealed_test?.predictions_file ?? '');
if (!fs.existsSync(predictionsPath) || shaFile(predictionsPath) !== payload.sealed_test?.predictions_file_sha256) {
  errors.push('predictions-file');
}
const rows = fs.existsSync(predictionsPath)
  ? fs.readFileSync(predictionsPath, 'utf8').trim().split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line))
  : [];
for (const row of rows) {
  row.CERT = Number(row.CERT);
  row.label = Number(row.label);
  row.probability = Number(row.probability);
  row.threshold = Number(row.threshold);
}
const baseline = payload.selection?.selected_baseline;
const challenger = payload.selection?.selected_challenger;
const expected = payload.sealed_test?.by_year?.['2014'];
if (!baseline || !challenger || !expected) errors.push('2014-contract');

function costMetrics(method) {
  const selected = rows.filter(row => row.split === 'test' && row.REPDTE.startsWith('2014-') && row.method === method);
  const thresholds = [...new Set(selected.map(row => row.threshold))];
  if (thresholds.length !== 1) errors.push(`2014-threshold-${method}`);
  const threshold = thresholds[0];
  let falseNegatives = 0;
  let falsePositives = 0;
  for (const row of selected) {
    const alarm = row.probability >= threshold;
    if (row.label === 1 && !alarm) falseNegatives += 1;
    if (row.label === 0 && alarm) falsePositives += 1;
  }
  const totalCost = 100 * falseNegatives + falsePositives;
  return {
    rows:selected.length,
    positive_rows:selected.filter(row => row.label === 1).length,
    positive_entities:new Set(selected.filter(row => row.label === 1).map(row => row.CERT)).size,
    threshold,
    false_negatives:falseNegatives,
    false_positives:falsePositives,
    total_cost:totalCost,
    cost_per_row:selected.length ? totalCost / selected.length : null,
  };
}

if (baseline && challenger && expected) {
  const rebuiltBaseline = costMetrics(baseline);
  const rebuiltChallenger = costMetrics(challenger);
  for (const [role, rebuilt] of [['baseline', rebuiltBaseline], ['challenger', rebuiltChallenger]]) {
    const section = expected[role] ?? {};
    if (Number(section.rows) !== rebuilt.rows) errors.push(`2014-${role}-rows`);
    if (Number(section.positive_rows) !== rebuilt.positive_rows) errors.push(`2014-${role}-positive-rows`);
    if (Number(section.positive_entities) !== rebuilt.positive_entities) errors.push(`2014-${role}-positive-entities`);
    const reported = section.metrics ?? {};
    for (const field of ['threshold', 'false_negatives', 'false_positives', 'total_cost', 'cost_per_row']) {
      if (!close(reported[field], rebuilt[field])) errors.push(`2014-${role}-${field}`);
    }
  }
  const evaluable = Math.min(rebuiltBaseline.positive_rows, rebuiltChallenger.positive_rows) >= 15;
  const improves = evaluable && rebuiltChallenger.cost_per_row < rebuiltBaseline.cost_per_row;
  if (Boolean(payload.python_gate_checks?.year_2014_cost_improves) !== improves) {
    errors.push('2014-gate');
  }
}

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema:'fin-abs-004b/fdic-node-metric-receipt/3',
  valid:uniqueErrors.length === 0,
  errors:uniqueErrors,
  report_sha256:report.sha256,
  predictions_sha256:fs.existsSync(predictionsPath) ? shaFile(predictionsPath) : null,
  verifier_v2_receipt_sha256:v2Receipt?.sha256 ?? null,
  selected_baseline:baseline ?? null,
  selected_challenger:challenger ?? null,
  year_2014_gate:payload.python_gate_checks?.year_2014_cost_improves ?? null,
  performance_candidate_pass:payload.performance_candidate_pass ?? false,
  absolute_score:payload.absolute_score ?? null,
};
const receipt = {payload:receiptPayload, sha256:shaText(canonical(receiptPayload))};
fs.mkdirSync(path.dirname(outputPath), {recursive:true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
