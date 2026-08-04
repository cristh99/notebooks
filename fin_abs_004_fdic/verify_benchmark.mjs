#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [reportPath, outputPath] = process.argv.slice(2);
if (![reportPath, outputPath].every(Boolean)) {
  console.error('usage: verify_benchmark.mjs <report> <output>');
  process.exit(2);
}

const FN_COST = 100;
const FP_COST = 1;
const SEED = 20260803;
const BASELINES = ['CONSTANT_RATE', 'CAMELS_LITE', 'LOGISTIC_L2', 'SURVIVAL_LOGIT'];
const CHALLENGERS = ['MONOTONIC_HGB', 'MONOTONIC_HGB_HORIZON', 'CALIBRATED_ENSEMBLE'];

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const shaText = value => crypto.createHash('sha256').update(value, 'utf8').digest('hex');
const shaFile = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const close = (a, b, tolerance = 1e-8) => {
  if (a === null || b === null) return a === b;
  return Math.abs(Number(a) - Number(b)) <= tolerance * Math.max(1, Math.abs(Number(a)), Math.abs(Number(b)));
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

function averagePrecision(rows) {
  const ordered = [...rows].sort((a, b) => b.probability - a.probability || a.CERT - b.CERT || a.REPDTE.localeCompare(b.REPDTE));
  const positives = ordered.filter(row => row.label === 1).length;
  if (!positives) return 0;
  let seen = 0;
  let sum = 0;
  ordered.forEach((row, index) => {
    if (row.label === 1) {
      seen += 1;
      sum += seen / (index + 1);
    }
  });
  return sum / positives;
}

function recallAtFpr(rows, limit) {
  const ordered = [...rows].sort((a, b) => b.probability - a.probability || a.CERT - b.CERT || a.REPDTE.localeCompare(b.REPDTE));
  const positives = ordered.filter(row => row.label === 1).length;
  const negatives = ordered.length - positives;
  if (!positives || !negatives) return 0;
  let tp = 0;
  let fp = 0;
  let best = 0;
  let index = 0;
  while (index < ordered.length) {
    const probability = ordered[index].probability;
    while (index < ordered.length && ordered[index].probability === probability) {
      if (ordered[index].label === 1) tp += 1;
      else fp += 1;
      index += 1;
    }
    const fpr = fp / negatives;
    if (fpr <= limit + 1e-12) best = Math.max(best, tp / positives);
  }
  return best;
}

function topPrecision(rows, fraction) {
  const count = Math.max(1, Math.ceil(rows.length * fraction));
  const ordered = [...rows].sort((a, b) => b.probability - a.probability || a.CERT - b.CERT || a.REPDTE.localeCompare(b.REPDTE)).slice(0, count);
  return ordered.filter(row => row.label === 1).length / count;
}

function calibrationError(rows, bins = 10) {
  let error = 0;
  for (let index = 0; index < bins; index += 1) {
    const lower = index / bins;
    const upper = (index + 1) / bins;
    const selected = rows.filter(row => row.probability >= lower && (index < bins - 1 ? row.probability < upper : row.probability <= upper));
    if (!selected.length) continue;
    const actual = selected.reduce((sum, row) => sum + row.label, 0) / selected.length;
    const predicted = selected.reduce((sum, row) => sum + row.probability, 0) / selected.length;
    error += selected.length / rows.length * Math.abs(actual - predicted);
  }
  return error;
}

function metric(rows, threshold) {
  const positives = rows.filter(row => row.label === 1);
  const positiveEntities = new Set(positives.map(row => row.CERT)).size;
  let falseNegatives = 0;
  let falsePositives = 0;
  const lead = [];
  let brier = 0;
  for (const row of rows) {
    const predicted = row.probability >= threshold;
    if (row.label === 1 && !predicted) falseNegatives += 1;
    if (row.label === 0 && predicted) falsePositives += 1;
    if (row.label === 1 && predicted && row.days_to_failure !== null) lead.push(Number(row.days_to_failure));
    brier += (row.probability - row.label) ** 2;
  }
  lead.sort((a, b) => a - b);
  const medianLead = lead.length ? (lead.length % 2 ? lead[(lead.length - 1) / 2] : (lead[lead.length / 2 - 1] + lead[lead.length / 2]) / 2) : null;
  const totalCost = FN_COST * falseNegatives + FP_COST * falsePositives;
  return {
    rows: rows.length,
    positive_rows: positives.length,
    positive_entities: positiveEntities,
    average_precision: averagePrecision(rows),
    recall_at_fpr_0_005: recallAtFpr(rows, 0.005),
    recall_at_fpr_0_01: recallAtFpr(rows, 0.01),
    recall_at_fpr_0_02: recallAtFpr(rows, 0.02),
    top_1pct_precision: topPrecision(rows, 0.01),
    top_2pct_precision: topPrecision(rows, 0.02),
    brier: brier / rows.length,
    calibration_error_10bin: calibrationError(rows),
    threshold,
    false_negatives: falseNegatives,
    false_positives: falsePositives,
    total_cost: totalCost,
    cost_per_row: totalCost / rows.length,
    median_lead_days_detected: medianLead,
  };
}

function selectionKey(name, metrics) {
  return [metrics.cost_per_row, -metrics.average_precision, metrics.brier, name];
}
function compareKeys(left, right) {
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}
function selectMethod(metrics, methods) {
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

function clusterBootstrap(rows, baseline, challenger, baselineThreshold, challengerThreshold, replicates = 5000) {
  const byEntity = new Map();
  for (const row of rows.filter(value => value.method === baseline || value.method === challenger)) {
    if (!byEntity.has(row.CERT)) byEntity.set(row.CERT, new Map());
    const entity = byEntity.get(row.CERT);
    const key = row.REPDTE;
    if (!entity.has(key)) entity.set(key, {label: row.label});
    entity.get(key)[row.method] = row.probability;
  }
  const improvements = [];
  for (const entity of [...byEntity.keys()].sort((a, b) => a - b)) {
    let baselineCost = 0;
    let challengerCost = 0;
    for (const item of byEntity.get(entity).values()) {
      if (!(baseline in item) || !(challenger in item)) continue;
      const baselinePrediction = item[baseline] >= baselineThreshold;
      const challengerPrediction = item[challenger] >= challengerThreshold;
      if (item.label === 1 && !baselinePrediction) baselineCost += FN_COST;
      if (item.label === 0 && baselinePrediction) baselineCost += FP_COST;
      if (item.label === 1 && !challengerPrediction) challengerCost += FN_COST;
      if (item.label === 0 && challengerPrediction) challengerCost += FP_COST;
    }
    improvements.push(baselineCost - challengerCost);
  }
  if (!improvements.length) return {entities:0, mean_improvement:null, lower_95:null, upper_95:null, replicates:0, seed:SEED};
  const indices = lcgIndices(SEED, replicates * improvements.length, improvements.length);
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
    seed: SEED,
  };
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const root = path.dirname(reportPath);
const errors = [];
if (payload.schema !== 'fin-abs-004/fdic-sealed-distress-benchmark/1') errors.push('schema');
if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push('report-hash');
try {
  if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) errors.push('canonical-payload');
} catch {
  errors.push('canonical-json');
}
if (canonical(payload.absolute_score) !== canonical({
  before:423, after:423, delta:0,
  boundary:'No absolute points are awarded until a separate implementation reconstructs labels, predictions and every non-compensable gate.',
})) errors.push('score-boundary');
if (payload.independent_model_reimplementation !== 'PENDING') errors.push('independent-boundary');
const predictionsPath = path.join(root, payload.sealed_test?.predictions_file ?? '');
const preprocessingPath = path.join(root, payload.sealed_test?.preprocessing_file ?? '');
if (!fs.existsSync(predictionsPath) || shaFile(predictionsPath) !== payload.sealed_test?.predictions_file_sha256) errors.push('predictions-file');
if (!fs.existsSync(preprocessingPath) || shaFile(preprocessingPath) !== payload.sealed_test?.preprocessing_file_sha256) errors.push('preprocessing-file');
const rows = fs.existsSync(predictionsPath) ? fs.readFileSync(predictionsPath, 'utf8').trim().split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line)) : [];
for (const row of rows) {
  row.CERT = Number(row.CERT);
  row.label = Number(row.label);
  row.probability = Number(row.probability);
  row.threshold = Number(row.threshold);
}
const metrics = {validation:{}, test:{}};
const methods = [...BASELINES, ...CHALLENGERS];
for (const split of ['validation', 'test']) {
  for (const method of methods) {
    const selected = rows.filter(row => row.split === split && row.method === method);
    const thresholds = [...new Set(selected.map(row => row.threshold))];
    if (thresholds.length !== 1) errors.push(`threshold-${split}-${method}`);
    metrics[split][method] = metric(selected, thresholds[0]);
  }
}
deepClose(metrics.validation, payload.validation?.metrics ?? {}, 'validation-metrics', errors);
const selectedBaseline = selectMethod(metrics.validation, BASELINES);
const selectedChallenger = selectMethod(metrics.validation, CHALLENGERS);
if (selectedBaseline !== payload.validation?.selected_baseline) errors.push('selected-baseline');
if (selectedChallenger !== payload.validation?.selected_challenger) errors.push('selected-challenger');
deepClose(metrics.test[selectedBaseline], payload.sealed_test?.baseline?.metrics, 'test-baseline', errors);
deepClose(metrics.test[selectedChallenger], payload.sealed_test?.challenger?.metrics, 'test-challenger', errors);
const testRows = rows.filter(row => row.split === 'test');
const baselineThreshold = metrics.validation[selectedBaseline].threshold;
const challengerThreshold = metrics.validation[selectedChallenger].threshold;
const bootstrap = clusterBootstrap(testRows, selectedBaseline, selectedChallenger, baselineThreshold, challengerThreshold);
deepClose(bootstrap, payload.sealed_test?.bank_cluster_bootstrap, 'bootstrap', errors);

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema:'fin-abs-004/fdic-node-metric-receipt/1',
  valid:uniqueErrors.length === 0,
  errors:uniqueErrors,
  report_sha256:report.sha256,
  predictions_sha256:fs.existsSync(predictionsPath) ? shaFile(predictionsPath) : null,
  selected_baseline:selectedBaseline,
  selected_challenger:selectedChallenger,
  performance_candidate_pass:payload.performance_candidate_pass ?? false,
  independent_model_reimplementation:payload.independent_model_reimplementation ?? null,
  absolute_score:payload.absolute_score ?? null,
};
const receipt = {payload:receiptPayload, sha256:shaText(canonical(receiptPayload))};
fs.mkdirSync(path.dirname(outputPath), {recursive:true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
