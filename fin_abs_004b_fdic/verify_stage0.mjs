#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [entityPath, preflightPath, panelPath, outputPath] = process.argv.slice(2);
if (![entityPath, preflightPath, panelPath, outputPath].every(Boolean)) {
  console.error('usage: verify_stage0.mjs <entity-report> <preflight-report> <panel> <output>');
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
const entity = JSON.parse(fs.readFileSync(entityPath, 'utf8'));
const preflight = JSON.parse(fs.readFileSync(preflightPath, 'utf8'));
const panelSha = shaFile(panelPath);
const errors = [];

for (const [name, report] of [['entity', entity], ['preflight', preflight]]) {
  if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push(`${name}-hash`);
  try {
    if (canonical(JSON.parse(report.payload_canonical)) !== canonical(report.payload)) errors.push(`${name}-canonical`);
  } catch {
    errors.push(`${name}-canonical-json`);
  }
}
const ep = entity.payload ?? {};
const pp = preflight.payload ?? {};
if (ep.schema !== 'fin-abs-004/fdic-entity-disjoint-panel/1') errors.push('entity-schema');
if (pp.schema !== 'fin-abs-004/fdic-preflight/1') errors.push('preflight-schema');
if (ep.status !== 'PASS_ENTITY_SPLIT') errors.push('entity-status');
if (pp.status !== 'PASS_PREFLIGHT') errors.push('preflight-status');
if (ep.protocol?.seed !== 'FIN-ABS-004B-ENTITY-SPLIT-V1') errors.push('seed');
if (canonical(ep.protocol?.bucket_rule) !== canonical({train:[0,19], validation:[20,29], test:[30,99]})) errors.push('bucket-rule');
if (panelSha !== ep.evaluation_panel?.feature_file_sha256) errors.push('entity-panel-file-hash');
if (panelSha !== pp.panel_file_sha256) errors.push('preflight-panel-file-hash');
if (pp.panel_report_sha256 !== entity.sha256) errors.push('report-binding');
if (!Object.values(ep.gate_checks ?? {}).every(Boolean)) errors.push('entity-gates');
if (!Object.values(pp.gate_checks ?? {}).every(Boolean)) errors.push('preflight-gates');
if (Object.values(ep.evaluation_panel?.entity_overlap_counts ?? {}).some(value => Number(value) !== 0)) errors.push('entity-overlap');
if (Object.values(pp.entity_overlap_counts ?? {}).some(value => Number(value) !== 0)) errors.push('preflight-overlap');
const expectedDates = {
  train:{start:'1992-12-31', end:'2004-12-31'},
  validation:{start:'2007-03-31', end:'2009-12-31'},
  test:{start:'2012-03-31', end:'2013-12-31'},
};
if (canonical(pp.split_dates) !== canonical(expectedDates)) errors.push('split-dates');
const counts = pp.split_counts ?? {};
if (Number(counts.train?.positive_entities ?? 0) < 30) errors.push('train-events');
if (Number(counts.validation?.positive_entities ?? 0) < 10) errors.push('validation-events');
if (Number(counts.test?.positive_entities ?? 0) < 50) errors.push('test-events');
if (canonical(ep.absolute_score) !== canonical({before:423, after:423, delta:0, boundary:'Split construction only; no model evaluated.'})) errors.push('entity-score');
if (canonical(pp.absolute_score) !== canonical({before:423, after:423, delta:0})) errors.push('preflight-score');

const uniqueErrors = [...new Set(errors)].sort();
const payload = {
  schema:'fin-abs-004b/fdic-stage0-node-receipt/1',
  valid:uniqueErrors.length === 0,
  errors:uniqueErrors,
  entity_report_sha256:entity.sha256,
  preflight_report_sha256:preflight.sha256,
  panel_file_sha256:panelSha,
  split_counts:counts,
  bucket_rule:ep.protocol?.bucket_rule ?? null,
  absolute_score:{before:423, after:423, delta:0},
};
const receipt = {payload, sha256:shaText(canonical(payload))};
fs.mkdirSync(outputPath.split('/').slice(0, -1).join('/') || '.', {recursive:true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
