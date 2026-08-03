#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';

const [reportPath, rowsPath, labelsPath, outputPath] = process.argv.slice(2);
if (!outputPath) {
  console.error('usage: verify_clean_replay.mjs report.json compact.jsonl labels.jsonl output.json');
  process.exit(2);
}

const reportBytes = fs.readFileSync(reportPath);
const rowsBytes = fs.readFileSync(rowsPath);
const labelsBytes = fs.readFileSync(labelsPath);
const report = JSON.parse(reportBytes);
const rows = rowsBytes.toString('utf8').trim().split(/\n+/).filter(Boolean).map(JSON.parse).sort((a,b)=>a.candidate_id.localeCompare(b.candidate_id));
const labels = labelsBytes.toString('utf8').trim().split(/\n+/).filter(Boolean).map(JSON.parse).sort((a,b)=>a.candidate_id.localeCompare(b.candidate_id));

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
const shaBytes = value => crypto.createHash('sha256').update(value).digest('hex');
const shaCanonical = value => shaBytes(Buffer.from(canonical(value), 'utf8'));

const expected = {
  compact: '5793b9d1f88176b9ba3b61a006510766041572502a6ad0595e05fc2869f71571',
  labels: '949b6e8d0ad035130cb47d2e7c97a5f4176ea5d9bbcdb7dbc7b0444c22754a1f',
  ids: '7352d9e05195fe597a4b8001192f39f7e540a0ee8799d0b0e940c73dff2354db',
  permutation: {
    seed: 'FIN-RVI-002-STAGE3-PERMUTATION-V1',
    labeled_rows: 86,
    promotions: 58,
    supported_recovered: 37,
    unsafe_overpromotions: 21,
  },
};

function metrics(sourceRows) {
  const labeled = sourceRows.filter(row => row.label === 'SUPPORTED' || row.label === 'REJECTED');
  const definitions = {
    B1_CODE_SUPPLIER: row => Boolean(row.baseline_supplier_support),
    POLICY_DOCUMENTARY: row => row.policy_decision === 'SUPPORTED',
  };
  const output = {};
  for (const [name, promotes] of Object.entries(definitions)) {
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

function permutation(sourceRows) {
  const seed = expected.permutation.seed;
  const labeled = sourceRows
    .filter(row => row.label === 'SUPPORTED' || row.label === 'REJECTED')
    .sort((a,b) => shaCanonical(`${a.candidate_id}|${seed}`).localeCompare(shaCanonical(`${b.candidate_id}|${seed}`)));
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

const payload = report.payload ?? {};
const stage4 = payload.stage4 ?? {};
const calculated = metrics(rows);
const recalculatedPermutation = permutation(rows);
const labelCounts = rows.reduce((acc,row)=>{acc[row.label]=(acc[row.label]??0)+1; return acc;},{});
const ids = rows.map(row => row.candidate_id);
const excluded = new Set(stage4.source_stage3_manifest?.shared_codes ?? []);
const codeCounts = new Map();
for (const row of rows) codeCounts.set(row.shared_code, (codeCounts.get(row.shared_code) ?? 0) + 1);
const reportRows = [...(stage4.compact_rows ?? [])].sort((a,b)=>a.candidate_id.localeCompare(b.candidate_id));
const downloads = new Map((payload.downloads ?? []).map(item => [`${item.source}:${item.year}`, item.sha256]));
const expectedPackages = new Map([
  ['ONCAE:2023','db9a76958a069ff5fc47b6f68caf59a74174efcbebcca0458d0f4a08cf00683d'],
  ['SEFIN:2023','9bae4bcef17c618137901f1f9b7a548ab734a7195cb92aaddeb34b2a49b1ced6'],
  ['ONCAE:2024','43e12ce76ba1fcd3bf1240ffea4e246126bdcc2832d3d77bcb7415d8a1195c37'],
  ['SEFIN:2024','f41f2f9b11ab8e6ccd185ab2c7e193a7107bd1b12f25d33a14946589d5dccd47'],
  ['ONCAE:2025','aa33b9b591fabce5f2397b5966b67ba7fc6471bf8b394ceb5c2aeec707f6cb06'],
  ['SEFIN:2025','3971d50d45b21ea97dbdaf05b70cd38f674765a9d70f2ed30e80d7b9a5d25db5'],
]);
const packagesExact = downloads.size === expectedPackages.size && [...expectedPackages].every(([key,value]) => downloads.get(key) === value);

const gates = {
  schema: payload.schema === 'fin-rvi-002/stage4-independent-policy-v3/1',
  official_packages_exact: packagesExact,
  candidate_universe: payload.candidate_reconstruction?.candidate_count === 2295,
  compact_file_exact: shaBytes(rowsBytes) === expected.compact,
  labels_file_exact: shaBytes(labelsBytes) === expected.labels,
  ids_exact: shaBytes(Buffer.from(ids.join('\n'), 'utf8')) === expected.ids,
  cohort_size: rows.length === 120 && reportRows.length === 120,
  labels_size: labels.length === 86,
  label_counts: labelCounts.SUPPORTED === 58 && labelCounts.REJECTED === 28 && labelCounts.UNRESOLVED === 34,
  labels_match_rows: labels.every(row => rows.some(candidate => candidate.candidate_id === row.candidate_id && candidate.label === row.label)),
  report_rows_match_file: canonical(rows) === canonical(reportRows),
  metrics_match_report: canonical(calculated) === canonical(stage4.policy_metrics),
  permutation_exact: canonical(recalculatedPermutation) === canonical(expected.permutation) && canonical(recalculatedPermutation) === canonical(stage4.permutation_control),
  all_stage4_gates: Object.values(stage4.gate_checks ?? {}).every(Boolean),
  zero_unsafe: calculated.POLICY_DOCUMENTARY.unsafe_overpromotions === 0,
  full_recovery: calculated.POLICY_DOCUMENTARY.supported_recovered === 58 && calculated.POLICY_DOCUMENTARY.missed_supported === 0,
  strict_improvement: calculated.B1_CODE_SUPPLIER.unsafe_overpromotions === 20,
  policy_fixed: stage4.policy_id === 'FIN-RVI-002-DOCUMENTARY-V3',
  independence: stage4.independence_contract?.stage3_shared_codes_excluded === true && stage4.independence_contract?.policy_fixed_before_stage4_outcomes === true && stage4.independence_contract?.labeler_unchanged_from_stage3 === true,
  stage3_codes_excluded: excluded.size === 118 && rows.every(row => !excluded.has(row.shared_code)),
  code_cardinality_cap: Math.max(...codeCounts.values()) <= 2,
  source_candidate: stage4.gate_status === 'PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION',
  g09_open: payload.gate_readout?.G09 === 'OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED',
};
if (!Object.values(gates).every(Boolean)) {
  console.error(JSON.stringify({valid:false,gates,calculated,recalculatedPermutation,labelCounts},null,2));
  process.exit(2);
}
const receiptPayload = {
  schema: 'fin-rvi-002/stage5-node-clean-reconstruction/1',
  source_head: '9e6686204fce20bc21d17f041d506a2a9c92761d',
  report_file_sha256: shaBytes(reportBytes),
  report_payload_sha256: report.sha256,
  compact_file_sha256: shaBytes(rowsBytes),
  labels_file_sha256: shaBytes(labelsBytes),
  candidate_ids_sha256: shaBytes(Buffer.from(ids.join('\n'), 'utf8')),
  label_counts: labelCounts,
  policy_metrics: calculated,
  permutation_control: recalculatedPermutation,
  gates,
  gate_readout: {G07:'PASS',G09:'OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED',finance_score:920},
};
const receipt = {payload: receiptPayload, sha256: shaCanonical(receiptPayload)};
fs.writeFileSync(outputPath, `${JSON.stringify(receipt,null,2)}\n`);
console.log(JSON.stringify({valid:true,receipt_sha256:receipt.sha256,gate_readout:receiptPayload.gate_readout}));
