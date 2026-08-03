import fs from "node:fs";
import crypto from "node:crypto";

const EXPECTED_WEIGHTS = {
  WORLD_SOTA_SUPERIORITY: 250,
  HISTORICAL_ORIGINALITY: 200,
  CROSS_DOMAIN_GENERALITY: 150,
  TRUTH_RIGOR_REPRODUCIBILITY: 150,
  EXTERNAL_VALIDATION_AND_IMPACT: 150,
  AUTONOMOUS_RECURSIVE_GROWTH: 100,
};
const EXPECTED_SCORES = {
  WORLD_SOTA_SUPERIORITY: 35,
  HISTORICAL_ORIGINALITY: 45,
  CROSS_DOMAIN_GENERALITY: 90,
  TRUTH_RIGOR_REPRODUCIBILITY: 125,
  EXTERNAL_VALIDATION_AND_IMPACT: 48,
  AUTONOMOUS_RECURSIVE_GROWTH: 80,
};
const EXPECTED_ACTION = "parallel_benchmark_deployment_discovery";

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

function equalObjects(left, right) {
  return canonical(left) === canonical(right);
}

function minimaxRegret(actions) {
  const names = Object.keys(actions).sort();
  if (names.length === 0) throw new Error("actions required");
  const states = Object.keys(actions[names[0]]).sort();
  for (const name of names) {
    if (!equalObjects(Object.keys(actions[name]).sort(), states)) throw new Error("state mismatch");
  }
  const best = Object.fromEntries(states.map((state) => [state, Math.max(...names.map((name) => actions[name][state]))]));
  const regrets = Object.fromEntries(names.map((name) => [
    name,
    Math.max(...states.map((state) => best[state] - actions[name][state])),
  ]));
  const selected = names.sort((a, b) => regrets[a] - regrets[b] || a.localeCompare(b))[0];
  return { selected, regrets };
}

function verify(scorecard) {
  const dimensions = Array.isArray(scorecard.dimensions) ? scorecard.dimensions : [];
  const weights = Object.fromEntries(dimensions.map((item) => [item.id, Number(item.weight)]));
  const scores = Object.fromEntries(dimensions.map((item) => [item.id, Number(item.score)]));
  let selection = { selected: null, regrets: {} };
  try {
    selection = minimaxRegret(scorecard.problem_ir?.actions ?? {});
  } catch (_) {
    // Fail closed in gates below.
  }
  const demotions = scorecard.superseded_interpretations ?? {};
  const bounded = scorecard.bounded_result ?? {};
  const gates = {
    schema: scorecard.schema === "finance-absolute-level-god-score/1",
    cut_date: scorecard.cut_date === "2026-08-03",
    dimension_set: equalObjects(Object.keys(weights).sort(), Object.keys(EXPECTED_WEIGHTS).sort()),
    weights_exact: equalObjects(weights, EXPECTED_WEIGHTS),
    weights_sum_1000: Object.values(weights).reduce((a, b) => a + b, 0) === 1000,
    scores_exact: equalObjects(scores, EXPECTED_SCORES),
    scores_sum_423: Object.values(scores).reduce((a, b) => a + b, 0) === 423,
    declared_score_423: scorecard.absolute_score === 423,
    not_falsely_solved: scorecard.terminal_status === "BLOCKED",
    open_points_577: 1000 - Number(scorecard.absolute_score) === 577,
    maximum_claim_bounded: String(scorecard.maximum_claim ?? "").includes("domain-bounded"),
    internal_scores_demoted:
      String(demotions["775"] ?? "").includes("not absolute world SOTA") &&
      String(demotions["820"] ?? "").includes("not absolute world SOTA") &&
      String(demotions["1000"] ?? "").includes("not all of finance"),
    fin_rvi_scope_bounded:
      bounded.claim_id === "FIN-RVI-002-C1" &&
      String(bounded.scope ?? "").includes("Honduras ONCAE-SEFIN") &&
      new Set(bounded.does_not_imply ?? []).has("global finance SOTA"),
    fin_rvi_metrics_preserved:
      bounded.baseline_unsafe_promotions === 20 &&
      bounded.challenger_unsafe_promotions === 0 &&
      bounded.baseline_supported_recovered === 58 &&
      bounded.challenger_supported_recovered === 58,
    minimax_recomputed: selection.selected === EXPECTED_ACTION,
    selected_action_exact: scorecard.selected_action === EXPECTED_ACTION,
    more_theory_not_selected: selection.selected !== "more_internal_theory",
    partial_unknown_problem:
      scorecard.problem_ir?.uncertainty === "UNKNOWN" && scorecard.problem_ir?.model_status === "PARTIAL",
    next_program_complete: equalObjects(new Set(scorecard.next_program ?? []).size, 3) &&
      (scorecard.next_program ?? []).includes("FIN-ABS-001 sealed cross-domain external benchmark") &&
      (scorecard.next_program ?? []).includes("FIN-ABS-002 real-data engine deployment and stress validation") &&
      (scorecard.next_program ?? []).includes("FIN-ABS-003 independent replication and historical-priority audit"),
  };
  const valid = Object.values(gates).every(Boolean);
  const payload = {
    schema: "finance-absolute-level-god-node-receipt/1",
    scorecard_sha256: digest(scorecard),
    valid,
    absolute_score: scorecard.absolute_score,
    terminal_status: scorecard.terminal_status,
    selected_action: selection.selected,
    minimax_regrets: selection.regrets,
    gates,
    boundary: "423/1000 is the broad absolute score; FIN-RVI-002 is domain-bounded.",
  };
  return { payload, sha256: digest(payload) };
}

if (process.argv.length < 3 || process.argv.length > 4) {
  console.error("usage: node verify_score.mjs SCORECARD [OUTPUT]");
  process.exit(2);
}
const scorecard = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const receipt = verify(scorecard);
if (process.argv[3]) fs.writeFileSync(process.argv[3], `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify({
  valid: receipt.payload.valid,
  score: receipt.payload.absolute_score,
  selected_action: receipt.payload.selected_action,
  receipt_sha256: receipt.sha256,
}));
process.exit(receipt.payload.valid ? 0 : 2);
