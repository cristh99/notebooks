#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [reportPath, outputPath] = process.argv.slice(2);
if (![reportPath, outputPath].every(Boolean)) {
  console.error('usage: verify_audit_v3.mjs <report> <output>');
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
const root = path.dirname(reportPath);
const errors = [];

if (payload.schema !== 'fin-abs-004/fdic-access-audit/2') errors.push('schema');
if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push('report-hash');
try {
  if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) errors.push('canonical-payload');
} catch {
  errors.push('canonical-json');
}
const allowed = new Map([
  ['PROCEED', 'STAGE0_PROCEED'],
  ['REDESIGN', 'STAGE0_REDESIGN'],
]);
if (!allowed.has(payload.recommendation)) errors.push('recommendation');
else if (payload.status !== allowed.get(payload.recommendation)) errors.push('status');
if (canonical(payload.absolute_score) !== canonical({
  before:423, after:423, delta:0,
  boundary:'Metadata redesign and access audit only; no bank-distress model evaluated.',
})) errors.push('score-boundary');

const documentation = payload.documentation_contract ?? {};
if (documentation.legacy_yaml_urls_now_return_html !== true) errors.push('legacy-redirect-detection');
if (documentation.official_api_documentation_identified !== true) errors.push('official-docs');
for (const item of documentation.files ?? []) {
  const file = path.join(root, item.file ?? '');
  if (!fs.existsSync(file) || shaFile(file) !== item.sha256) errors.push(`documentation-${item.resource}`);
}
const live = payload.live_api_contract ?? {};
for (const key of ['financial_full_record', 'failure_full_record']) {
  const item = live[key] ?? {};
  const file = path.join(root, item.file ?? '');
  if (!fs.existsSync(file)) errors.push(`live-${key}-file`);
  else if (item.acquisition?.sha256 && shaFile(file) !== item.acquisition.sha256) errors.push(`live-${key}-sha`);
  if (!(item.column_count > 0) || !Array.isArray(item.columns)) errors.push(`live-${key}-columns`);
}
for (const record of payload.acquisitions ?? []) {
  if (record.file) {
    const file = path.join(root, record.file);
    if (!fs.existsSync(file)) errors.push(`missing-${record.file}`);
    else if (record.sha256 && shaFile(file) !== record.sha256) errors.push(`sha-${record.file}`);
  }
}
const samples = payload.financial_samples ?? [];
if (samples.length !== 5) errors.push('sample-count');
for (const sample of samples) {
  if (sample.status !== 'ACQUIRED') errors.push(`sample-status-${sample.date}`);
  else {
    const file = path.join(root, sample.file);
    if (!fs.existsSync(file) || shaFile(file) !== sample.sha256) errors.push(`sample-${sample.date}`);
    if (!(sample.rows > 0) || sample.duplicate_bank_quarters !== 0) errors.push(`sample-shape-${sample.date}`);
  }
}
const failures = payload.failures ?? {};
if (!(failures.rows >= 500)) errors.push('failure-rows');
if (!(failures.date_parse_rate >= 0.99)) errors.push('failure-dates');
const gates = payload.gate_checks ?? {};
if (Object.keys(gates).length < 12) errors.push('gate-count');
const allGatesPass = Object.values(gates).every(Boolean);
if (payload.recommendation === 'PROCEED' && !allGatesPass) errors.push('proceed-with-failed-gates');
if (payload.recommendation !== 'PROCEED' && allGatesPass) errors.push('redesign-with-all-gates');

const uniqueErrors = [...new Set(errors)].sort();
const failedGates = Object.entries(gates).filter(([, value]) => value !== true).map(([key]) => key).sort();
const receiptPayload = {
  schema:'fin-abs-004/fdic-access-audit-node-receipt/3',
  valid:uniqueErrors.length === 0,
  errors:uniqueErrors,
  report_sha256:report.sha256,
  recommendation:payload.recommendation ?? null,
  failed_gates:failedGates,
  failure_rows:failures.rows ?? null,
  candidate_windows:failures.candidate_window_counts ?? null,
  quarters_acquired:samples.filter(item => item.status === 'ACQUIRED').length,
  live_contract_fields:{
    financial:live.financial_full_record?.column_count ?? null,
    failure:live.failure_full_record?.column_count ?? null,
  },
  absolute_score:payload.absolute_score ?? null,
};
const receipt = {payload:receiptPayload, sha256:shaText(canonical(receiptPayload))};
fs.mkdirSync(path.dirname(outputPath), {recursive:true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
