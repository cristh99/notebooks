#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";

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
function metrics(rows) {
  const definitions = {
    B1_CODE_SUPPLIER: (row) => Boolean(row.baseline_supplier_support),
    POLICY_DOCUMENTARY: (row) => row.policy_decision === "SUPPORTED",
  };
  const labeled = rows.filter((row) => row.label === "SUPPORTED" || row.label === "REJECTED");
  const output = {};
  for (const [name, promotes] of Object.entries(definitions)) {
    const promoted = labeled.filter(promotes);
    output[name] = {
      labeled_rows: labeled.length,
      promotions: promoted.length,
      supported_recovered: promoted.filter((row) => row.label === "SUPPORTED").length,
      unsafe_overpromotions: promoted.filter((row) => row.label === "REJECTED").length,
      missed_supported: labeled.filter((row) => row.label === "SUPPORTED" && !promotes(row)).length,
      correct_rejections: labeled.filter((row) => row.label === "REJECTED" && !promotes(row)).length,
    };
  }
  return output;
}
function permuted(rows) {
  const seed = "FIN-RVI-002-STAGE3-PERMUTATION-V1";
  const labeled = rows
    .filter((row) => row.label === "SUPPORTED" || row.label === "REJECTED")
    .sort((a, b) => digest(`${a.candidate_id}|${seed}`).localeCompare(digest(`${b.candidate_id}|${seed}`)));
  let decisions = labeled.map((row) => row.policy_decision);
  if (decisions.length) decisions = [...decisions.slice(1), decisions[0]];
  const promoted = labeled.filter((_, index) => decisions[index] === "SUPPORTED");
  return {
    seed,
    labeled_rows: labeled.length,
    promotions: promoted.length,
    supported_recovered: promoted.filter((row) => row.label === "SUPPORTED").length,
    unsafe_overpromotions: promoted.filter((row) => row.label === "REJECTED").length,
  };
}
function expectedChecks(rows, policyMetrics, permutation) {
  const labelCounts = rows.reduce((acc, row) => {
    acc[row.label] = (acc[row.label] || 0) + 1;
    return acc;
  }, {});
  const baseline = policyMetrics.B1_CODE_SUPPLIER;
  const challenger = policyMetrics.POLICY_DOCUMENTARY;
  return {
    confirmed_positive_labels: (labelCounts.SUPPORTED || 0) >= 20,
    confirmed_negative_labels: (labelCounts.REJECTED || 0) >= 5,
    challenger_zero_unsafe: challenger.unsafe_overpromotions === 0,
    strictly_reduces_unsafe_vs_baseline:
      challenger.unsafe_overpromotions < baseline.unsafe_overpromotions,
    recovers_no_fewer_supported:
      challenger.supported_recovered >= baseline.supported_recovered,
    permutation_is_worse:
      permutation.unsafe_overpromotions > challenger.unsafe_overpromotions ||
      permutation.supported_recovered < challenger.supported_recovered,
  };
}
function expectedStatus(checks) {
  if (!checks.confirmed_positive_labels || !checks.confirmed_negative_labels) {
    return "BLOCKED_INSUFFICIENT_CONFIRMED_LABELS";
  }
  return Object.values(checks).every(Boolean)
    ? "PASS_CANDIDATE_PENDING_CLEAN_RECONSTRUCTION"
    : "OPEN_POLICY_DID_NOT_DOMINATE_STRONG_BASELINE";
}
function verify(report) {
  const errors = [];
  const payload = report.payload;
  if (!payload || typeof payload !== "object") return ["payload"];
  if (payload.schema !== "fin-rvi-002/stage4-independent-policy-v3/1") errors.push("schema");
  const stage4 = payload.stage4;
  if (!stage4 || typeof stage4 !== "object") return [...errors, "stage4"];
  const rows = stage4.compact_rows;
  if (!Array.isArray(rows)) return [...errors, "rows"];
  if (rows.length !== 120) errors.push("cohort-size");
  if (stage4.policy_id !== "FIN-RVI-002-DOCUMENTARY-V3") errors.push("policy-id");
  const independence = stage4.independence_contract || {};
  if (!independence.stage3_shared_codes_excluded) errors.push("stage3-exclusion");
  if (!independence.policy_fixed_before_stage4_outcomes) errors.push("policy-fixation");
  if (!independence.labeler_unchanged_from_stage3) errors.push("labeler-change");
  const manifest = stage4.source_stage3_manifest || {};
  const excluded = new Set(manifest.shared_codes || []);
  if (excluded.size !== 118) errors.push("manifest-count");
  if (rows.some((row) => excluded.has(row.shared_code))) errors.push("stage3-code-leakage");

  const codeCounts = new Map();
  for (const row of rows) codeCounts.set(row.shared_code, (codeCounts.get(row.shared_code) || 0) + 1);
  if ([...codeCounts.values()].some((count) => count > 2)) errors.push("code-cap");

  const recalculatedMetrics = metrics(rows);
  if (canonical(recalculatedMetrics) !== canonical(stage4.policy_metrics)) errors.push("policy-metrics");
  const recalculatedPermutation = permuted(rows);
  if (canonical(recalculatedPermutation) !== canonical(stage4.permutation_control)) errors.push("permutation");
  const checks = expectedChecks(rows, recalculatedMetrics, recalculatedPermutation);
  if (canonical(checks) !== canonical(stage4.gate_checks)) errors.push("gate-checks");
  const status = expectedStatus(checks);
  if (stage4.gate_status !== status) errors.push("stage4-status");
  if ((payload.gate_readout || {}).G07 !== status) errors.push("g07");
  return errors;
}

if (process.argv.length !== 3) {
  console.error("usage: verify_stage4.mjs <report.json>");
  process.exit(2);
}
let report;
try {
  report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
} catch (error) {
  console.error(JSON.stringify({valid: false, errors: ["json"], detail: String(error)}));
  process.exit(1);
}
const errors = verify(report);
console.log(JSON.stringify({valid: errors.length === 0, errors}));
process.exit(errors.length === 0 ? 0 : 1);
