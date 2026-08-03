import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const output = process.argv[2] || 'reports/fin_rvi_002_stage1';
const reportPath = path.join(output, 'report.json');
const decisionsPath = path.join(output, 'holdout_decisions.jsonl');
const checksumPath = path.join(output, 'report.sha256');

function fail(message) {
  console.error(`FAIL: ${message}`);
  process.exit(1);
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

for (const file of [reportPath, decisionsPath, checksumPath]) {
  if (!fs.existsSync(file)) fail(`missing ${file}`);
}

const reportBytes = fs.readFileSync(reportPath);
const expectedFileHash = fs.readFileSync(checksumPath, 'utf8').trim().split(/\s+/)[0];
if (sha256(reportBytes) !== expectedFileHash) fail('report-file-sha256');

const report = JSON.parse(reportBytes.toString('utf8'));
const payload = report.payload || report;
if (payload.schema !== 'fin-rvi-002/stage1-public-data/2') fail(`schema=${payload.schema}`);

const rows = fs.readFileSync(decisionsPath, 'utf8')
  .split(/\r?\n/)
  .filter(Boolean)
  .map((line) => JSON.parse(line));
if (!rows.length) fail('empty-holdout');

const ids = rows.map((row) => row.candidate_id);
if (ids.some((value) => !value)) fail('missing-candidate-id');
if (new Set(ids).size !== ids.length) fail('duplicate-candidate-id');

const allowed = new Set(['SUPPORTED', 'REJECTED', 'UNRESOLVED']);
const decisionCounts = {};
const cardinalityCounts = {};
const stratumCounts = {};
for (const row of rows) {
  const decision = row.decision || row.object_decision;
  if (!allowed.has(decision)) fail(`invalid-decision:${decision}`);
  decisionCounts[decision] = (decisionCounts[decision] || 0) + 1;

  const cardinality = row.cardinality_type || 'UNKNOWN';
  cardinalityCounts[cardinality] = (cardinalityCounts[cardinality] || 0) + 1;
  const stratum = row.holdout_stratum || 'UNKNOWN';
  stratumCounts[stratum] = (stratumCounts[stratum] || 0) + 1;

  if (decision === 'SUPPORTED' && row.supplier_identity_supported !== true) {
    fail(`unsupported-supplier-promotion:${row.candidate_id}`);
  }
  if (decision === 'REJECTED' && !String(row.reason || '').includes('CONFLICT')) {
    fail(`rejection-without-material-conflict:${row.candidate_id}`);
  }
  if (!row.shared_code) fail(`missing-shared-code:${row.candidate_id}`);
  if (!row.holdout_order_key || !/^[a-f0-9]{64}$/.test(row.holdout_order_key)) {
    fail(`invalid-holdout-order-key:${row.candidate_id}`);
  }
}

const metrics = payload.holdout_metrics || {};
const expectedSize = metrics.holdout_size ?? metrics.total ?? rows.length;
if (expectedSize !== rows.length) fail(`holdout-size:${expectedSize}!=${rows.length}`);

function compareCounts(label, actual, expected) {
  if (!expected || typeof expected !== 'object') return;
  for (const [key, value] of Object.entries(expected)) {
    if ((actual[key] || 0) !== value) fail(`${label}:${key}:${actual[key] || 0}!=${value}`);
  }
}

compareCounts('cardinality-counts', cardinalityCounts, metrics.cardinality_counts);
compareCounts('stratum-counts', stratumCounts, metrics.stratum_counts);

for (const [key, decision] of [['supported', 'SUPPORTED'], ['rejected', 'REJECTED'], ['unresolved', 'UNRESOLVED']]) {
  if (metrics[key] !== undefined && metrics[key] !== (decisionCounts[decision] || 0)) {
    fail(`${key}:${metrics[key]}!=${decisionCounts[decision] || 0}`);
  }
}

const uniqueCodes = new Set(rows.map((row) => row.shared_code)).size;
if (metrics.unique_shared_codes !== undefined && metrics.unique_shared_codes !== uniqueCodes) {
  fail(`unique-shared-codes:${metrics.unique_shared_codes}!=${uniqueCodes}`);
}

const receipt = {
  schema: 'fin-rvi-002/stage1-node-independent-verification/1',
  report_file_sha256: expectedFileHash,
  report_logical_sha256: report.sha256 || null,
  holdout_rows: rows.length,
  unique_shared_codes: uniqueCodes,
  decisions: decisionCounts,
  cardinalities: cardinalityCounts,
  strata: stratumCounts,
  gates: {
    report_file_hash: 'PASS',
    schema: 'PASS',
    unique_candidates: 'PASS',
    cardinality_reconciliation: 'PASS',
    no_supplierless_promotion: 'PASS',
    rejection_requires_conflict: 'PASS',
  },
};
const receiptText = `${JSON.stringify(receipt, null, 2)}\n`;
const receiptPath = path.join(output, 'node_independent_receipt.json');
fs.writeFileSync(receiptPath, receiptText);
fs.writeFileSync(
  path.join(output, 'node_independent_receipt.sha256'),
  `${sha256(Buffer.from(receiptText))}  node_independent_receipt.json\n`,
);
console.log(receiptText);
