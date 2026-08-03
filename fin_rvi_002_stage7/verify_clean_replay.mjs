#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [reportPath, rowsPath, labelsPath, stage6NodePath, exclusionPath, pythonReceiptPath, outputPath] = process.argv.slice(2);
if (![reportPath, rowsPath, labelsPath, stage6NodePath, exclusionPath, pythonReceiptPath, outputPath].every(Boolean)) {
  console.error('usage: verify_clean_replay.mjs <report> <rows> <labels> <stage6-node> <exclusion> <python-receipt> <output>');
  process.exit(2);
}

const EXPECTED = {
  sourceHead: '9beb7ec13e09674ea95d7a517f038acb37b9653b',
  sourceRun: 30847688470,
  sourceArtifact: 8869552099,
  sourceArtifactSha256: 'ad221e7cafb7fc8d11afb5e53f486842788f0fa5a423fbdb9891f9dc7824dfaf',
  compactFile: '90e26745ced9dafd81249edb39ffbd4c10f0b64a5c6855eadf6053c4abf503e3',
  labelsFile: 'fc3a33ba87ecc29a909717e4702ea3e281d5461fa2c5d45e242f9be8a4dc7f2a',
  exclusionFile: 'b4aa12fdf1126e11512579c71ce2a38f109aecbdac0081758951c2757f99103a',
  candidateIds: 'd259ec1f3cccae2dc0756ce6b318253359970ca759e89fce92d36b5336ca1aa4',
  nodeCompactLogical: 'd02f65f00435f0e0710fd44c2ad1512cc9925a6048b364c9de85722872f45890',
  policyDecisions: '3f4999ae8d4282f6a71c25fe790ca28cad1fd7549fdb07f17a2bbdd209bbff0b',
  exclusionPayload: 'd7cc93a4a1233f4e2309fe9e3bd74fd9813e460cf82b2e15ccfcdf46d1e5425c',
  exclusionCodes: '927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984',
};
const EXPECTED_PACKAGES = new Map([
  ['ONCAE:2023', 'db9a76958a069ff5fc47b6f68caf59a74174efcbebcca0458d0f4a08cf00683d'],
  ['SEFIN:2023', '9bae4bcef17c618137901f1f9b7a548ab734a7195cb92aaddeb34b2a49b1ced6'],
  ['ONCAE:2024', '43e12ce76ba1fcd3bf1240ffea4e246126bdcc2832d3d77bcb7415d8a1195c37'],
  ['SEFIN:2024', 'f41f2f9b11ab8e6ccd185ab2c7e193a7107bd1b12f25d33a14946589d5dccd47'],
  ['ONCAE:2025', 'aa33b9b591fabce5f2397b5966b67ba7fc6471bf8b394ceb5c2aeec707f6cb06'],
  ['SEFIN:2025', '3971d50d45b21ea97dbdaf05b70cd38f674765a9d70f2ed30e80d7b9a5d25db5'],
]);
const EXPECTED_LABELS = {SUPPORTED: 63, REJECTED: 28, UNRESOLVED: 29};
const EXPECTED_METRICS = {
  B1_CODE_SUPPLIER: {labeled_rows: 91, promotions: 82, supported_recovered: 63, unsafe_overpromotions: 19, missed_supported: 0, correct_rejections: 9},
  POLICY_DOCUMENTARY: {labeled_rows: 91, promotions: 63, supported_recovered: 63, unsafe_overpromotions: 0, missed_supported: 0, correct_rejections: 28},
};
const EXPECTED_PERMUTATION = {seed: 'FIN-RVI-002-STAGE3-PERMUTATION-V1', labeled_rows: 91, promotions: 63, supported_recovered: 41, unsafe_overpromotions: 22};

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
function digest(value) {
  return crypto.createHash('sha256').update(canonical(value), 'utf8').digest('hex');
}
function rawDigest(path) {
  return crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex');
}
function readJson(path) {
  return JSON.parse(fs.readFileSync(path, 'utf8'));
}
function readJsonl(path) {
  return fs.readFileSync(path, 'utf8').split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
}
function equal(left, right) {
  return canonical(left) === canonical(right);
}
function independentPolicy(row) {
  const hardConflict = Boolean(row.policy_hard_category_conflict);
  const classificationSupport = Array.isArray(row.policy_shared_classifications) && row.policy_shared_classifications.length > 0;
  const tokenCount = Number(row.policy_shared_object_token_count || 0);
  if (row.policy_numeric_conflict) return {decision: 'REJECTED', reason: 'V3_NUMERIC_SUPPLIER_CONFLICT_VETO'};
  if (row.policy_exact_numeric_support && row.policy_payment_language && !hardConflict && (tokenCount >= 2 || classificationSupport)) {
    return {decision: 'SUPPORTED', reason: 'V3_EXACT_ID_PAYMENT_AND_OBJECT_SUPPORT'};
  }
  if (row.policy_base_v2_decision === 'SUPPORTED' && row.policy_name_support && row.policy_payment_language && !hardConflict && (tokenCount >= 6 || classificationSupport)) {
    return {decision: 'SUPPORTED', reason: 'V3_NAME_PAYMENT_AND_STRONG_OBJECT_SUPPORT'};
  }
  if (hardConflict) return {decision: 'REJECTED', reason: 'V3_HARD_OBJECT_CONFLICT'};
  return {decision: 'UNRESOLVED', reason: 'V3_INSUFFICIENT_JOINT_EVIDENCE'};
}
function policyRows(rows) {
  return [...rows].sort((a, b) => a.candidate_id.localeCompare(b.candidate_id)).map(row => ({
    candidate_id: row.candidate_id,
    expected_decision: row.policy_decision,
    expected_reason: row.policy_reason,
    ...independentPolicy(row),
  }));
}
function metrics(rows) {
  const labeled = rows.filter(row => row.label === 'SUPPORTED' || row.label === 'REJECTED');
  const output = {};
  for (const name of ['B1_CODE_SUPPLIER', 'POLICY_DOCUMENTARY']) {
    const promotes = name === 'B1_CODE_SUPPLIER'
      ? row => Boolean(row.baseline_supplier_support)
      : row => independentPolicy(row).decision === 'SUPPORTED';
    const promoted = labeled.filter(promotes);
    output[name] = {
      labeled_rows: labeled.length,
      promotions: promoted.length,
      supported_recovered: promoted.filter(row => row.label === 'SUPPORTED').length,
      unsafe_overpromotions: promoted.filter(row => row.label === 'REJECTED').length,
      missed_supported: labeled.filter(row => row.label === 'SUPPORTED' && !promotes(row)).length,
      correct_rejections: labeled.filter(row => row.label === 'REJECTED' && !promotes(row)).length,
    };
  }
  return output;
}
function permutation(rows) {
  const seed = EXPECTED_PERMUTATION.seed;
  const labeled = rows
    .filter(row => row.label === 'SUPPORTED' || row.label === 'REJECTED')
    .sort((a, b) => digest(`${a.candidate_id}|${seed}`).localeCompare(digest(`${b.candidate_id}|${seed}`)));
  let decisions = labeled.map(row => row.policy_decision);
  if (decisions.length) decisions = [...decisions.slice(1), decisions[0]];
  const promoted = labeled.filter((_, index) => decisions[index] === 'SUPPORTED');
  return {
    seed,
    labeled_rows: labeled.length,
    promotions: promoted.length,
    supported_recovered: promoted.filter(row => row.label === 'SUPPORTED').length,
    unsafe_overpromotions: promoted.filter(row => row.label === 'REJECTED').length,
  };
}

const report = readJson(reportPath);
const payload = report.payload || {};
const stage6 = payload.stage6 || {};
const rows = readJsonl(rowsPath).sort((a, b) => a.candidate_id.localeCompare(b.candidate_id));
const labels = readJsonl(labelsPath).sort((a, b) => a.candidate_id.localeCompare(b.candidate_id));
const stage6Node = readJson(stage6NodePath);
const exclusion = readJson(exclusionPath);
const pythonReceipt = readJson(pythonReceiptPath);
const pythonPayload = pythonReceipt.payload || {};
const reportRows = [...(stage6.compact_rows || [])].sort((a, b) => a.candidate_id.localeCompare(b.candidate_id));
const decisions = policyRows(rows);
const mismatches = decisions.filter(row => row.decision !== row.expected_decision || row.reason !== row.expected_reason);
const calculatedMetrics = metrics(rows);
const calculatedPermutation = permutation(rows);
const labelCounts = rows.reduce((acc, row) => { acc[row.label] = (acc[row.label] || 0) + 1; return acc; }, {});
const idDigest = crypto.createHash('sha256').update(rows.map(row => row.candidate_id).join('\n'), 'utf8').digest('hex');
const labelMap = new Map(labels.map(row => [row.candidate_id, row.label]));
const labelsMatch = labels.length === 91 && labels.every(row => rows.some(candidate => candidate.candidate_id === row.candidate_id && candidate.label === row.label));
const packageMap = new Map((payload.downloads || []).map(record => [`${record.source}:${record.year}`, record.sha256]));
const packagesExact = packageMap.size === EXPECTED_PACKAGES.size && [...EXPECTED_PACKAGES].every(([key, value]) => packageMap.get(key) === value);
const excluded = new Set(stage6.source_stage34_manifest?.shared_codes || []);
const codeCounts = new Map();
for (const row of rows) codeCounts.set(row.shared_code, (codeCounts.get(row.shared_code) || 0) + 1);
const stage6NodePayload = stage6Node.payload || {};
const pythonReplay = pythonPayload.replay || {};

const gates = {
  report_payload_hash_self_consistent: typeof report.sha256 === 'string' && digest(payload) === report.sha256,
  schema: payload.schema === 'fin-rvi-002/stage6-third-sealed-cohort/1',
  official_packages_exact: packagesExact,
  candidate_universe: payload.candidate_reconstruction?.candidate_count === 2295,
  cohort_size: rows.length === reportRows.length && rows.length === 120,
  compact_file_exact: rawDigest(rowsPath) === EXPECTED.compactFile,
  labels_file_exact: rawDigest(labelsPath) === EXPECTED.labelsFile,
  exclusion_file_exact: rawDigest(exclusionPath) === EXPECTED.exclusionFile,
  candidate_ids_exact: idDigest === EXPECTED.candidateIds,
  compact_rows_node_logical_exact: digest(rows) === EXPECTED.nodeCompactLogical,
  rows_match_report: equal(rows, reportRows),
  labels_match_rows: labelsMatch && labelMap.size === 91,
  label_counts_exact: equal(labelCounts, EXPECTED_LABELS),
  policy_inputs_present: rows.every(row => [
    'policy_numeric_conflict', 'policy_exact_numeric_support', 'policy_name_support',
    'policy_payment_language', 'policy_hard_category_conflict',
    'policy_shared_object_token_count', 'policy_shared_classifications',
    'policy_base_v2_decision',
  ].every(field => Object.hasOwn(row, field))),
  independent_policy_exact: mismatches.length === 0 && digest(decisions) === EXPECTED.policyDecisions,
  policy_metrics_exact: equal(calculatedMetrics, EXPECTED_METRICS) && equal(stage6.policy_metrics, EXPECTED_METRICS),
  permutation_exact: equal(calculatedPermutation, EXPECTED_PERMUTATION) && equal(stage6.permutation_control, EXPECTED_PERMUTATION),
  source_gates_pass: Object.values(stage6.gate_checks || {}).every(Boolean),
  source_gate_candidate: stage6.gate_status === 'PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION',
  policy_fixed: stage6.policy_id === 'FIN-RVI-002-DOCUMENTARY-V3',
  prior_codes_exact: excluded.size === 237 && stage6.source_stage34_manifest?.shared_codes_sha256 === EXPECTED.exclusionCodes && stage6.source_stage34_manifest_sha256 === EXPECTED.exclusionPayload,
  prior_codes_excluded: rows.every(row => !excluded.has(row.shared_code)),
  code_cardinality_cap: Math.max(...codeCounts.values()) <= 2,
  zero_unsafe_full_recovery: calculatedMetrics.POLICY_DOCUMENTARY.unsafe_overpromotions === 0 && calculatedMetrics.POLICY_DOCUMENTARY.supported_recovered === 63 && calculatedMetrics.POLICY_DOCUMENTARY.missed_supported === 0,
  baseline_strictly_worse: calculatedMetrics.B1_CODE_SUPPLIER.unsafe_overpromotions === 19,
  stage6_node_schema: stage6NodePayload.schema === 'fin-rvi-002/stage6-node-independent-policy-receipt/3',
  stage6_node_gates: Object.values(stage6NodePayload.gates || {}).every(Boolean),
  stage6_node_policy_exact: stage6NodePayload.independent_policy_mismatches === 0 && stage6NodePayload.independent_policy_decisions_sha256 === EXPECTED.policyDecisions,
  stage6_node_metrics: equal(stage6NodePayload.policy_metrics, calculatedMetrics),
  stage6_node_labels: equal(stage6NodePayload.label_counts, labelCounts),
  python_receipt_schema: pythonPayload.schema === 'fin-rvi-002/stage7-clean-reconstruction/1',
  python_receipt_hash: digest(pythonPayload) === pythonReceipt.sha256,
  python_all_gates: Object.values(pythonPayload.gates || {}).every(Boolean),
  python_replay_files: pythonReplay.compact_file_sha256 === EXPECTED.compactFile && pythonReplay.labels_file_sha256 === EXPECTED.labelsFile && pythonReplay.exclusion_manifest_file_sha256 === EXPECTED.exclusionFile && pythonReplay.candidate_ids_sha256 === EXPECTED.candidateIds,
  python_policy_agreement: pythonReplay.independent_node_policy_decisions_sha256 === EXPECTED.policyDecisions && equal(pythonPayload.policy_metrics, calculatedMetrics),
  python_gate_readout: equal(pythonPayload.gate_readout, {G07: 'PASS', G09_REPLICATION: 'PASS', G09: 'OPEN_FINAL_CONTRACT_PROMOTION_REQUIRED', finance_score: 920}),
  g09_not_premature: payload.gate_readout?.G09 === 'OPEN_PRIOR_ART_AND_CLEAN_REPLAY_REQUIRED',
};
const valid = Object.values(gates).every(Boolean);
const receiptPayload = {
  schema: 'fin-rvi-002/stage7-node-clean-reconstruction/1',
  source: {
    head: EXPECTED.sourceHead,
    run_id: EXPECTED.sourceRun,
    artifact_id: EXPECTED.sourceArtifact,
    artifact_sha256: EXPECTED.sourceArtifactSha256,
  },
  replay: {
    report_payload_sha256: report.sha256,
    compact_file_sha256: rawDigest(rowsPath),
    labels_file_sha256: rawDigest(labelsPath),
    exclusion_manifest_file_sha256: rawDigest(exclusionPath),
    candidate_ids_sha256: idDigest,
    stage6_node_receipt_sha256: stage6Node.sha256,
    python_receipt_sha256: pythonReceipt.sha256,
    independent_policy_decisions_sha256: digest(decisions),
  },
  label_counts: labelCounts,
  policy_metrics: calculatedMetrics,
  permutation_control: calculatedPermutation,
  gates,
  gate_readout: {
    G07: 'PASS',
    G09_REPLICATION: valid ? 'PASS' : 'OPEN_CLEAN_RECONSTRUCTION_FAILED',
    G09: 'OPEN_FINAL_CONTRACT_PROMOTION_REQUIRED',
    finance_score: 920,
  },
  boundary: 'Independent Node verification of the Stage 7 clean replay; final G09 promotion remains a separate fail-closed contract action.',
};
const receipt = {payload: receiptPayload, sha256: digest(receiptPayload)};
fs.mkdirSync(new URL('.', `file://${outputPath}`).pathname, {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify({valid, receipt_sha256: receipt.sha256, mismatches: mismatches.length, gate_readout: receiptPayload.gate_readout}));
process.exit(valid ? 0 : 2);
