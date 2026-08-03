#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [promotionPath, basePath, pythonStage7Path, nodeStage7Path, pythonFinalPath, legacyNodePath, outputPath] = process.argv.slice(2);
if (![promotionPath, basePath, pythonStage7Path, nodeStage7Path, pythonFinalPath, legacyNodePath, outputPath].every(Boolean)) {
  console.error('usage: verify_final_promotion_v4.mjs <promotion> <base> <stage7-python> <stage7-node> <python-final> <legacy-node> <output>');
  process.exit(2);
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const digest = value => crypto.createHash('sha256').update(canonical(value), 'utf8').digest('hex');
const rawDigest = path => crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex');
const read = path => JSON.parse(fs.readFileSync(path, 'utf8'));
const equal = (a, b) => canonical(a) === canonical(b);
const isHash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const sameSet = (values, expected) => Array.isArray(values) && values.length === expected.size && values.every(value => expected.has(value));

const promotion = read(promotionPath);
const base = read(basePath);
const pyStage7 = read(pythonStage7Path);
const nodeStage7 = read(nodeStage7Path);
const pyFinal = read(pythonFinalPath);
const legacyNode = read(legacyNodePath);
const manifestPath = promotion.stage7_manifest_file;
const manifest = read(manifestPath);

const expectedGates = {
  g07_operational_utility: 'PASS',
  stage4_independent_code_disjoint_cohort: 'PASS',
  stage5_clean_reconstruction: 'PASS',
  systematic_primary_prior_art_closure: 'PASS',
  claim_scope_audit: 'PASS',
  stage6_third_code_disjoint_cohort: 'PASS',
  stage6_independent_policy_implementation: 'PASS',
  stage7_third_cohort_clean_reconstruction: 'PASS',
};
const expectedReadout = {G07: 'PASS', G09: 'PASS', finance_score: 1000};
const expectedOpen = {
  head_sha: '27c35d6833d8ff3cdc73f8a308eae4fe50422eec',
  run_id: 30847916495,
  artifact_id: 8869425757,
  artifact_sha256: '4467ebf198d15e199afc64180bf456d2ee0166b3520b01c9f4f9dccb1d60417b',
  contract_sha256: '5e1bde35b3cddb0e77a0eb8cb72482d1582e3578854fa4ec959e19f1b444526f',
  python_receipt_sha256: 'ea9edeb832608cf9f30806c00abba9c09cdfe77a3c88aa463afd8456bd0b9919',
  node_receipt_sha256: '780d25a90e0e41b333ae49c9b32ce5396c36f4c2d1f54db0a6abe5e882ce87bf',
  scope_audit_receipt_sha256: 'e1fd5faae0ec3e7aa5a52de151f188101d84f43692e515709b1f6cb2f36e9add',
};
const replay = {
  compact: '90e26745ced9dafd81249edb39ffbd4c10f0b64a5c6855eadf6053c4abf503e3',
  labels: 'fc3a33ba87ecc29a909717e4702ea3e281d5461fa2c5d45e242f9be8a4dc7f2a',
  exclusion: 'b4aa12fdf1126e11512579c71ce2a38f109aecbdac0081758951c2757f99103a',
  candidateIds: 'd259ec1f3cccae2dc0756ce6b318253359970ca759e89fce92d36b5336ca1aa4',
  decisions: '3f4999ae8d4282f6a71c25fe790ca28cad1fd7549fdb07f17a2bbdd209bbff0b',
};
const expectedMetrics = {
  B1_CODE_SUPPLIER: {labeled_rows:91,promotions:82,supported_recovered:63,unsafe_overpromotions:19,missed_supported:0,correct_rejections:9},
  POLICY_DOCUMENTARY: {labeled_rows:91,promotions:63,supported_recovered:63,unsafe_overpromotions:0,missed_supported:0,correct_rejections:28},
};
const exclusions = new Set([
  'legality','fraud','corruption','physical receipt','quality','liquidation',
  'causal impact','global universality','novelty of entity resolution',
  'novelty of procurement knowledge graphs','novelty of active evidence acquisition',
]);

function receiptChecks(receipt, schema, node) {
  const payload = receipt.payload || {};
  const gates = payload.gates || {};
  const replayBlock = payload.replay || {};
  return {
    self_hash: digest(payload) === receipt.sha256,
    schema: payload.schema === schema,
    gates: Object.keys(gates).length > 0 && Object.values(gates).every(Boolean),
    metrics: equal(payload.policy_metrics, expectedMetrics),
    readout: equal(payload.gate_readout, {G07:'PASS',G09_REPLICATION:'PASS',G09:'OPEN_FINAL_CONTRACT_PROMOTION_REQUIRED',finance_score:920}),
    compact: replayBlock.compact_file_sha256 === replay.compact,
    labels: replayBlock.labels_file_sha256 === replay.labels,
    exclusion: replayBlock.exclusion_manifest_file_sha256 === replay.exclusion,
    ids: replayBlock.candidate_ids_sha256 === replay.candidateIds,
    decisions: replayBlock[node ? 'independent_policy_decisions_sha256' : 'independent_node_policy_decisions_sha256'] === replay.decisions,
  };
}

const pyChecks = receiptChecks(pyStage7, 'fin-rvi-002/stage7-clean-reconstruction/1', false);
const nodeChecks = receiptChecks(nodeStage7, 'fin-rvi-002/stage7-node-clean-reconstruction/1', true);
const errors = [];
if (promotion.schema !== 'fin-rvi-002/g09-final-promotion/4') errors.push('schema');
if (promotion.claim_id !== 'FIN-RVI-002-C1-BOUNDED') errors.push('claim-id');
if (promotion.status !== 'PASS') errors.push('status');
if (promotion.score_before !== 920 || promotion.gate_points !== 80 || promotion.score_after !== 1000) errors.push('score');
if (!equal(promotion.gate_readout, expectedReadout)) errors.push('readout');
if (!equal(promotion.final_gates, expectedGates)) errors.push('final-gates');
if (!equal(promotion.open_contract, expectedOpen)) errors.push('open-contract');
if (digest(base) !== expectedOpen.contract_sha256) errors.push('base-contract-hash');
if (promotion.claim !== base.claim) errors.push('claim-drift');
if (!equal(promotion.scope, base.scope)) errors.push('scope-drift');
if (!sameSet(promotion.scope?.excluded_claims, exclusions)) errors.push('scope-exclusions');
if (!String(promotion.novelty_boundary || '').includes('not proof of global novelty')) errors.push('novelty-boundary');
if (!String(promotion.novelty_boundary || '').includes('historical priority')) errors.push('priority-boundary');

const stage6 = promotion.stage6 || {};
if (stage6.status !== 'PASS' || stage6.head_sha !== '9beb7ec13e09674ea95d7a517f038acb37b9653b' || stage6.run_id !== 30847688470 || stage6.artifact_id !== 8869552099 || stage6.artifact_sha256 !== 'ad221e7cafb7fc8d11afb5e53f486842788f0fa5a423fbdb9891f9dc7824dfaf') errors.push('stage6-source');
if (stage6.cohort_rows !== 120 || stage6.prior_shared_codes_excluded !== 237 || stage6.prior_shared_codes_sha256 !== '927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984') errors.push('stage6-cohort');
if (stage6.baseline?.unsafe_overpromotions !== 19 || stage6.baseline?.supported_recovered !== 63) errors.push('stage6-baseline');
if (stage6.challenger?.unsafe_overpromotions !== 0 || stage6.challenger?.supported_recovered !== 63 || stage6.challenger?.missed_supported !== 0) errors.push('stage6-challenger');
if (stage6.independent_policy_mismatches !== 0 || stage6.independent_policy_decisions_sha256 !== replay.decisions) errors.push('stage6-independent');
for (const field of ['artifact_sha256','report_payload_sha256','compact_rows_sha256','labels_sha256','candidate_ids_sha256','node_receipt_sha256','independent_policy_decisions_sha256']) if (!isHash(stage6[field])) errors.push(`stage6-${field}`);

if (!equal(manifest, promotion.stage7?.run_manifest)) errors.push('stage7-manifest');
if (rawDigest(pythonStage7Path) !== manifest.python_receipt_file_sha256) errors.push('stage7-python-file');
if (rawDigest(nodeStage7Path) !== manifest.node_receipt_file_sha256) errors.push('stage7-node-file');
if (pyStage7.sha256 !== manifest.python_receipt_sha256) errors.push('stage7-python-hash');
if (nodeStage7.sha256 !== manifest.node_receipt_sha256) errors.push('stage7-node-hash');
for (const [name, checks] of [['python',pyChecks],['node',nodeChecks]]) for (const [gate, value] of Object.entries(checks)) if (!value) errors.push(`stage7-${name}-${gate}`);

const legacyPayload = legacyNode.payload || {};
if (digest(legacyPayload) !== legacyNode.sha256 || legacyPayload.valid !== true || legacyPayload.promotion_allowed !== true || !equal(legacyPayload.gate_readout, expectedReadout)) errors.push('legacy-node-promotion');
const finalPayload = pyFinal.payload || {};
if (digest(finalPayload) !== pyFinal.sha256 || finalPayload.valid !== true || finalPayload.promotion_allowed !== true || !equal(finalPayload.gate_readout, expectedReadout)) errors.push('python-final-promotion');

const unique = [...new Set(errors)].sort();
const valid = unique.length === 0;
const payload = {
  schema: 'fin-rvi-002/g09-final-promotion-node-receipt/4',
  claim_id: promotion.claim_id,
  promotion_contract_sha256: digest(promotion),
  base_contract_sha256: digest(base),
  valid,
  errors: unique,
  promotion_allowed: valid,
  gate_readout: valid ? expectedReadout : {G07:'PASS',G09:'OPEN',finance_score:920},
  boundary: 'Independent Node authorization of 1000/1000 only within the declared finance gate rubric; no global novelty or historical-priority claim.',
};
const receipt = {payload, sha256:digest(payload)};
fs.mkdirSync(outputPath.split('/').slice(0,-1).join('/') || '.', {recursive:true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt,null,2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(valid ? 0 : 2);
