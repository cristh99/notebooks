#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [reportPath, outputPath] = process.argv.slice(2);
if (![reportPath, outputPath].every(Boolean)) {
  console.error('usage: verify_benchmark_v2.mjs <report> <output>');
  process.exit(2);
}

const FN_COST = 100;
const FP_COST = 1;
const BOOTSTRAP_SEED = 20260803;
const CALIBRATION_SEED = 'FIN-ABS-004B-CALIBRATION-SPLIT-V1';

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

function deepClose(left, right, location, errors) {
  if (left === null || right === null) {
    if (left !== right) errors.push(location);
    return;
  }
  if (typeof left === 'number' || typeof right === 'number') {
    if (!close(left, right)) errors.push(location);
    return;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
      errors.push(location);
      return;
    }
    left.forEach((value, index) => deepClose(value, right[index], `${location}[${index}]`, errors));
    return;
  }
  if (typeof left === 'object' && typeof right === 'object') {
    const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
    for (const key of keys) {
      if (!(key in left) || !(key in right)) errors.push(`${location}.${key}`);
      else deepClose(left[key], right[key], `${location}.${key}`, errors);
    }
    return;
  }
  if (left !== right) errors.push(location);
}

function descending(rows) {
  return rows
    .map((row, index) => ({...row, __index:index}))
    .sort((a, b) => b.probability - a.probability || a.__index - b.__index);
}

function averagePrecision(rows) {
  const ordered = descending(rows);
  const positives = ordered.filter(row => row.label === 1).length;
  if (!positives) return 0;
  let truePositives = 0;
  let falsePositives = 0;
  let priorRecall = 0;
  let result = 0;
  let index = 0;
  while (index < ordered.length) {
    const score = ordered[index].probability;
    while (index < ordered.length && ordered[index].probability === score) {
      if (ordered[index].label === 1) truePositives += 1;
      else falsePositives += 1;
      index += 1;
    }
    const recall = truePositives / positives;
    const precision = truePositives / (truePositives + falsePositives);
    result += (recall - priorRecall) * precision;
    priorRecall = recall;
  }
  return result;
}

function recallAtFpr(rows, maximum) {
  const ordered = descending(rows);
  const positives = ordered.filter(row => row.label === 1).length;
  const negatives = ordered.length - positives;
  if (!positives || !negatives) return 0;
  let truePositives = 0;
  let falsePositives = 0;
  let result = 0;
  let index = 0;
  while (index < ordered.length) {
    const score = ordered[index].probability;
    while (index < ordered.length && ordered[index].probability === score) {
      if (ordered[index].label === 1) truePositives += 1;
      else falsePositives += 1;
      index += 1;
    }
    if (falsePositives / negatives <= maximum + 1e-12) {
      result = Math.max(result, truePositives / positives);
    }
  }
  return result;
}

function topPrecision(rows, fraction) {
  const count = Math.max(1, Math.ceil(rows.length * fraction));
  return descending(rows).slice(0, count).filter(row => row.label === 1).length / count;
}

function calibrationError(rows, bins = 10) {
  let result = 0;
  for (let bin = 0; bin < bins; bin += 1) {
    const lower = bin / bins;
    const upper = (bin + 1) / bins;
    const selected = rows.filter(row => row.probability >= lower && (bin < bins - 1 ? row.probability < upper : row.probability <= upper));
    if (!selected.length) continue;
    const actual = selected.reduce((total, row) => total + row.label, 0) / selected.length;
    const predicted = selected.reduce((total, row) => total + row.probability, 0) / selected.length;
    result += selected.length / rows.length * Math.abs(actual - predicted);
  }
  return result;
}

function metrics(rows, threshold) {
  const positiveRows = rows.filter(row => row.label === 1);
  const positiveEntities = new Set(positiveRows.map(row => row.CERT)).size;
  let falseNegatives = 0;
  let falsePositives = 0;
  let brier = 0;
  const leadDays = [];
  for (const row of rows) {
    const alarm = row.probability >= threshold;
    if (row.label === 1 && !alarm) falseNegatives += 1;
    if (row.label === 0 && alarm) falsePositives += 1;
    if (row.label === 1 && alarm && row.days_to_failure !== null) leadDays.push(Number(row.days_to_failure));
    brier += (row.probability - row.label) ** 2;
  }
  leadDays.sort((a, b) => a - b);
  const medianLead = leadDays.length
    ? (leadDays.length % 2 ? leadDays[(leadDays.length - 1) / 2] : (leadDays[leadDays.length / 2 - 1] + leadDays[leadDays.length / 2]) / 2)
    : null;
  const totalCost = FN_COST * falseNegatives + FP_COST * falsePositives;
  return {
    rows:rows.length,
    positive_rows:positiveRows.length,
    positive_entities:positiveEntities,
    average_precision:averagePrecision(rows),
    recall_at_fpr_0_005:recallAtFpr(rows, 0.005),
    recall_at_fpr_0_01:recallAtFpr(rows, 0.01),
    recall_at_fpr_0_02:recallAtFpr(rows, 0.02),
    top_1pct_precision:topPrecision(rows, 0.01),
    top_2pct_precision:topPrecision(rows, 0.02),
    brier:brier / rows.length,
    calibration_error_10bin:calibrationError(rows),
    threshold,
    false_negatives:falseNegatives,
    false_positives:falsePositives,
    total_cost:totalCost,
    cost_per_row:totalCost / rows.length,
    median_lead_days_detected:medianLead,
  };
}

function selectionKey(name, value) {
  return [value.cost_per_row, -value.average_precision, value.brier, name];
}
function selectMethod(allMetrics, methods) {
  return [...methods].sort((left, right) => {
    const leftKey = selectionKey(left, allMetrics[left]);
    const rightKey = selectionKey(right, allMetrics[right]);
    for (let index = 0; index < leftKey.length; index += 1) {
      if (leftKey[index] < rightKey[index]) return -1;
      if (leftKey[index] > rightKey[index]) return 1;
    }
    return 0;
  })[0];
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

function bootstrap(rows, baseline, challenger, baselineThreshold, challengerThreshold, replicates = 5000) {
  const entities = new Map();
  for (const row of rows.filter(item => item.method === baseline || item.method === challenger)) {
    if (!entities.has(row.CERT)) entities.set(row.CERT, new Map());
    const dates = entities.get(row.CERT);
    if (!dates.has(row.REPDTE)) dates.set(row.REPDTE, {label:row.label});
    dates.get(row.REPDTE)[row.method] = row.probability;
  }
  const improvements = [];
  for (const cert of [...entities.keys()].sort((a, b) => a - b)) {
    let baselineCost = 0;
    let challengerCost = 0;
    for (const item of entities.get(cert).values()) {
      if (!(baseline in item) || !(challenger in item)) continue;
      const baselineAlarm = item[baseline] >= baselineThreshold;
      const challengerAlarm = item[challenger] >= challengerThreshold;
      if (item.label === 1 && !baselineAlarm) baselineCost += FN_COST;
      if (item.label === 0 && baselineAlarm) baselineCost += FP_COST;
      if (item.label === 1 && !challengerAlarm) challengerCost += FN_COST;
      if (item.label === 0 && challengerAlarm) challengerCost += FP_COST;
    }
    improvements.push(baselineCost - challengerCost);
  }
  if (!improvements.length) return {entities:0, mean_improvement:null, lower_95:null, upper_95:null, replicates:0, seed:BOOTSTRAP_SEED};
  const indices = lcgIndices(BOOTSTRAP_SEED, replicates * improvements.length, improvements.length);
  const means = [];
  let cursor = 0;
  for (let replicate = 0; replicate < replicates; replicate += 1) {
    let total = 0;
    for (let index = 0; index < improvements.length; index += 1) total += improvements[indices[cursor++]];
    means.push(total / improvements.length);
  }
  means.sort((a, b) => a - b);
  return {
    entities:improvements.length,
    mean_improvement:improvements.reduce((a, b) => a + b, 0) / improvements.length,
    lower_95:means[Math.floor(0.025 * (replicates - 1))],
    upper_95:means[Math.ceil(0.975 * (replicates - 1))],
    replicates,
    seed:BOOTSTRAP_SEED,
  };
}

function calibrationBucket(cert) {
  const digest = crypto.createHash('sha256').update(`${CALIBRATION_SEED}|${Number(cert)}`, 'utf8').digest('hex');
  return Number(BigInt(`0x${digest.slice(0, 16)}`) % 100n);
}
function assignments(text) {
  const lines = text.trim().split(/\r?\n/);
  const header = lines.shift().split(',');
  const position = Object.fromEntries(header.map((name, index) => [name, index]));
  return lines.filter(Boolean).map(line => {
    const fields = line.split(',');
    return {
      CERT:Number(fields[position.CERT]),
      calibration_bucket:Number(fields[position.calibration_bucket]),
      subset:fields[position.subset],
    };
  });
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const root = path.dirname(reportPath);
const errors = [];
if (payload.schema !== 'fin-abs-004b/fdic-sealed-rf-benchmark/1') errors.push('schema');
if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push('report-hash');
try {
  if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) errors.push('payload-canonical');
} catch {
  errors.push('payload-canonical-json');
}
if (canonical(payload.absolute_score) !== canonical({
  before:423,
  after:423,
  delta:0,
  boundary:'No absolute points are awarded until an independent implementation reconstructs models, predictions and every non-compensable gate.',
})) errors.push('score-boundary');
if (payload.independent_model_reimplementation !== 'PENDING') errors.push('independent-boundary');

const baselines = payload.protocol?.baselines ?? [];
const challengers = payload.protocol?.challengers ?? [];
if (!Array.isArray(baselines) || !Array.isArray(challengers) || !baselines.length || !challengers.length) errors.push('method-family');
for (const required of ['RF_BALANCED', 'RF_COST_SENSITIVE', 'RF_BALANCED_PLATT', 'RF_COST_PLATT']) {
  if (!baselines.includes(required)) errors.push(`missing-${required}`);
}

const predictionsPath = path.join(root, payload.sealed_test?.predictions_file ?? '');
const preprocessingPath = path.join(root, payload.sealed_test?.preprocessing_file ?? '');
const assignmentsPath = path.join(root, payload.sealed_test?.validation_entity_assignments_file ?? '');
if (!fs.existsSync(predictionsPath) || shaFile(predictionsPath) !== payload.sealed_test?.predictions_file_sha256) errors.push('predictions-file');
if (!fs.existsSync(preprocessingPath) || shaFile(preprocessingPath) !== payload.sealed_test?.preprocessing_file_sha256) errors.push('preprocessing-file');
if (!fs.existsSync(assignmentsPath) || shaFile(assignmentsPath) !== payload.sealed_test?.validation_entity_assignments_sha256) errors.push('assignments-file');

if (fs.existsSync(assignmentsPath)) {
  const rows = assignments(fs.readFileSync(assignmentsPath, 'utf8'));
  for (const row of rows) {
    const bucket = calibrationBucket(row.CERT);
    if (bucket !== row.calibration_bucket) errors.push(`assignment-bucket-${row.CERT}`);
    if ((bucket < 50 ? 'calibration' : 'selection') !== row.subset) errors.push(`assignment-subset-${row.CERT}`);
  }
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
const methodNames = [...baselines, ...challengers];
const rebuilt = {selection:{}, test:{}};
for (const split of ['selection', 'test']) {
  for (const method of methodNames) {
    const selected = rows.filter(row => row.split === split && row.method === method);
    const thresholds = [...new Set(selected.map(row => row.threshold))];
    if (thresholds.length !== 1) errors.push(`threshold-${split}-${method}`);
    rebuilt[split][method] = metrics(selected, thresholds[0]);
  }
}
deepClose(rebuilt.selection, payload.selection?.metrics ?? {}, 'selection-metrics', errors);
const selectedBaseline = selectMethod(rebuilt.selection, baselines);
const selectedChallenger = selectMethod(rebuilt.selection, challengers);
if (selectedBaseline !== payload.selection?.selected_baseline) errors.push('selected-baseline');
if (selectedChallenger !== payload.selection?.selected_challenger) errors.push('selected-challenger');
deepClose(rebuilt.test[selectedBaseline], payload.sealed_test?.baseline?.metrics, 'test-baseline', errors);
deepClose(rebuilt.test[selectedChallenger], payload.sealed_test?.challenger?.metrics, 'test-challenger', errors);

const testRows = rows.filter(row => row.split === 'test');
for (const year of [2012, 2013]) {
  const expected = payload.sealed_test?.by_year?.[String(year)] ?? {};
  for (const [role, method] of [['baseline', selectedBaseline], ['challenger', selectedChallenger]]) {
    const selected = testRows.filter(row => Number(row.REPDTE.slice(0, 4)) === year && row.method === method);
    const rebuiltMetrics = metrics(selected, rebuilt.selection[method].threshold);
    deepClose(rebuiltMetrics, expected[role]?.metrics, `year-${year}-${role}`, errors);
    if (selected.length !== Number(expected[role]?.rows ?? -1)) errors.push(`year-${year}-${role}-rows`);
  }
}
const rebuiltBootstrap = bootstrap(
  testRows,
  selectedBaseline,
  selectedChallenger,
  rebuilt.selection[selectedBaseline].threshold,
  rebuilt.selection[selectedChallenger].threshold,
);
deepClose(rebuiltBootstrap, payload.sealed_test?.bank_cluster_bootstrap, 'bootstrap', errors);

const allPythonGatesPass = Object.values(payload.python_gate_checks ?? {}).every(value => value === true);
if (Boolean(payload.performance_candidate_pass) !== allPythonGatesPass) errors.push('candidate-pass');
const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema:'fin-abs-004b/fdic-node-metric-receipt/2',
  valid:uniqueErrors.length === 0,
  errors:uniqueErrors,
  report_sha256:report.sha256,
  predictions_sha256:fs.existsSync(predictionsPath) ? shaFile(predictionsPath) : null,
  selected_baseline:selectedBaseline,
  selected_challenger:selectedChallenger,
  performance_candidate_pass:Boolean(payload.performance_candidate_pass),
  independent_model_reimplementation:payload.independent_model_reimplementation ?? null,
  absolute_score:payload.absolute_score ?? null,
};
const receipt = {payload:receiptPayload, sha256:shaText(canonical(receiptPayload))};
fs.mkdirSync(path.dirname(outputPath), {recursive:true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
