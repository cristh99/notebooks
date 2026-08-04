#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [preflightPath, panelPath, panelReportPath, outputPath] = process.argv.slice(2);
if (![preflightPath, panelPath, panelReportPath, outputPath].every(Boolean)) {
  console.error('usage: verify_preflight.mjs <preflight> <panel> <panel-report> <output>');
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

async function shaFile(path) {
  return await new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(path);
    stream.on('data', chunk => hash.update(chunk));
    stream.on('error', reject);
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

async function main() {
  const report = JSON.parse(fs.readFileSync(preflightPath, 'utf8'));
  const panelReport = JSON.parse(fs.readFileSync(panelReportPath, 'utf8'));
  const payload = report.payload ?? {};
  const errors = [];

  if (payload.schema !== 'fin-abs-004b/fdic-temporal-preflight/1') errors.push('schema');
  if (shaText(report.payload_canonical ?? '') !== report.sha256) errors.push('report-hash');
  try {
    if (canonical(JSON.parse(report.payload_canonical)) !== canonical(payload)) errors.push('canonical-payload');
  } catch {
    errors.push('canonical-json');
  }
  if (payload.status !== 'PASS_TEMPORAL_PREFLIGHT') errors.push('status');
  if (payload.deployment_contract?.generalization_axis !== 'future_calendar_regimes') errors.push('generalization-axis');
  if (payload.deployment_contract?.unseen_entity_superiority_claimed !== false) errors.push('unseen-entity-boundary');
  if (Number(payload.deployment_contract?.label_horizon_days) !== 730) errors.push('label-horizon');

  const score = payload.absolute_score ?? {};
  if (canonical(score) !== canonical({
    before: 423,
    after: 423,
    delta: 0,
    boundary: 'Temporal preflight only; no model performance evaluated.',
  })) errors.push('score-boundary');

  const gates = payload.gate_checks ?? {};
  if (Object.keys(gates).length < 14 || !Object.values(gates).every(Boolean)) errors.push('gate-checks');
  const counts = payload.split_counts ?? {};
  if (Number(counts.validation?.positive_rows ?? 0) < 20) errors.push('validation-positive-rows');
  if (Number(counts.test?.positive_rows ?? 0) < 100) errors.push('test-positive-rows');
  const recurrence = payload.entity_recurrence_counts ?? {};
  for (const key of ['train_validation', 'train_test', 'validation_test']) {
    if (!Number.isInteger(recurrence[key]) || recurrence[key] < 0) errors.push(`recurrence-${key}`);
  }

  const panelSha = await shaFile(panelPath);
  if (panelSha !== payload.panel_file_sha256) errors.push('panel-file-sha');
  if (panelSha !== panelReport.payload?.evaluation_panel?.feature_file_sha256) errors.push('panel-report-file-sha');
  if (panelReport.sha256 !== payload.panel_report_sha256) errors.push('panel-report-reference');
  if (shaText(panelReport.payload_canonical ?? '') !== panelReport.sha256) errors.push('panel-report-hash');

  const uniqueErrors = [...new Set(errors)].sort();
  const receiptPayload = {
    schema: 'fin-abs-004b/fdic-temporal-preflight-node-receipt/1',
    valid: uniqueErrors.length === 0,
    errors: uniqueErrors,
    report_sha256: report.sha256,
    panel_sha256: panelSha,
    panel_report_sha256: panelReport.sha256,
    split_counts: counts,
    entity_recurrence_counts: recurrence,
    absolute_score: score,
  };
  const receipt = {payload: receiptPayload, sha256: shaText(canonical(receiptPayload))};
  fs.mkdirSync(outputPath.split('/').slice(0, -1).join('/') || '.', {recursive: true});
  fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
  console.log(JSON.stringify(receipt));
  process.exit(uniqueErrors.length === 0 ? 0 : 1);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
