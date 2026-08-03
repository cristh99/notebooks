#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const REQUIRED_GATES = [
  "stage2_strong_baseline",
  "clean_independent_replay",
  "second_sealed_cohort",
  "systematic_primary_prior_art_log",
  "claim_scope_audit",
];
const REQUIRED_EXCLUSIONS = new Set([
  "legality", "fraud", "corruption", "physical receipt", "quality", "liquidation", "causal impact",
]);
const REQUIRED_ABSORBED = new Set([
  "public_payment_record_linkage",
  "procurement_supplier_name_reconciliation",
  "procurement_spending_knowledge_graphs",
  "OCDS_contract_lifecycle_transactions_and_documents",
  "adaptive_costly_information_acquisition",
  "noisy_expensive_test_selection",
  "provenance_and_refutation",
  "one_to_many_procurement_data_modeling",
  "procurement_payment_red_flags",
  "audit_document_sufficiency_and_three_way_matching",
  "purchase_order_invoice_vendor_reconciliation",
  "many_to_many_purchase_to_pay_process_modeling",
  "open_set_document_rejection",
  "contract_payment_reconciliation_patents",
  "Honduras_procurement_financial_system_integration",
]);

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value).sort();
    return `{${keys.map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
function digest(value) {
  return crypto.createHash("sha256").update(canonical(value), "utf8").digest("hex");
}
function sameSet(values, expected) {
  const actual = new Set(values || []);
  return actual.size === expected.size && [...expected].every((value) => actual.has(value));
}
function subset(expected, actualValues) {
  const actual = new Set(actualValues || []);
  return [...expected].every((value) => actual.has(value));
}
function eq(value, expected) {
  return canonical(value) === canonical(expected);
}
function verify(contract) {
  const errors = [];
  if (contract.schema !== "fin-rvi-002/g09-claim-contract/2") errors.push("schema");
  if (contract.claim_id !== "FIN-RVI-002-C1") errors.push("claim-id");
  if (contract.status !== "PASS") errors.push("status");
  const claim = String(contract.claim || "");
  for (const phrase of [
    "sealed public ONCAE-SEFIN holdout", "120 pairs", "exact contract/project-code blocking",
    "compatible supplier identity", "strictly reduces unsupported promotions", "from 20 to 0",
    "without reducing supported-payment recovery", "58/58 under both",
    "one-to-many contract-financial-event cardinality", "fail-closed abstention",
    "clean reconstruction reproduces",
  ]) if (!claim.includes(phrase)) errors.push("claim-specificity");

  const scope = contract.scope || {};
  if (scope.country !== "Honduras" || scope.period !== "2023-2025" || scope.claim_level !== "CONTRACTOR_PAYMENT") errors.push("scope");
  if (!sameSet(scope.excluded_claims, REQUIRED_EXCLUSIONS)) errors.push("excluded-claims");
  const novelty = contract.novelty_classification || {};
  if (novelty.type !== "DOMAIN_BOUNDED_ORIGINAL_EMPIRICAL_RESULT") errors.push("novelty-type");
  if (novelty.broad_method_novelty !== false) errors.push("broad-method-novelty");
  if (novelty.exact_claim_match_found_in_bounded_search !== false) errors.push("prior-art-exact-match");
  if (novelty.revocable_if_prior_art_found !== true) errors.push("novelty-revocability");
  if (contract.strong_baseline !== "B1_CODE_SUPPLIER") errors.push("strong-baseline");
  if (contract.challenger !== "POLICY_DOCUMENTARY_V3") errors.push("challenger");
  if (!subset(REQUIRED_ABSORBED, contract.prior_art_absorbed)) errors.push("prior-art-boundary");

  const required = contract.required_gates || {};
  const current = contract.current_gates || {};
  if (!sameSet(Object.keys(required), new Set(REQUIRED_GATES)) || REQUIRED_GATES.some((gate) => required[gate] !== "PASS")) errors.push("required-gates");
  if (!sameSet(Object.keys(current), new Set(REQUIRED_GATES)) || REQUIRED_GATES.some((gate) => current[gate] !== "PASS")) errors.push("premature-pass");

  const evidence = contract.empirical_evidence || {};
  const s3 = evidence.development_stage3 || {};
  const s4 = evidence.independent_stage4 || {};
  const s5 = evidence.clean_stage5 || {};
  if (s3.run_id !== 30840335568 || s3.artifact_id !== 8866730681 || s3.report_sha256 !== "e12ac82c517ede58cbe2ee1339c24ae6c406251c08e562afd856e65eb859c6f4") errors.push("stage3-lineage");
  if (!eq(s3.labels, {SUPPORTED:57, REJECTED:34, UNRESOLVED:29}) || !eq(s3.baseline, {unsafe_overpromotions:19, supported_recovered:57}) || !eq(s3.challenger_v2, {unsafe_overpromotions:17, supported_recovered:56})) errors.push("stage3-result");
  if (s4.run_id !== 30841561243 || s4.artifact_id !== 8867231467 || s4.report_sha256 !== "83e83d5893c7df8ab425debbb21e9edd5eda60e08309cfbd4905bd84a5ffbc7d") errors.push("stage4-lineage");
  if (s4.cohort_size !== 120 || s4.stage3_shared_codes_excluded !== 118 || !eq(s4.labels, {SUPPORTED:58, REJECTED:28, UNRESOLVED:34})) errors.push("stage4-cohort");
  if (!eq(s4.baseline, {promotions:78, unsafe_overpromotions:20, supported_recovered:58, missed_supported:0})) errors.push("stage4-baseline");
  if (!eq(s4.challenger_v3, {promotions:58, unsafe_overpromotions:0, supported_recovered:58, missed_supported:0})) errors.push("stage4-challenger");
  if (!eq(s4.permutation, {promotions:58, unsafe_overpromotions:21, supported_recovered:37}) || s4.all_preregistered_checks !== true) errors.push("stage4-controls");
  if (s5.run_id !== 30844453922 || s5.artifact_id !== 8868335548 || s5.reconstructed_report_sha256 !== "e825184bc0e4389e8475b9a861d852b40c39b57322cbad574b4d4880fc67f811") errors.push("stage5-lineage");
  if (s5.python_receipt_sha256 !== "03e97d0eb13ad7808a1a78f37ff2e8d16695ca092ccf3ed76f7cd12a78b795be" || s5.node_receipt_sha256 !== "3fa82f11d111d97e3b5fcaf58680a413f1482e01744e336cd5e64fa0c33d72d6" || s5.all_python_gates !== true || s5.all_node_gates !== true || s5.finance_score_after_g07 !== 920) errors.push("stage5-result");

  const prior = contract.prior_art_search || {};
  if (prior.status !== "PASS_BOUNDED_MULTI_INDEX_SEARCH" || prior.exact_claim_match_found !== false || prior.cut_date !== "2026-08-03") errors.push("prior-art-search");
  if (!Array.isArray(contract.primary_sources) || contract.primary_sources.length < 20) errors.push("primary-sources");
  return [...new Set(errors)];
}

const input = process.argv[2] || "fin_rvi_002_g09/claim_contract.json";
const output = process.argv[3] || "reports/fin_rvi_002_g09/node_claim_receipt.json";
const contract = JSON.parse(fs.readFileSync(input, "utf8"));
const errors = verify(contract);
const promotion = errors.length === 0;
const payload = {
  schema: "fin-rvi-002/g09-node-claim-receipt/2",
  claim_id: contract.claim_id,
  contract_sha256: digest(contract),
  valid: promotion,
  errors,
  promotion_allowed: promotion,
  gate_readout: {G07:"PASS", G09: promotion ? "PASS" : "OPEN", finance_score: promotion ? 1000 : 920},
};
const receipt = {payload, sha256:digest(payload)};
fs.mkdirSync(path.dirname(output), {recursive:true});
fs.writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
console.log(JSON.stringify({valid:promotion, errors, gate_readout:payload.gate_readout}));
process.exit(promotion ? 0 : 1);
