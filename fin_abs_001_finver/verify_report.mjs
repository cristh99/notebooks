import fs from "node:fs";
import crypto from "node:crypto";

const UPSTREAM_COMMIT = "8aef2f48befdab5c57cc383a521711fe11c2df98";
const RULE_RECALL = 0.528;
const ROUNDED_FRONTIER_RECALL = 0.790;
const PERMUTATION_SEED = "FIN-ABS-001A-PERMUTATION-V1";

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function digest(value) {
  return crypto.createHash("sha256").update(canonical(value), "utf8").digest("hex");
}

function readJsonl(path) {
  return fs.readFileSync(path, "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function safeDiv(a, b) {
  return b ? a / b : null;
}

function metrics(rows) {
  const eligible = rows.filter((row) => row.observable);
  const clean = eligible.filter((row) => !row.gold_error);
  const errors = eligible.filter((row) => row.gold_error);
  const tp = errors.filter((row) => row.decision === "ERROR").length;
  const fn = errors.length - tp;
  const tn = clean.filter((row) => row.decision === "CLEAN").length;
  const fp = clean.filter((row) => row.decision === "ERROR").length;
  const abstainClean = clean.filter((row) => row.decision === "ABSTAIN").length;
  const abstainError = errors.filter((row) => row.decision === "ABSTAIN").length;
  const precision = safeDiv(tp, tp + fp);
  const recall = safeDiv(tp, tp + fn);
  const specificity = safeDiv(tn, tn + fp);
  const fpr = safeDiv(fp, fp + tn);
  const accuracy = safeDiv(tp + tn, eligible.length);
  const f1 = precision !== null && recall !== null && precision + recall
    ? (2 * precision * recall) / (precision + recall)
    : null;
  const balanced = recall !== null && specificity !== null ? (recall + specificity) / 2 : null;
  const detected = errors.filter((row) => row.decision === "ERROR");
  const localization = safeDiv(detected.filter((row) => row.localized).length, detected.length);
  const totals = new Map();
  const hits = new Map();
  for (const row of errors) {
    for (const category of row.categories ?? []) {
      totals.set(category, (totals.get(category) ?? 0) + 1);
      if (row.decision === "ERROR") hits.set(category, (hits.get(category) ?? 0) + 1);
    }
  }
  const categoryRecall = {};
  for (const category of [...totals.keys()].sort()) {
    categoryRecall[category] = safeDiv(hits.get(category) ?? 0, totals.get(category));
  }
  return {
    eligible_rows: eligible.length,
    clean_rows: clean.length,
    observable_error_rows: errors.length,
    true_positive: tp,
    false_negative: fn,
    true_negative: tn,
    false_positive: fp,
    clean_abstentions: abstainClean,
    error_abstentions: abstainError,
    coverage: safeDiv(eligible.length - abstainClean - abstainError, eligible.length),
    accuracy,
    balanced_accuracy: balanced,
    precision,
    recall,
    specificity,
    false_positive_rate: fpr,
    f1,
    localization_accuracy_on_detected: localization,
    category_recall: categoryRecall,
  };
}

function permutationControl(rows) {
  const eligible = rows.filter((row) => row.observable).sort((a, b) => {
    const left = digest(`${a.instance_id}|${PERMUTATION_SEED}`);
    const right = digest(`${b.instance_id}|${PERMUTATION_SEED}`);
    return left.localeCompare(right);
  });
  const decisions = eligible.map((row) => row.decision);
  if (decisions.length) decisions.push(decisions.shift());
  const permuted = eligible.map((row, index) => ({ ...row, decision: decisions[index] }));
  return { seed: PERMUTATION_SEED, metrics: metrics(permuted) };
}

function equal(left, right) {
  return canonical(left) === canonical(right);
}

function verify(report, exactRows, roundedRows) {
  const payload = report.payload ?? {};
  const exact = metrics(exactRows);
  const rounded = metrics(roundedRows);
  const permutation = permutationControl(exactRows);
  const exactRecall = exact.recall ?? 0;
  const exactFpr = exact.false_positive_rate;
  const roundedRecall = rounded.recall ?? 0;
  const roundedFpr = rounded.false_positive_rate;
  const expectedChecks = {
    external_repo_pinned: payload.upstream?.commit === UPSTREAM_COMMIT,
    upstream_schema_mismatch_recorded: payload.upstream?.upstream_schema_audit?.pipeline_status === "SCHEMA_MISMATCH",
    adapter_boundary_declared: String(payload.adapter?.boundary ?? "").toLowerCase().includes("residual"),
    enough_companies: Number(payload.adapter?.adapted_statement_count ?? 0) >= 40,
    enough_clean_rows: Number(exact.clean_rows) >= 40,
    enough_observable_errors: Number(exact.observable_error_rows) >= 50,
    exact_zero_fpr: exactFpr === 0,
    exact_precision_one: exact.precision === 1,
    exact_full_coverage: exact.coverage === 1,
    beats_published_rule_recall: exactRecall > RULE_RECALL,
    rounded_zero_fpr: roundedFpr === 0,
    rounded_recall_meets_frontier: roundedRecall >= ROUNDED_FRONTIER_RECALL,
    permutation_is_worse:
      (permutation.metrics.false_positive_rate ?? 0) > (exactFpr ?? 0) ||
      (permutation.metrics.recall ?? 0) < exactRecall,
    no_absolute_score_promotion_from_adapter: true,
  };
  const gates = {
    report_hash: digest(payload) === report.sha256,
    schema: payload.schema === "fin-abs-001a/finver-external-slice/1",
    policy: payload.policy_id === "FIN-ABS-001A-CALIBRATED-RELATIONAL-VERIFIER-V1",
    exact_metrics: equal(exact, payload.exact_metrics),
    rounded_metrics: equal(rounded, payload.rounded_metrics),
    permutation: equal(permutation, payload.permutation_control),
    gate_checks: equal(expectedChecks, payload.gate_checks),
    score_unchanged:
      payload.absolute_score_readout?.before === 423 &&
      payload.absolute_score_readout?.after === 423,
    boundary_not_global_sota: String(payload.boundary ?? "").includes("does not") && String(payload.boundary ?? "").includes("general Finance SOTA"),
  };
  const valid = Object.values(gates).every(Boolean);
  const receiptPayload = {
    schema: "fin-abs-001a/node-receipt/1",
    valid,
    report_sha256: report.sha256,
    exact_metrics: exact,
    rounded_metrics: rounded,
    permutation_control: permutation,
    gates,
    absolute_score: 423,
    boundary: "The adapted external slice cannot promote the broad absolute score.",
  };
  return { payload: receiptPayload, sha256: digest(receiptPayload) };
}

if (process.argv.length !== 6) {
  console.error("usage: node verify_report.mjs REPORT EXACT_JSONL ROUNDED_JSONL OUTPUT");
  process.exit(2);
}
const report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const exactRows = readJsonl(process.argv[3]);
const roundedRows = readJsonl(process.argv[4]);
const receipt = verify(report, exactRows, roundedRows);
fs.writeFileSync(process.argv[5], `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify({ valid: receipt.payload.valid, score: 423, receipt_sha256: receipt.sha256 }));
process.exit(receipt.payload.valid ? 0 : 2);
