import fs from 'node:fs';
import crypto from 'node:crypto';

const contractPath = process.argv[2] ?? 'fin_rvi_002_g09/final_contract_v2.json';
const outputPath = process.argv[3] ?? 'reports/fin_rvi_002_g09_v3/node_final_contract_receipt.json';
const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const digest = value => crypto.createHash('sha256').update(canonical(value), 'utf8').digest('hex');
const errors = [];
const requiredGates = [
  'g07_operational_utility',
  'stage4_independent_code_disjoint_cohort',
  'stage5_clean_reconstruction',
  'systematic_primary_prior_art_closure',
  'claim_scope_audit',
  'stage6_third_code_disjoint_cohort',
  'stage6_independent_policy_implementation',
  'stage7_third_cohort_clean_reconstruction',
];
const requiredExclusions = new Set([
  'legality','fraud','corruption','physical receipt','quality','liquidation',
  'causal impact','global universality','novelty of entity resolution',
  'novelty of procurement knowledge graphs','novelty of active evidence acquisition',
]);
const requiredAbsorbed = new Set([
  'public payment ingestion and record linkage',
  'procurement supplier reconciliation',
  'procurement-company-spending knowledge graphs',
  'many-to-many purchase-to-pay cardinality',
  'documentary audit evidence for payment',
  'active and agentic evidence acquisition',
  'cost-aware sequential entity resolution',
  'provenance-bearing governed match assertions',
  'false-positive-aware procurement red flags',
  'contract-payment reconciliation and accounts-payable exception handling',
]);
const sameSet = (values, expected) => Array.isArray(values) && values.length === expected.size && values.every(value => expected.has(value));
const isHash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);

if (contract.schema !== 'fin-rvi-002/g09-final-contract/2') errors.push('schema');
if (contract.claim_id !== 'FIN-RVI-002-C1-BOUNDED') errors.push('claim-id');
if (!['OPEN','PASS','FALSIFIED'].includes(contract.status)) errors.push('status');
if (contract.canonical_score_before !== 920) errors.push('score-before');
if (contract.gate_points !== 80) errors.push('gate-points');
const claim = String(contract.claim ?? '');
for (const phrase of [
  'multiple preregistered, mutually shared-code-disjoint',
  'public Honduras ONCAE-SEFIN cohorts',
  'exact contract/project-code blocking',
  'compatible supplier identity',
  'fixed fail-closed documentary policy',
  'maximum claim CONTRACTOR_PAYMENT',
  'reduces unsupported payment attribution',
  'without reducing recovery of supported payments',
  'one-to-many contract-payment cardinality',
  'independent policy implementation',
  'clean public reconstruction',
]) if (!claim.includes(phrase)) errors.push('claim-specificity');
if (/proves fraud|proves corruption|first ever entity resolution|first procurement knowledge graph|\buniversal\b/i.test(claim)) errors.push('claim-expansion');
const scope = contract.scope ?? {};
if (scope.country !== 'Honduras') errors.push('country');
if (scope.period !== '2023-2025') errors.push('period');
if (scope.claim_level !== 'CONTRACTOR_PAYMENT') errors.push('claim-level');
if (!sameSet(scope.excluded_claims, requiredExclusions)) errors.push('excluded-claims');
if (contract.strong_baseline !== 'B1_CODE_SUPPLIER') errors.push('strong-baseline');
if (contract.challenger !== 'FIN-RVI-002-DOCUMENTARY-V3') errors.push('challenger');
if (!Array.isArray(contract.exclusive_predictions) || contract.exclusive_predictions.length < 6 || new Set(contract.exclusive_predictions).size !== contract.exclusive_predictions.length) errors.push('predictions');
if (!Array.isArray(contract.falsifiers) || contract.falsifiers.length < 7 || new Set(contract.falsifiers).size !== contract.falsifiers.length) errors.push('falsifiers');

const gates = contract.required_gates ?? {};
if (Object.keys(gates).sort().join('|') !== [...requiredGates].sort().join('|')) errors.push('required-gates');
for (const value of Object.values(gates)) if (!['PASS','PENDING','FAIL','FALSIFIED'].includes(value)) errors.push('gate-values');
for (const gate of requiredGates.slice(0,5)) if (gates[gate] !== 'PASS') errors.push(`gate-${gate}`);

const evidence = contract.empirical_evidence ?? {};
const stage4 = evidence.stage4 ?? {};
if (stage4.head_sha !== '9e6686204fce20bc21d17f041d506a2a9c92761d' || stage4.run_id !== 30841561243 || stage4.artifact_id !== 8867231467 || stage4.artifact_sha256 !== 'a1a4a2e7dd3a722ce9b1dac9b5dbe02a5bfde0f7bd63c9e5fb6974c056de3928') errors.push('stage4-source');
if (stage4.cohort_rows !== 120 || stage4.prior_shared_codes_excluded !== 118) errors.push('stage4-cohort');
if (canonical(stage4.labels) !== canonical({SUPPORTED:58,REJECTED:28,UNRESOLVED:34})) errors.push('stage4-labels');
if (stage4.baseline?.unsafe_overpromotions !== 20 || stage4.baseline?.supported_recovered !== 58) errors.push('stage4-baseline');
if (stage4.challenger?.unsafe_overpromotions !== 0 || stage4.challenger?.supported_recovered !== 58 || stage4.challenger?.missed_supported !== 0) errors.push('stage4-challenger');
if (stage4.permutation?.unsafe_overpromotions !== 21 || stage4.permutation?.supported_recovered !== 37) errors.push('stage4-permutation');

const stage5 = evidence.stage5 ?? {};
for (const [field, expected] of Object.entries({
  head_sha:'d9928f064d0ff80084d46c9fae73d7717dffbfbd',
  run_id:30844453922,
  artifact_id:8868335548,
  artifact_sha256:'53920001230a0ea13f3929f0abcdf529653759a8e869dd1707499029ba867462',
  python_receipt_sha256:'03e97d0eb13ad7808a1a78f37ff2e8d16695ca092ccf3ed76f7cd12a78b795be',
  node_receipt_sha256:'3fa82f11d111d97e3b5fcaf58680a413f1482e01744e336cd5e64fa0c33d72d6',
  compact_rows_sha256:'5793b9d1f88176b9ba3b61a006510766041572502a6ad0595e05fc2869f71571',
  labels_sha256:'949b6e8d0ad035130cb47d2e7c97a5f4176ea5d9bbcdb7dbc7b0444c22754a1f',
  candidate_ids_sha256:'7352d9e05195fe597a4b8001192f39f7e540a0ee8799d0b0e940c73dff2354db',
  g07:'PASS',score_after:920,
})) if (stage5[field] !== expected) errors.push(`stage5-${field}`);

const boundary = contract.prior_art_boundary ?? {};
if (!sameSet(boundary.absorbed_components, requiredAbsorbed)) errors.push('prior-art-absorbed');
if (boundary.interpretation !== 'No exact hit in searched corpora is not proof of global novelty.') errors.push('prior-art-interpretation');
const closurePath = boundary.closure_file;
if (typeof closurePath !== 'string' || !fs.existsSync(closurePath)) {
  errors.push('prior-art-file');
} else {
  const closure = JSON.parse(fs.readFileSync(closurePath, 'utf8'));
  if (closure.schema !== 'fin-rvi-002/g09-prior-art-closure/2') errors.push('prior-art-schema');
  if (closure.claim_id !== contract.claim_id) errors.push('prior-art-claim-id');
  if (closure.status !== boundary.searched_status) errors.push('prior-art-status');
  if (closure.cut_date !== boundary.search_cut) errors.push('prior-art-cut');
  if (!String(closure.interpretation ?? '').includes('not proof of global novelty')) errors.push('prior-art-caution');
  if (!Array.isArray(closure.absorbed_primary_prior_art) || closure.absorbed_primary_prior_art.length < 10) errors.push('prior-art-primary-sources');
  if (!Array.isArray(closure.searched_corpora) || closure.searched_corpora.length < 4) errors.push('prior-art-corpora');
  const bounded = String(closure.bounded_remaining_claim ?? '');
  for (const phrase of [
    'multiple preregistered, mutually code-disjoint public Honduras ONCAE-SEFIN cohorts',
    'exact contract/project-code blocking','compatible supplier identity',
    'fixed fail-closed documentary policy','maximum claim CONTRACTOR_PAYMENT',
    'reduces unsupported payment attribution','without reducing recovery of supported payments',
    'preserving one-to-many contract-payment cardinality','strong baselines',
    'monetary amount at risk','permutation controls','independent clean replay',
  ]) if (!bounded.includes(phrase)) errors.push('prior-art-claim-boundary');
}

function verifyStage6(stage, required) {
  if (stage == null) { if (required) errors.push('stage6-missing'); return; }
  if (stage.status !== 'PASS' || stage.cohort_rows !== 120 || stage.prior_shared_codes_excluded !== 237 || stage.prior_shared_codes_sha256 !== '927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984') errors.push('stage6-core');
  if (!(stage.baseline?.unsafe_overpromotions > 0)) errors.push('stage6-baseline');
  if (stage.challenger?.unsafe_overpromotions !== 0 || stage.challenger?.missed_supported !== 0 || stage.challenger?.supported_recovered !== stage.baseline?.supported_recovered) errors.push('stage6-result');
  if (stage.independent_policy_mismatches !== 0) errors.push('stage6-independent-policy');
  for (const field of ['artifact_sha256','report_payload_sha256','compact_rows_sha256','labels_sha256','node_receipt_sha256','independent_policy_decisions_sha256']) if (!isHash(stage[field])) errors.push(`stage6-${field}`);
}
function verifyStage7(stage, required) {
  if (stage == null) { if (required) errors.push('stage7-missing'); return; }
  if (stage.status !== 'PASS' || stage.g09_replication !== 'PASS' || stage.cohort_rows !== 120 || stage.policy_unsafe_overpromotions !== 0 || stage.policy_missed_supported !== 0 || stage.python_node_agreement !== true || stage.tamper_controls_rejected !== true) errors.push('stage7-core');
  for (const field of ['artifact_sha256','python_receipt_sha256','node_receipt_sha256','compact_rows_sha256','labels_sha256','candidate_ids_sha256']) if (!isHash(stage[field])) errors.push(`stage7-${field}`);
}
const finalRequired = contract.status === 'PASS';
verifyStage6(evidence.stage6, finalRequired);
verifyStage7(evidence.stage7, finalRequired);

const readout = contract.gate_readout ?? {};
if (readout.G07 !== 'PASS') errors.push('readout-g07');
if (contract.status === 'PASS') {
  if (requiredGates.some(gate => gates[gate] !== 'PASS')) errors.push('premature-pass');
  if (canonical(readout) !== canonical({G07:'PASS',G09:'PASS',finance_score:1000})) errors.push('pass-readout');
} else if (contract.status === 'OPEN') {
  if (requiredGates.every(gate => gates[gate] === 'PASS')) errors.push('stale-open');
  if (readout.G09 === 'PASS' || readout.finance_score !== 920) errors.push('premature-score');
} else if (readout.G09 === 'PASS' || readout.finance_score !== 920) errors.push('falsified-score');

const uniqueErrors = [...new Set(errors)].sort();
const passed = requiredGates.filter(gate => gates[gate] === 'PASS').length;
const promotion = uniqueErrors.length === 0 && contract.status === 'PASS' && passed === requiredGates.length;
const payload = {
  schema:'fin-rvi-002/g09-final-contract-node-receipt/3',
  claim_id:contract.claim_id,
  contract_sha256:digest(contract),
  valid:uniqueErrors.length === 0,
  errors:uniqueErrors,
  status:contract.status,
  passed_required_gates:passed,
  total_required_gates:requiredGates.length,
  promotion_allowed:promotion,
  gate_readout:promotion ? {G07:'PASS',G09:'PASS',finance_score:1000} : {G07:'PASS',G09:'OPEN',finance_score:920},
};
const receipt = {payload,sha256:digest(payload)};
fs.mkdirSync(outputPath.split('/').slice(0,-1).join('/') || '.', {recursive:true});
fs.writeFileSync(outputPath, `${JSON.stringify(receipt,null,2)}\n`);
console.log(JSON.stringify(receipt));
process.exit(uniqueErrors.length === 0 ? 0 : 1);
