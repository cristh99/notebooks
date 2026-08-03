#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [reportPath, datasetPath, outputPath] = process.argv.slice(2);
if (![reportPath, datasetPath, outputPath].every(Boolean)) {
  console.error('usage: verify_audit.mjs <report> <dataset> <output>');
  process.exit(2);
}

const EXPECTED_DATASET_SHA = '495659fb40690d48748dcbcbd8c8c2add5371fac9d5be535270959ae8f519221';
const EXPECTED_SOURCE_COMMIT = '5e7cce2e1214a5dd026578c8814953f358b5a475';
const EXPECTED_CLASSES = new Set([
  'equities', 'bonds', 'commodities', 'real_estate', 'cryptocurrency', 'cash',
]);

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const shaText = value => crypto.createHash('sha256').update(value, 'utf8').digest('hex');
const shaFile = path => crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex');

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const errors = [];

if (payload.schema !== 'fin-abs-002/portbench-data-audit/1') errors.push('schema');
if (payload.source?.source_commit !== EXPECTED_SOURCE_COMMIT) errors.push('source-commit');
const datasetSha = shaFile(datasetPath);
if (datasetSha !== EXPECTED_DATASET_SHA) errors.push('dataset-file-sha');
if (payload.source?.dataset_sha256 !== datasetSha) errors.push('dataset-report-sha');
if (typeof report.payload_canonical !== 'string') errors.push('payload-canonical-shape');
else {
  if (shaText(report.payload_canonical) !== report.sha256) errors.push('payload-hash');
  try {
    const parsedCanonical = JSON.parse(report.payload_canonical);
    if (canonical(parsedCanonical) !== canonical(payload)) errors.push('payload-canonical-mismatch');
  } catch {
    errors.push('payload-canonical-json');
  }
}
if (payload.status !== 'PASS_DATA_AUDIT') errors.push('status');
if (payload.shape?.rows < 4000 || payload.shape?.columns < 1000) errors.push('shape');
if (payload.shape?.date_start !== '2015-01-02' || payload.shape?.date_end !== '2025-12-31') errors.push('date-range');
if (payload.returns?.tradable_return_columns < 100) errors.push('tradable-count');
const classes = payload.returns?.asset_class_counts ?? {};
for (const name of EXPECTED_CLASSES) {
  if (!(Number(classes[name]) > 0)) errors.push(`asset-class-${name}`);
}
if (payload.returns?.convention?.inferred_convention !== 'log_return') errors.push('return-convention');
if (payload.splits?.embedded_labels_consistent !== true) errors.push('split-consistency');
const gates = payload.gate_checks ?? {};
if (Object.keys(gates).length < 8 || !Object.values(gates).every(Boolean)) errors.push('gate-checks');
if (canonical(payload.score_effect) !== canonical({
  absolute_score_before: 423,
  absolute_score_after: 423,
  delta: 0,
  reason: 'Information acquisition only; no external performance gate has been run.',
})) errors.push('score-effect');

const header = fs.readFileSync(datasetPath, {encoding: 'utf8', flag: 'r'}).split(/\r?\n/, 1)[0];
if (!header.startsWith('date,')) errors.push('csv-header');
if (!header.includes('_return') || !header.includes('_close')) errors.push('csv-fields');

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema: 'fin-abs-002/portbench-data-audit-node-receipt/1',
  valid: uniqueErrors.length === 0,
  errors: uniqueErrors,
  dataset_sha256: datasetSha,
  report_payload_sha256: report.sha256,
  rows: payload.shape?.rows ?? null,
  columns: payload.shape?.columns ?? null,
  tradable_assets: payload.returns?.tradable_return_columns ?? null,
  asset_class_counts: classes,
  score_effect: payload.score_effect ?? null,
};
const receipt = {payload: receiptPayload, sha256: shaText(canonical(receiptPayload))};
fs.mkdirSync(outputPath.split('/').slice(0, -1).join('/') || '.', {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
