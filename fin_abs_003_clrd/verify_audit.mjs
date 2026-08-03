#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [reportPath, datasetPath, casesPath, outputPath] = process.argv.slice(2);
if (![reportPath, datasetPath, casesPath, outputPath].every(Boolean)) {
  console.error('usage: verify_audit.mjs <report> <dataset> <cases> <output>');
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

const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
const payload = report.payload ?? {};
const errors = [];
if (payload.schema !== 'fin-abs-003/clrd-data-audit/1') errors.push('schema');
if (payload.source?.source_commit !== '2f6ea125d17e29d018b56e4df85eda52ac8ac206') errors.push('source-commit');
if (payload.source?.source_blob !== '04e54cfa41e7bd879877e5c5aea5e63a6d20d29b') errors.push('source-blob');
const transport = shaFile(datasetPath);
if (payload.source?.transport_sha256 !== transport) errors.push('transport-sha');
if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push('payload-hash');
try {
  if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) errors.push('payload-canonical');
} catch {
  errors.push('payload-json');
}
if (payload.status !== 'PASS_DATA_AUDIT') errors.push('status');
if (payload.dataset?.rows < 40000) errors.push('rows');
if (payload.dataset?.triangles < 500) errors.push('triangles');
if (Object.keys(payload.dataset?.lines ?? {}).length !== 6) errors.push('lines');
if (payload.dataset?.duplicate_cells !== 0) errors.push('duplicates');
if (payload.split?.entity_leakage !== 0) errors.push('split-leakage');
for (const split of ['train', 'validation', 'test']) {
  if (!(Number(payload.split?.case_counts?.[split]) > 0)) errors.push(`split-${split}`);
}
if (payload.cases?.eligible < 5000) errors.push('cases');
if (Object.keys(payload.cases?.line_counts ?? {}).length !== 6) errors.push('case-lines');
const gates = payload.gate_checks ?? {};
if (Object.keys(gates).length < 10 || !Object.values(gates).every(Boolean)) errors.push('gates');
if (canonical(payload.absolute_score) !== canonical({
  before: 423,
  after: 423,
  delta: 0,
  boundary: 'Data acquisition and audit do not establish reserving superiority.',
})) errors.push('score-boundary');

const header = fs.readFileSync(casesPath, 'utf8').split(/\r?\n/, 1)[0];
for (const required of ['case_id', 'GRCODE', 'LOB', 'cutoff', 'actual_reserve', 'split']) {
  if (!header.split(',').includes(required)) errors.push(`cases-${required}`);
}

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema: 'fin-abs-003/clrd-data-audit-node-receipt/1',
  valid: uniqueErrors.length === 0,
  errors: uniqueErrors,
  transport_sha256: transport,
  report_sha256: report.sha256,
  cases_file_sha256: shaFile(casesPath),
  rows: payload.dataset?.rows ?? null,
  triangles: payload.dataset?.triangles ?? null,
  eligible_cases: payload.cases?.eligible ?? null,
  split_case_counts: payload.split?.case_counts ?? null,
  absolute_score: payload.absolute_score ?? null,
};
const receipt = {payload: receiptPayload, sha256: shaText(canonical(receiptPayload))};
fs.mkdirSync(outputPath.split('/').slice(0, -1).join('/') || '.', {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
