#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";

const POLICIES = [
  "B0_CODE",
  "B1_CODE_SUPPLIER",
  "B2_CODE_SUPPLIER_AMOUNT",
  "POLICY_DOCUMENTARY",
];
const EVIDENCE_FIELDS = {
  B0_CODE: 1,
  B1_CODE_SUPPLIER: 2,
  B2_CODE_SUPPLIER_AMOUNT: 3,
  POLICY_DOCUMENTARY: 4,
};
const SEED = "FIN-RVI-002-STAGE2-NEGATIVE-CONTROL-V1";

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
function promotes(row, policy) {
  if (policy === "B0_CODE") return true;
  if (policy === "B1_CODE_SUPPLIER") return Boolean(row.supplier_supported);
  if (policy === "B2_CODE_SUPPLIER_AMOUNT") {
    return Boolean(row.supplier_supported) && Number(row.relative_amount_difference) <= 0.05;
  }
  if (policy === "POLICY_DOCUMENTARY") return row.documentary_decision === "SUPPORTED";
  throw new Error(`unknown policy ${policy}`);
}
function template(policy) {
  return {
    policy,
    evidence_fields: EVIDENCE_FIELDS[policy],
    holdout_promotions: 0,
    evaluated_rule_hits: 0,
    matched_candidates: 0,
    positive_expected: 0,
    nonpositive_expected: 0,
    supported_recovered: 0,
    unsafe_overpromotions: 0,
    correct_nonpromotions: 0,
    missed_supported: 0,
    binary_correct: 0,
  };
}
function evaluate(rows) {
  const output = {};
  for (const policy of POLICIES) {
    const metric = template(policy);
    const matched = new Set();
    for (const row of rows) {
      const promote = promotes(row, policy);
      metric.holdout_promotions += Number(promote);
      if (row.gold.length) matched.add(String(row.candidate_id));
      for (const gold of row.gold) {
        const positive = gold.expected === "SUPPORTED";
        metric.evaluated_rule_hits += 1;
        if (positive) {
          metric.positive_expected += 1;
          if (promote) {
            metric.supported_recovered += 1;
            metric.binary_correct += 1;
          } else metric.missed_supported += 1;
        } else {
          metric.nonpositive_expected += 1;
          if (promote) metric.unsafe_overpromotions += 1;
          else {
            metric.correct_nonpromotions += 1;
            metric.binary_correct += 1;
          }
        }
      }
    }
    metric.matched_candidates = matched.size;
    metric.ordering_key = [
      metric.unsafe_overpromotions,
      -metric.supported_recovered,
      metric.missed_supported,
      metric.evidence_fields,
      policy,
    ];
    output[policy] = metric;
  }
  return output;
}
function rotate(rows) {
  const ordered = [...rows].sort((a, b) => {
    const ka = digest(`${a.candidate_id}|${SEED}`);
    const kb = digest(`${b.candidate_id}|${SEED}`);
    return ka.localeCompare(kb);
  });
  const decisions = ordered.map((row) => row.documentary_decision);
  const shifted = decisions.length ? [...decisions.slice(1), decisions[0]] : [];
  const mapping = new Map(ordered.map((row, i) => [String(row.candidate_id), shifted[i]]));
  return rows.map((row) => ({...row, documentary_decision: mapping.get(String(row.candidate_id))}));
}
function rotatedMetric(rows) {
  const metric = template("POLICY_DOCUMENTARY");
  const matched = new Set();
  for (const row of rotate(rows)) {
    const promote = row.documentary_decision === "SUPPORTED";
    metric.holdout_promotions += Number(promote);
    if (row.gold.length) matched.add(String(row.candidate_id));
    for (const gold of row.gold) {
      const positive = gold.expected === "SUPPORTED";
      metric.evaluated_rule_hits += 1;
      if (positive) {
        metric.positive_expected += 1;
        if (promote) {
          metric.supported_recovered += 1;
          metric.binary_correct += 1;
        } else metric.missed_supported += 1;
      } else {
        metric.nonpositive_expected += 1;
        if (promote) metric.unsafe_overpromotions += 1;
        else {
          metric.correct_nonpromotions += 1;
          metric.binary_correct += 1;
        }
      }
    }
  }
  metric.matched_candidates = matched.size;
  metric.seed = SEED;
  return metric;
}
function compareKeys(left, right) {
  for (let i = 0; i < left.length; i += 1) {
    if (left[i] < right[i]) return -1;
    if (left[i] > right[i]) return 1;
  }
  return 0;
}
function verify(report) {
  const errors = [];
  const payload = report.payload;
  if (!payload || typeof payload !== "object") return ["payload"];
  if (report.sha256 !== digest(payload)) errors.push("payload-hash");
  if (payload.schema !== "fin-rvi-002/stage2-strong-baselines/1") errors.push("schema");
  const rows = payload.input_rows;
  if (!Array.isArray(rows)) return [...errors, "input-rows"];
  const metrics = evaluate(rows);
  if (canonical(metrics) !== canonical(payload.policy_metrics)) errors.push("policy-metrics");
  const rotated = rotatedMetric(rows);
  if (canonical(rotated) !== canonical(payload.negative_control)) errors.push("negative-control");
  const b1 = metrics.B1_CODE_SUPPLIER;
  const doc = metrics.POLICY_DOCUMENTARY;
  const checks = {
    has_positive_gold: doc.positive_expected >= 1,
    has_nonpositive_gold: doc.nonpositive_expected >= 1,
    documentary_zero_unsafe: doc.unsafe_overpromotions === 0,
    strictly_reduces_unsafe_vs_b1: doc.unsafe_overpromotions < b1.unsafe_overpromotions,
    recovers_no_fewer_supported_vs_b1: doc.supported_recovered >= b1.supported_recovered,
    negative_control_worse:
      rotated.unsafe_overpromotions > doc.unsafe_overpromotions ||
      rotated.binary_correct < doc.binary_correct,
  };
  if (canonical(checks) !== canonical(payload.gate_checks)) errors.push("gate-checks");
  const expectedGate = Object.values(checks).every(Boolean)
    ? "PASS_CANDIDATE_PENDING_CLEAN_REPLAY"
    : "OPEN";
  if (payload.gate_readout.G07_STRONG_BASELINE !== expectedGate) errors.push("g07");
  const winner = POLICIES.reduce((best, policy) =>
    compareKeys(metrics[policy].ordering_key, metrics[best].ordering_key) < 0 ? policy : best
  );
  if (payload.selected_policy !== winner) errors.push("selected-policy");
  const incremental = rows.filter(
    (row) => row.supplier_supported && row.documentary_decision !== "SUPPORTED"
  );
  const amount = Math.round(
    incremental.reduce((sum, row) => sum + Number(row.amount_sefin), 0) * 100
  ) / 100;
  const expectedIncrement = {
    blocked_rows: incremental.length,
    blocked_candidate_ids: incremental.map((row) => row.candidate_id),
    amount_sefin: amount,
  };
  if (canonical(expectedIncrement) !== canonical(payload.documentary_increment_over_b1)) {
    errors.push("documentary-increment");
  }
  return errors;
}

if (process.argv.length !== 3) {
  console.error("usage: verify_stage2.mjs <report.json>");
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
