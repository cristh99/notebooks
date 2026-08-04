#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const [reportPath, preflightPath, entityPath, outputPath] = process.argv.slice(2);
if (![reportPath, preflightPath, entityPath, outputPath].every(Boolean)) {
  console.error(
    'usage: verify_boundaries.mjs <benchmark-report> <preflight-report> <entity-report> <output>'
  );
  process.exit(2);
}

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

function readCertificate(file, label, errors) {
  const value = JSON.parse(fs.readFileSync(file, 'utf8'));
  const payload = value.payload ?? {};
  if (typeof value.payload_canonical !== 'string') {
    errors.push(`${label}-canonical-shape`);
  } else {
    if (shaText(value.payload_canonical) !== value.sha256) {
      errors.push(`${label}-hash`);
    }
    try {
      if (canonical(JSON.parse(value.payload_canonical)) !== canonical(payload)) {
        errors.push(`${label}-canonical-mismatch`);
      }
    } catch {
      errors.push(`${label}-canonical-json`);
    }
  }
  return value;
}

const errors = [];
const benchmark = readCertificate(reportPath, 'benchmark', errors);
const preflight = readCertificate(preflightPath, 'preflight', errors);
const entity = readCertificate(entityPath, 'entity', errors);
const payload = benchmark.payload ?? {};
const preflightPayload = preflight.payload ?? {};
const entityPayload = entity.payload ?? {};

if (preflightPayload.schema !== 'fin-abs-004/fdic-preflight/1') {
  errors.push('preflight-schema');
}
if (entityPayload.schema !== 'fin-abs-004/fdic-entity-disjoint-panel/1') {
  errors.push('entity-schema');
}
if (preflightPayload.status !== 'PASS_PREFLIGHT') {
  errors.push('preflight-status');
}
if (entityPayload.status !== 'PASS_ENTITY_SPLIT') {
  errors.push('entity-status');
}

const preflightGates = preflightPayload.gate_checks ?? {};
const entityGates = entityPayload.gate_checks ?? {};
if (!Object.keys(preflightGates).length || !Object.values(preflightGates).every(Boolean)) {
  errors.push('preflight-gates');
}
if (!Object.keys(entityGates).length || !Object.values(entityGates).every(Boolean)) {
  errors.push('entity-gates');
}

const overlaps = preflightPayload.entity_overlap_counts ?? {};
if (
  !['train_validation', 'train_test', 'validation_test'].every(
    key => Number(overlaps[key]) === 0
  )
) {
  errors.push('entity-overlap');
}

const source = payload.source ?? {};
if (source.preflight_report_sha256 !== preflight.sha256) {
  errors.push('bound-preflight-hash');
}
if (source.entity_split_report_sha256 !== entity.sha256) {
  errors.push('bound-entity-hash');
}
if (source.entity_split_seed !== entityPayload.protocol?.seed) {
  errors.push('bound-entity-seed');
}
if (canonical(source.entity_overlap_counts) !== canonical(overlaps)) {
  errors.push('bound-overlap-counts');
}

const benchmarkGates = payload.python_gate_checks ?? {};
for (const key of [
  'preflight_pass',
  'entity_split_pass',
  'zero_entity_overlap',
  'entity_split_source_hash_exact',
  'entity_split_positive_event_sufficiency',
]) {
  if (benchmarkGates[key] !== true) errors.push(`benchmark-gate-${key}`);
}
if (payload.absolute_score?.before !== 423 || payload.absolute_score?.after !== 423) {
  errors.push('score-boundary');
}
if (payload.absolute_score?.delta !== 0) errors.push('score-delta');

const uniqueErrors = [...new Set(errors)].sort();
const receiptPayload = {
  schema: 'fin-abs-004/fdic-boundary-node-receipt/1',
  valid: uniqueErrors.length === 0,
  errors: uniqueErrors,
  benchmark_sha256: benchmark.sha256 ?? null,
  benchmark_file_sha256: shaFile(reportPath),
  preflight_sha256: preflight.sha256 ?? null,
  preflight_file_sha256: shaFile(preflightPath),
  entity_split_sha256: entity.sha256 ?? null,
  entity_split_file_sha256: shaFile(entityPath),
  entity_overlap_counts: overlaps,
  performance_candidate_pass: payload.performance_candidate_pass ?? false,
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
