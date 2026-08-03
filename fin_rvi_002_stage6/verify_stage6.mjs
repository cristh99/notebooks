import fs from 'node:fs';
import crypto from 'node:crypto';

const reportPath = process.argv[2] || 'reports/fin_rvi_002_stage6/report.json';
const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
function digest(value) {
  return crypto.createHash('sha256').update(canonical(value)).digest('hex');
}

const payload = report.payload || {};
const stage6 = payload.stage6 || {};
const rows = [...(stage6.compact_rows || [])].sort((a,b)=>a.candidate_id.localeCompare(b.candidate_id));
const labeled = rows.filter(row => row.label === 'SUPPORTED' || row.label === 'REJECTED');
const excluded = new Set(stage6.source_stage34_manifest?.shared_codes || []);
const codeCounts = new Map();
for (const row of rows) codeCounts.set(row.shared_code, (codeCounts.get(row.shared_code) || 0) + 1);

function independentPolicyV3(row) {
  const hardConflict = Boolean(row.hard_category_conflict);
  const classificationSupport = Array.isArray(row.shared_classifications) && row.shared_classifications.length > 0;
  const tokenCount = Number(row.shared_object_token_count || 0);
  if (row.numeric_conflict) {
    return {decision:'REJECTED', reason:'V3_NUMERIC_SUPPLIER_CONFLICT_VETO'};
  }
  if (
    row.exact_numeric_support && row.payment_language && !hardConflict &&
    (tokenCount >= 2 || classificationSupport)
  ) {
    return {decision:'SUPPORTED', reason:'V3_EXACT_ID_PAYMENT_AND_OBJECT_SUPPORT'};
  }
  if (
    row.base_v2_decision === 'SUPPORTED' && row.name_support &&
    row.payment_language && !hardConflict &&
    (tokenCount >= 6 || classificationSupport)
  ) {
    return {decision:'SUPPORTED', reason:'V3_NAME_PAYMENT_AND_STRONG_OBJECT_SUPPORT'};
  }
  if (hardConflict) {
    return {decision:'REJECTED', reason:'V3_HARD_OBJECT_CONFLICT'};
  }
  return {decision:'UNRESOLVED', reason:'V3_INSUFFICIENT_JOINT_EVIDENCE'};
}

const independentPolicyRows = rows.map(row => ({
  candidate_id: row.candidate_id,
  expected_decision: row.policy_decision,
  expected_reason: row.policy_reason,
  ...independentPolicyV3(row),
}));
const independentPolicyMismatches = independentPolicyRows.filter(
  row => row.decision !== row.expected_decision || row.reason !== row.expected_reason
);

function metrics(policy) {
  const promotes = policy === 'B1_CODE_SUPPLIER'
    ? row => Boolean(row.baseline_supplier_support)
    : row => independentPolicyV3(row).decision === 'SUPPORTED';
  const promoted = labeled.filter(promotes);
  return {
    labeled_rows: labeled.length,
    promotions: promoted.length,
    supported_recovered: promoted.filter(row=>row.label==='SUPPORTED').length,
    unsafe_overpromotions: promoted.filter(row=>row.label==='REJECTED').length,
    missed_supported: labeled.filter(row=>row.label==='SUPPORTED' && !promotes(row)).length,
    correct_rejections: labeled.filter(row=>row.label==='REJECTED' && !promotes(row)).length,
  };
}
const calculated = {
  B1_CODE_SUPPLIER: metrics('B1_CODE_SUPPLIER'),
  POLICY_DOCUMENTARY: metrics('POLICY_DOCUMENTARY'),
};
const labelCounts = rows.reduce((acc,row)=>{acc[row.label]=(acc[row.label]||0)+1; return acc;},{});
const packages = new Map((payload.downloads || []).map(item=>[`${item.source}:${item.year}`,item.sha256]));
const expectedPackages = new Map([
  ['ONCAE:2023','db9a76958a069ff5fc47b6f68caf59a74174efcbebcca0458d0f4a08cf00683d'],
  ['SEFIN:2023','9bae4bcef17c618137901f1f9b7a548ab734a7195cb92aaddeb34b2a49b1ced6'],
  ['ONCAE:2024','43e12ce76ba1fcd3bf1240ffea4e246126bdcc2832d3d77bcb7415d8a1195c37'],
  ['SEFIN:2024','f41f2f9b11ab8e6ccd185ab2c7e193a7107bd1b12f25d33a14946589d5dccd47'],
  ['ONCAE:2025','aa33b9b591fabce5f2397b5966b67ba7fc6471bf8b394ceb5c2aeec707f6cb06'],
  ['SEFIN:2025','3971d50d45b21ea97dbdaf05b70cd38f674765a9d70f2ed30e80d7b9a5d25db5'],
]);
const packagesExact = packages.size === expectedPackages.size && [...expectedPackages].every(([k,v])=>packages.get(k)===v);
const gateChecks = stage6.gate_checks || {};
const independence = stage6.independence_contract || {};
const gates = {
  report_hash: digest(payload) === report.sha256,
  schema: payload.schema === 'fin-rvi-002/stage6-third-sealed-cohort/1',
  candidate_universe: payload.candidate_reconstruction?.candidate_count === 2295,
  official_packages_exact: packagesExact,
  cohort_size: rows.length === 120,
  enough_supported: (labelCounts.SUPPORTED || 0) >= 20,
  enough_rejected: (labelCounts.REJECTED || 0) >= 5,
  independent_policy_facts_present: rows.every(row => typeof row.base_v2_decision === 'string'),
  independent_policy_exact_match: independentPolicyMismatches.length === 0,
  metrics_match: canonical(calculated) === canonical(stage6.policy_metrics),
  all_source_gates: Object.values(gateChecks).every(Boolean),
  zero_unsafe: calculated.POLICY_DOCUMENTARY.unsafe_overpromotions === 0,
  no_recovery_loss: calculated.POLICY_DOCUMENTARY.supported_recovered === calculated.B1_CODE_SUPPLIER.supported_recovered && calculated.POLICY_DOCUMENTARY.missed_supported === 0,
  strict_safety_improvement: calculated.B1_CODE_SUPPLIER.unsafe_overpromotions > calculated.POLICY_DOCUMENTARY.unsafe_overpromotions,
  policy_fixed: stage6.policy_id === 'FIN-RVI-002-DOCUMENTARY-V3',
  excluded_prior_codes: excluded.size === 237 && rows.every(row=>!excluded.has(row.shared_code)),
  exclusion_hash: stage6.source_stage34_manifest?.shared_codes_sha256 === '927ca1f2b780b6d34e37cd2d482a766c33a58781eacf121ac581a73ad2960984',
  code_cardinality_cap: Math.max(...codeCounts.values()) <= 2,
  independence_contract: independence.stage3_and_stage4_shared_codes_excluded === true && independence.policy_v3_unchanged_from_stage4 === true && independence.labeler_unchanged_from_stage3 === true && independence.selection_seed_new === true && independence.exclusions_derived_without_outcome_access === true && independence.independent_policy_facts_exported === true,
  gate_candidate: stage6.gate_status === 'PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION',
  g09_not_premature: payload.gate_readout?.G09 === 'OPEN_PRIOR_ART_AND_CLEAN_REPLAY_REQUIRED',
};
if (!Object.values(gates).every(Boolean)) {
  console.error(JSON.stringify({valid:false,gates,labelCounts,calculated,independentPolicyMismatches},null,2));
  process.exit(2);
}
const receiptPayload = {
  schema:'fin-rvi-002/stage6-node-independent-policy-receipt/2',
  report_payload_sha256: report.sha256,
  compact_rows_sha256: digest(rows),
  excluded_codes_sha256: stage6.source_stage34_manifest?.shared_codes_sha256,
  label_counts: labelCounts,
  policy_metrics: calculated,
  independent_policy_decisions_sha256: digest(independentPolicyRows),
  gates,
};
const receipt = {payload:receiptPayload,sha256:digest(receiptPayload)};
const output = reportPath.replace(/report\.json$/, 'stage6_node_receipt.json');
fs.writeFileSync(output, `${JSON.stringify(receipt,null,2)}\n`);
console.log(JSON.stringify({valid:true,receipt_sha256:receipt.sha256,label_counts:labelCounts,policy_metrics:calculated,independent_policy_sha256:receiptPayload.independent_policy_decisions_sha256}));
