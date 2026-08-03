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
const close = (left, right, tolerance = 1e-9) => Math.abs(Number(left) - Number(right)) <= tolerance * Math.max(1, Math.abs(Number(left)), Math.abs(Number(right)));

function parseDaily(file) {
  const lines = fs.readFileSync(file, 'utf8').trim().split(/\r?\n/);
  const header = lines.shift().split(',');
  const positions = Object.fromEntries(header.map((value, index) => [value, index]));
  return lines.filter(Boolean).map(line => {
    const values = line.split(',');
    return {
      date: values[positions.date],
      gross_return: Number(values[positions.gross_return]),
      net_return: Number(values[positions.net_return]),
      turnover: Number(values[positions.turnover]),
      cost: Number(values[positions.cost]),
    };
  });
}

function maximumWeight(file) {
  const lines = fs.readFileSync(file, 'utf8').trim().split(/\r?\n/);
  lines.shift();
  let maximum = 0;
  for (const line of lines) {
    const values = line.split(',').slice(1).map(Number);
    for (const value of values) if (Number.isFinite(value)) maximum = Math.max(maximum, value);
  }
  return maximum;
}

function metrics(rows, maxWeight) {
  const returns = rows.map(row => row.net_return);
  let wealth = 1;
  let peak = 1;
  let worst = 0;
  for (const value of returns) {
    wealth *= 1 + value;
    peak = Math.max(peak, wealth);
    worst = Math.min(worst, wealth / peak - 1);
  }
  const n = returns.length;
  const mean = returns.reduce((sum, value) => sum + value, 0) / n;
  const variance = n > 1 ? returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (n - 1) : 0;
  const stdev = Math.sqrt(variance);
  const losses = returns.map(value => -value).sort((a, b) => a - b);
  const tailCount = Math.max(1, Math.ceil(0.05 * losses.length));
  const tail = losses.slice(-tailCount);
  return {
    observations: n,
    total_return: wealth - 1,
    annualized_return: wealth ** (252 / n) - 1,
    annualized_volatility: stdev * Math.sqrt(252),
    sharpe: stdev > 1e-15 ? mean / stdev * Math.sqrt(252) : 0,
    max_drawdown_loss: -worst,
    expected_shortfall_95_loss: tail.reduce((sum, value) => sum + value, 0) / tail.length,
    turnover: rows.reduce((sum, row) => sum + row.turnover, 0),
    total_cost: rows.reduce((sum, row) => sum + row.cost, 0),
    maximum_single_asset_weight: maxWeight,
  };
}

function monthly(rows) {
  const grouped = new Map();
  for (const row of rows) {
    const month = row.date.slice(0, 7);
    grouped.set(month, (grouped.get(month) ?? 1) * (1 + row.net_return));
  }
  return [...grouped.entries()].map(([month, wealth]) => [month, wealth - 1]);
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

function bootstrap(values, blockLength = 3, replicates = 5000, seed = 20260803) {
  const n = values.length;
  const blocks = Math.ceil(n / blockLength);
  const starts = lcgIndices(seed, replicates * blocks, n);
  const means = [];
  let cursor = 0;
  for (let replicate = 0; replicate < replicates; replicate += 1) {
    const sample = [];
    for (let block = 0; block < blocks; block += 1) {
      const start = starts[cursor++];
      for (let offset = 0; offset < blockLength; offset += 1) sample.push(values[(start + offset) % n]);
    }
    const selected = sample.slice(0, n);
    means.push(selected.reduce((sum, value) => sum + value, 0) / n);
  }
  means.sort((a, b) => a - b);
  const low = Math.floor(0.025 * (replicates - 1));
  const high = Math.ceil(0.975 * (replicates - 1));
  return {
    mean: values.reduce((sum, value) => sum + value, 0) / n,
    lower_95: means[low],
    upper_95: means[high],
    replicates,
    block_length: blockLength,
    seed,
  };
}

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const root = path.dirname(reportPath);
const errors = [];
if (payload.schema !== 'fin-abs-002/portbench-external-benchmark/1') errors.push('schema');
if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push('report-hash');
try {
  if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) errors.push('canonical-payload');
} catch {
  errors.push('canonical-json');
}
if (payload.absolute_score?.before !== 423 || payload.absolute_score?.after !== 423 || payload.absolute_score?.delta !== 0) errors.push('score-boundary');
if (payload.independent_weight_reimplementation !== 'PENDING') errors.push('independent-boundary');

for (const side of ['baseline', 'challenger']) {
  const section = payload.sealed_test?.[side] ?? {};
  const files = payload.sealed_test?.files?.[side] ?? {};
  const dailyPath = path.join(root, files.daily_file ?? '');
  const weightsPath = path.join(root, files.weights_file ?? '');
  if (!fs.existsSync(dailyPath) || !fs.existsSync(weightsPath)) {
    errors.push(`${side}-files`);
    continue;
  }
  if (shaFile(dailyPath) !== files.daily_sha256) errors.push(`${side}-daily-sha`);
  if (shaFile(weightsPath) !== files.weights_sha256) errors.push(`${side}-weights-sha`);
  const calculated = metrics(parseDaily(dailyPath), maximumWeight(weightsPath));
  for (const [key, value] of Object.entries(calculated)) {
    if (!close(value, section.metrics?.[key])) errors.push(`${side}-metric-${key}`);
  }
}

const baselineRows = parseDaily(path.join(root, payload.sealed_test.files.baseline.daily_file));
const challengerRows = parseDaily(path.join(root, payload.sealed_test.files.challenger.daily_file));
const baselineMonthly = new Map(monthly(baselineRows));
const challengerMonthly = new Map(monthly(challengerRows));
const months = [...baselineMonthly.keys()].filter(month => challengerMonthly.has(month)).sort();
const differences = months.map(month => challengerMonthly.get(month) - baselineMonthly.get(month));
const paired = payload.sealed_test?.paired_monthly ?? {};
if (canonical(months) !== canonical(paired.months)) errors.push('paired-months');
for (let index = 0; index < differences.length; index += 1) {
  if (!close(differences[index], paired.difference?.[index])) errors.push('paired-difference');
}
const boot = bootstrap(differences);
for (const [key, value] of Object.entries(boot)) {
  if (!close(value, paired.bootstrap?.[key])) errors.push(`bootstrap-${key}`);
}

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema: 'fin-abs-002/portbench-node-performance-receipt/1',
  valid: uniqueErrors.length === 0,
  errors: uniqueErrors,
  report_sha256: report.sha256,
  selected_baseline: payload.validation?.selected_baseline ?? null,
  selected_challenger: payload.validation?.selected_challenger ?? null,
  performance_candidate_pass: payload.performance_candidate_pass ?? false,
  independent_weight_reimplementation: payload.independent_weight_reimplementation ?? null,
  absolute_score: payload.absolute_score ?? null,
};
const receipt = {payload: receiptPayload, sha256: shaText(canonical(receiptPayload))};
fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
