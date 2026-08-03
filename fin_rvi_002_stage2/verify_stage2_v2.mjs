import fs from 'node:fs';
import crypto from 'node:crypto';

const corpusPath = process.argv[2] ?? 'reports/fin_rvi_002_stage2_v2/frozen_adjudication_corpus_v2.json';
const reportPath = process.argv[3] ?? 'reports/fin_rvi_002_stage2_v2/report.json';
const outputPath = process.argv[4] ?? 'reports/fin_rvi_002_stage2_v2/node_independent_receipt.json';

const corpus = JSON.parse(fs.readFileSync(corpusPath, 'utf8'));
const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  if (typeof value === 'number' && !Number.isSafeInteger(value)) {
    throw new Error('non-canonical numeric boundary');
  }
  return JSON.stringify(value);
}
function sha(value) {
  return crypto.createHash('sha256').update(canonical(value), 'utf8').digest('hex');
}
function normalize(value) {
  return String(value).normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toUpperCase().match(/[A-Z0-9]+/g)?.join(' ') ?? '';
}
function numericIds(values) {
  return new Set(values.map(value => String(value).replace(/\D/g, '')).filter(value => value.length >= 8));
}
function intersects(left, right) {
  for (const value of left) if (right.has(value)) return true;
  return false;
}
const consortiumTerms = new Set(['ASOCIACION', 'CONSORCIO', 'UNION', 'UTE']);
const auxiliaryPhrases = [
  'GASTOS DE VIAJE', 'GASTO DE VIAJE', 'VIATICO', 'VIATICOS',
  'COMBUSTIBLE PARA LA VISITA', 'COMBUSTIBLE PARA REALIZAR VISITA',
  'SOCIALIZACION', 'ASAMBLEAS INFORMATIVAS', 'PUBLICACION', 'PERIODICO', 'AVISO DE PRENSA',
];
const paymentPhrases = [
  'PAGO DE ANTICIPO', 'PAGO 20 DE ANTICIPO', 'PAGO DE COMPRA',
  'ANTICIPO DE CONTRATO', 'ANTICIPO DE INVERSION', 'PAGO ESTIMACION',
  'PAGO DE ESTIMACION', 'PAGO UNICO', 'PAGO PARCIAL', 'PARCIAL DEL PAGO',
  'PARCIAL DE PAGO', 'COMPLEMENTO DE PAGO', 'COMPLEMENTO DEL PAGO',
  'PAGO COMPLEMENTARIO', 'FACTURA', 'ESTIMACION', 'INFORME FINAL',
];
const reversalPhrases = ['REVERSION', 'REVERSA'];
const reservationPhrases = ['RESERVA DE FONDOS', 'RESERVA DE CREDITO', 'RESERVA DE PAGO'];
const genericTokens = new Set(['PAGO','CONTRATO','PROYECTO','COMPRA','SERVICIO','SERVICIOS','SECRETARIA','SEGUN','PARA','DIFERENTES','UNIDADES','FACTURA','FACT']);
const distinctiveTokens = new Set(['SELLOS','LIMPIEZA','PAVIMENTACION','ANTICIPO','ESTIMACION']);

function consortiumAmbiguous(row) {
  if (intersects(numericIds(row.oncae_supplier_ids), numericIds(row.sefin_supplier_ids))) return false;
  const leftNames = row.oncae_supplier_names.map(value => new Set(normalize(value).split(' ').filter(Boolean)));
  const rightNames = row.sefin_supplier_names.map(value => new Set(normalize(value).split(' ').filter(Boolean)));
  for (const left of leftNames) {
    for (const right of rightNames) {
      const consortium = [...left].some(value => consortiumTerms.has(value));
      const strictSubset = right.size > 0 && [...right].every(value => left.has(value)) && right.size < left.size;
      const difference = [...left].filter(value => !right.has(value)).length;
      if (consortium && strictSubset && difference >= 2) return true;
    }
  }
  return false;
}
function eventKind(row) {
  const text = normalize(row.sefin_object_text);
  if (auxiliaryPhrases.some(phrase => text.includes(phrase))) return 'AUXILIARY';
  const hasPayment = paymentPhrases.some(phrase => text.includes(phrase));
  const hasReversal = reversalPhrases.some(phrase => text.includes(phrase));
  const hasReservation = reservationPhrases.some(phrase => text.includes(phrase));
  if (hasReversal) return hasPayment ? 'MIXED_ACCOUNTING' : 'NONPAYMENT_ACCOUNTING';
  if (hasReservation && !hasPayment) return 'NONPAYMENT_ACCOUNTING';
  return hasPayment ? 'CONTRACT_PAYMENT' : 'UNKNOWN';
}
function semanticObjectSupport(row) {
  if (row.documentary_decision === 'SUPPORTED') return true;
  const tokens = value => new Set(normalize(value).split(' ').filter(token => token.length >= 5 && !genericTokens.has(token)));
  const left = tokens(row.oncae_object_text);
  const right = tokens(row.sefin_object_text);
  const shared = [...left].filter(token => right.has(token));
  return shared.length >= 2 || shared.some(token => distinctiveTokens.has(token));
}
function temporalStatus(row) {
  const oncae = row.oncae_dates.map(value => Date.parse(`${value}T00:00:00Z`));
  const sefin = row.sefin_dates.map(value => Date.parse(`${value}T00:00:00Z`));
  if (!oncae.length || !sefin.length || [...oncae, ...sefin].some(Number.isNaN)) return 'UNKNOWN';
  const day = 86400000;
  const minO = Math.min(...oncae), maxO = Math.max(...oncae), minS = Math.min(...sefin);
  if ((maxO - minO) / day >= 300 && minS <= maxO) return 'UNKNOWN_SOURCE_DATE_SEMANTICS';
  if (minS < minO && (minO - minS) / day > 45) return 'UNKNOWN_PAYMENT_PRECEDES_PROCUREMENT_EVIDENCE';
  return 'CONSISTENT';
}
function cardinalityStatus(row) {
  let text = normalize(row.sefin_object_text);
  text = text.replace(/\b(?:OP|REF|CTTO|CONTRATO|FACTURA|PAGO|ORDEN)\s*(?:NO)?\s*\d[0-9 ]{3,}/g, ' ');
  const codes = new Set(text.match(/\b\d{6}\b/g) ?? []);
  const target = normalize(row.target);
  if (/^\d{6}$/.test(target)) codes.delete(target);
  return /^\d{6}$/.test(target) && codes.size ? 'AMBIGUOUS_MULTI_PROJECT' : 'RESOLVED';
}
function ladder(row) {
  const kind = eventKind(row);
  const authority = consortiumAmbiguous(row) ? 'UNKNOWN_CONSORTIUM_AUTHORITY' : (row.supplier_supported ? 'SUPPORTED' : 'REJECTED');
  const temporal = temporalStatus(row);
  const cardinality = cardinalityStatus(row);
  const objectSupported = semanticObjectSupport(row);
  const blockers = [];
  if (kind === 'AUXILIARY') blockers.push('AUXILIARY_EXPENDITURE');
  else if (['NONPAYMENT_ACCOUNTING','MIXED_ACCOUNTING'].includes(kind)) blockers.push(kind);
  else if (kind !== 'CONTRACT_PAYMENT') blockers.push('PAYMENT_NATURE_UNKNOWN');
  if (authority !== 'SUPPORTED') blockers.push(`PAYEE_AUTHORITY_${authority}`);
  if (!objectSupported) blockers.push('OBJECT_NOT_SUPPORTED');
  if (temporal !== 'CONSISTENT') blockers.push(`TEMPORAL_${temporal}`);
  if (cardinality !== 'RESOLVED') blockers.push(`CARDINALITY_${cardinality}`);
  return blockers.length === 0;
}
function promote(row, policy) {
  if (policy === 'B0_CODE') return true;
  if (policy === 'B1_CODE_SUPPLIER') return Boolean(row.supplier_supported);
  if (policy === 'B2_CODE_SUPPLIER_AMOUNT') return Boolean(row.supplier_supported) && row.relative_amount_difference !== null && Number(row.relative_amount_difference) <= 0.05;
  if (policy === 'B3_DOCUMENTARY') return row.documentary_decision === 'SUPPORTED';
  if (policy === 'EVIDENCE_LADDER') return ladder(row);
  throw new Error(`unknown policy ${policy}`);
}
function evaluate(rows, split) {
  const policies = ['B0_CODE','B1_CODE_SUPPLIER','B2_CODE_SUPPLIER_AMOUNT','B3_DOCUMENTARY','EVIDENCE_LADDER'];
  const output = {};
  for (const policy of policies) {
    const metric = {rows:0, positive_expected:0, nonpositive_expected:0, promotions:0, supported_recovered:0, missed_supported:0, unsafe_overpromotions:0, correct_nonpromotions:0, binary_correct:0};
    for (const row of rows.filter(item => !split || item.split === split)) {
      const expectedPositive = row.gold_expected === 'SUPPORTED';
      const decision = promote(row, policy);
      metric.rows += 1;
      metric.positive_expected += Number(expectedPositive);
      metric.nonpositive_expected += Number(!expectedPositive);
      metric.promotions += Number(decision);
      if (expectedPositive && decision) { metric.supported_recovered += 1; metric.binary_correct += 1; }
      else if (expectedPositive) metric.missed_supported += 1;
      else if (decision) metric.unsafe_overpromotions += 1;
      else { metric.correct_nonpromotions += 1; metric.binary_correct += 1; }
    }
    output[policy] = metric;
  }
  return output;
}

const recomputed = evaluate(corpus.rows, 'SEALED_TEST');
const reported = report.payload.policy_metrics_sealed_test;
const gates = {
  report_hash: sha(report.payload) === report.sha256,
  corpus_payload_hash: sha(corpus) === report.payload.frozen_corpus_sha256,
  ladder_zero_unsafe: recomputed.EVIDENCE_LADDER.unsafe_overpromotions === 0,
  ladder_recovers_all: recomputed.EVIDENCE_LADDER.supported_recovered === recomputed.EVIDENCE_LADDER.positive_expected,
  ladder_beats_code_supplier: recomputed.EVIDENCE_LADDER.unsafe_overpromotions < recomputed.B1_CODE_SUPPLIER.unsafe_overpromotions,
  metrics_match_python: ['B0_CODE','B1_CODE_SUPPLIER','B2_CODE_SUPPLIER_AMOUNT','B3_DOCUMENTARY','EVIDENCE_LADDER'].every(policy =>
    ['rows','positive_expected','nonpositive_expected','promotions','supported_recovered','missed_supported','unsafe_overpromotions','correct_nonpromotions','binary_correct'].every(field => recomputed[policy][field] === reported[policy][field])
  ),
  python_gate_candidate: report.payload.gate_readout.G07 === 'PASS_CANDIDATE_PENDING_PUBLIC_CLEAN_REPLAY',
  g09_not_forged: report.payload.gate_readout.G09 === 'OPEN_PRIOR_ART_AND_INDEPENDENT_REPLICATION_REQUIRED',
};
if (!Object.values(gates).every(Boolean)) {
  console.error(JSON.stringify({gates, recomputed}, null, 2));
  process.exit(2);
}
const payload = {
  schema: 'fin-rvi-002/stage2-v2-node-independent-receipt/1',
  report_sha256: report.sha256,
  corpus_sha256: sha(corpus),
  sealed_metrics: recomputed,
  gates,
};
const receipt = {payload, sha256: sha(payload)};
fs.writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
fs.writeFileSync(`${outputPath}.sha256`, `${crypto.createHash('sha256').update(fs.readFileSync(outputPath)).digest('hex')}  ${outputPath.split('/').at(-1)}\n`, 'utf8');
console.log(JSON.stringify({status:'PASS', receipt_sha256:receipt.sha256, gates}));
