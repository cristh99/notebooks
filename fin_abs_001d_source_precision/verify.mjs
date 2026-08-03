import fs from "node:fs";
import crypto from "node:crypto";

const SCHEMA = "fin-abs-001d/source-precision-robustness/1";
const POLICY_ID = "FIN-ABS-001D-SOURCE-PRECISION-V1";
const SOURCE_REVISION = "8f7cb7e70be8b4dc6702c24927b355c1a287e4c0";
const PARQUET_SHA = "c04bb39a676be9fbc5dd8a0addf99c2a92d9fcb2281657ba4c2bc5d6bf0b7a77";
const BASE_COUNT = 526;
const BASE_ID_SHA = "e9c67085421a89f37fe67e292af1d6ab49c846028d60bef6fe7878dbd36e4457";
const BASE_SIGNATURE_SHA = "c9596b45f0f29a774eba4a7a0e598acd57363380044dfa112d507227403f72ed";
const BEFORE = 423;
const PASS_DELTA = 6;
const ERROR_RATE = 0.05;
const RESOLVABILITY_MULTIPLIER = 2.0;
const MILLION = 1_000_000;
const PERMUTATION_SEED = "FIN-ABS-001D-PERMUTATION-V1";

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

function fileSha256(path) {
  return crypto.createHash("sha256").update(fs.readFileSync(path)).digest("hex");
}

function readJsonl(path) {
  return fs.readFileSync(path, "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function roundHalfAway(value) {
  return value >= 0 ? Math.floor(value + 0.5) : Math.ceil(value - 0.5);
}

function quantize(value, quantum) {
  return roundHalfAway(value / quantum) * quantum;
}

function exactTolerance(observed, expected, termCount, rounded) {
  return Math.max(
    2,
    0.001 * Math.max(Math.abs(observed), Math.abs(expected), 1),
    rounded ? 0.51 * (termCount + 1) : 0,
  );
}

function expected(relation, values) {
  let total = 0;
  for (const term of relation.terms) {
    let value = Number(values[term.fact_id]);
    if (term.absolute) value = Math.abs(value);
    total += Number(term.coefficient) * value;
  }
  return total;
}

function evaluate(instance, variant) {
  const relation = instance.relation;
  let values = Object.fromEntries(
    Object.entries(instance.values).map(([key, value]) => [key, Number(value)]),
  );
  if (variant === "source_precision") {
    values = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [
        key,
        quantize(value, Number(relation.precision[key].quantum)),
      ]),
    );
  } else if (variant === "naive_million") {
    values = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, roundHalfAway(value / MILLION)]),
    );
  }
  const targetId = relation.target_fact_id;
  const observed = values[targetId];
  const exp = expected(relation, values);
  let tol;
  if (variant === "source_precision") {
    tol = Math.max(
      exactTolerance(observed, exp, relation.terms.length, false),
      Number(relation.source_precision.aggregate_half_quantum_uncertainty),
    );
  } else if (variant === "naive_million") {
    tol = exactTolerance(observed, exp, relation.terms.length, true);
  } else {
    tol = exactTolerance(observed, exp, relation.terms.length, false);
  }
  const residual = observed - exp;
  const decision = Math.abs(residual) > tol ? "ERROR" : "CLEAN";
  return {
    instance_id: instance.instance_id,
    relation_id: relation.relation_id,
    family: relation.family,
    subtype: relation.subtype,
    ticker: relation.passage.ticker,
    cik: relation.passage.cik,
    sic_code: relation.passage.sic_code,
    variant,
    gold_error: Boolean(instance.ground_truth.has_error),
    decision,
    observed,
    expected: exp,
    residual,
    tolerance: tol,
  };
}

function stripHash(row) {
  const value = {...row};
  delete value.prediction_sha256;
  return value;
}

function safeDiv(a, b) {
  return b ? a / b : null;
}

function metrics(rows) {
  const clean = rows.filter((row) => !row.gold_error);
  const errors = rows.filter((row) => row.gold_error);
  const tp = errors.filter((row) => row.decision === "ERROR").length;
  const fn = errors.length - tp;
  const tn = clean.filter((row) => row.decision === "CLEAN").length;
  const fp = clean.length - tn;
  const precision = safeDiv(tp, tp + fp);
  const recall = safeDiv(tp, tp + fn);
  const specificity = safeDiv(tn, tn + fp);
  const fpr = safeDiv(fp, fp + tn);
  const f1 = precision !== null && recall !== null && precision + recall
    ? (2 * precision * recall) / (precision + recall)
    : null;
  const familyTotal = new Map();
  const familyHits = new Map();
  for (const row of errors) {
    familyTotal.set(row.family, (familyTotal.get(row.family) ?? 0) + 1);
    if (row.decision === "ERROR") {
      familyHits.set(row.family, (familyHits.get(row.family) ?? 0) + 1);
    }
  }
  const familyRecall = {};
  for (const family of [...familyTotal.keys()].sort()) {
    familyRecall[family] = safeDiv(familyHits.get(family) ?? 0, familyTotal.get(family));
  }
  return {
    rows: rows.length,
    clean_rows: clean.length,
    error_rows: errors.length,
    true_positive: tp,
    false_negative: fn,
    true_negative: tn,
    false_positive: fp,
    coverage: rows.length ? 1 : null,
    accuracy: safeDiv(tp + tn, rows.length),
    precision,
    recall,
    specificity,
    false_positive_rate: fpr,
    f1,
    family_recall: familyRecall,
  };
}

function permutationControl(rows) {
  const ordered = rows.map((row) => ({...row})).sort((left, right) => {
    const a = digest(`${left.instance_id}|${PERMUTATION_SEED}`);
    const b = digest(`${right.instance_id}|${PERMUTATION_SEED}`);
    return a.localeCompare(b);
  });
  const decisions = ordered.map((row) => row.decision);
  if (decisions.length) decisions.push(decisions.shift());
  const permuted = ordered.map((row, index) => ({...row, decision: decisions[index]}));
  return {seed: PERMUTATION_SEED, metrics: metrics(permuted)};
}

function directProvenance(relation) {
  const passage = relation.passage ?? {};
  const facts = relation.facts ?? {};
  if (
    !passage.chunk_id
    || !passage.accession
    || !String(passage.source_url ?? "").startsWith("https://www.sec.gov/")
    || !passage.text_sha256
    || Object.keys(facts).length === 0
  ) return false;
  return Object.values(facts).every((fact) => (
    Boolean(fact.fact_id)
    && Boolean(fact.concept)
    && String(fact.unit ?? "").startsWith("monetary:USD")
    && Boolean(fact.period)
    && fact.displayed_text !== null
    && fact.text_start !== null
    && fact.text_end !== null
  ));
}

function precisionVerified(relation) {
  const facts = relation.facts ?? {};
  const precision = relation.precision ?? {};
  if (canonical(Object.keys(facts).sort()) !== canonical(Object.keys(precision).sort())) return false;
  return Object.entries(precision).every(([factId, value]) => (
    value.display_consistent === true
    && Number(value.quantum) > 0
    && Number(value.source_value) === Number(facts[factId].value)
    && Math.abs(quantize(Number(value.source_value), Number(value.quantum)) - Number(value.source_value))
      <= Math.max(1e-9, Number(value.quantum) * 1e-9)
  ));
}

function eligibility(relation) {
  const values = Object.fromEntries(
    Object.entries(relation.facts).map(([factId, fact]) => [factId, Number(fact.value)]),
  );
  const targetId = relation.target_fact_id;
  const original = values[targetId];
  const exp = expected(relation, values);
  const baseTolerance = exactTolerance(original, exp, relation.terms.length, false);
  const targetQuantum = Number(relation.precision[targetId].quantum);
  const uncertainty = 0.5 * targetQuantum + relation.terms.reduce(
    (sum, term) => sum + 0.5 * Math.abs(Number(term.coefficient)) * Number(relation.precision[term.fact_id].quantum),
    0,
  );
  const direction = parseInt(digest(relation.relation_id).slice(-1), 16) % 2 ? -1 : 1;
  const rawModified = original + direction * ERROR_RATE * Math.abs(original);
  const modified = quantize(rawModified, targetQuantum);
  const actualDelta = Math.abs(modified - original);
  const threshold = RESOLVABILITY_MULTIPLIER * uncertainty + baseTolerance;
  const stored = relation.source_precision ?? {};
  const semanticMatch = (
    Number(stored.target_quantum) === targetQuantum
    && Math.abs(Number(stored.aggregate_half_quantum_uncertainty) - uncertainty) <= 1e-9
    && Math.abs(Number(stored.base_tolerance) - baseTolerance) <= 1e-9
    && Math.abs(Number(stored.resolvability_threshold) - threshold) <= 1e-9
    && Math.abs(Number(stored.modified_target_value) - modified) <= 1e-9
    && Math.abs(Number(stored.actual_delta) - actualDelta) <= 1e-9
    && actualDelta > threshold
  );
  return {semanticMatch, actualDelta, threshold};
}

function verify(
  report,
  source,
  baseSignature,
  relations,
  instances,
  exactRows,
  sourceRows,
  naiveRows,
  relationsPath,
  instancesPath,
) {
  const payload = report.payload ?? {};
  const recomputedExact = instances.map((instance) => evaluate(instance, "exact"));
  const recomputedSource = instances.map((instance) => evaluate(instance, "source_precision"));
  const recomputedNaive = instances.map((instance) => evaluate(instance, "naive_million"));
  const exact = metrics(recomputedExact);
  const sourcePrecision = metrics(recomputedSource);
  const naive = metrics(recomputedNaive);
  const permutation = permutationControl(recomputedSource);
  const companies = new Set(relations.map((relation) => relation.passage?.cik).filter(Boolean));
  const sics = new Set(relations.map((relation) => relation.passage?.sic_code).filter(Boolean));
  const families = new Map();
  for (const relation of relations) {
    families.set(relation.family, (families.get(relation.family) ?? 0) + 1);
  }
  const familyObject = Object.fromEntries([...families.entries()].sort(([a], [b]) => a.localeCompare(b)));
  const baseIds = baseSignature.map((value) => value.relation_id).sort();
  const eligibilityChecks = relations.map(eligibility);
  const checks = {
    source_revision_exact: source.revision === SOURCE_REVISION,
    source_parquet_hash_exact: source.parquet_sha256 === PARQUET_SHA,
    source_manifest_verified: source.selection_manifest_present_in_readme === true,
    base_relation_count_exact: baseSignature.length === BASE_COUNT,
    base_relation_id_hash_exact: digest(baseIds) === BASE_ID_SHA,
    base_relation_signature_hash_exact: digest(baseSignature) === BASE_SIGNATURE_SHA,
    all_eligible_directly_grounded: relations.every(directProvenance),
    all_eligible_precision_verified: relations.every(precisionVerified),
    all_eligible_resolvable_ex_ante: eligibilityChecks.every((value) => value.semanticMatch),
    eligible_companies_at_least_100: companies.size >= 100,
    eligible_relations_at_least_300: relations.length >= 300,
    sic_codes_at_least_70: sics.size >= 70,
    dimension_relations_at_least_250: (families.get("DIMENSION_TOTAL") ?? 0) >= 250,
    statement_relations_at_least_50: (families.get("STATEMENT_EQUATION") ?? 0) >= 50,
    exact_precision_one: exact.precision === 1,
    exact_recall_one: exact.recall === 1,
    exact_zero_fpr: exact.false_positive_rate === 0,
    source_precision_one: sourcePrecision.precision === 1,
    source_precision_recall_at_least_99pct: (sourcePrecision.recall ?? 0) >= 0.99,
    source_precision_zero_fpr: sourcePrecision.false_positive_rate === 0,
    source_precision_full_coverage: sourcePrecision.coverage === 1,
    beats_naive_million_by_25_points: (sourcePrecision.recall ?? 0) - (naive.recall ?? 0) >= 0.25,
    permutation_worse:
      (permutation.metrics.false_positive_rate ?? 0) > (sourcePrecision.false_positive_rate ?? 0)
      || (permutation.metrics.recall ?? 0) < (sourcePrecision.recall ?? 0),
  };
  const passed = Object.values(checks).every(Boolean);
  const expectedScore = BEFORE + (passed ? PASS_DELTA : 0);
  const gates = {
    report_hash:
      typeof report.payload_canonical === "string"
      && crypto.createHash("sha256").update(report.payload_canonical, "utf8").digest("hex") === report.sha256,
    payload_matches_canonical:
      typeof report.payload_canonical === "string"
      && canonical(JSON.parse(report.payload_canonical)) === canonical(payload),
    schema: payload.schema === SCHEMA,
    policy: payload.policy_id === POLICY_ID,
    source_semantics: Object.entries(payload.source ?? {}).every(([key, value]) => canonical(source[key]) === canonical(value)),
    relations_hash: fileSha256(relationsPath) === payload.cohort?.relations_sha256,
    instances_hash: fileSha256(instancesPath) === payload.cohort?.instances_sha256,
    exact_rows: canonical(recomputedExact) === canonical(exactRows.map(stripHash)),
    source_rows: canonical(recomputedSource) === canonical(sourceRows.map(stripHash)),
    naive_rows: canonical(recomputedNaive) === canonical(naiveRows.map(stripHash)),
    exact_metrics: canonical(exact) === canonical(payload.exact_metrics),
    source_metrics: canonical(sourcePrecision) === canonical(payload.source_precision_metrics),
    naive_metrics: canonical(naive) === canonical(payload.naive_million_metrics),
    permutation: canonical(permutation) === canonical(payload.permutation_control),
    cohort_counts:
      payload.cohort?.eligible_companies === companies.size
      && payload.cohort?.eligible_relations === relations.length
      && payload.cohort?.sic_count === sics.size
      && canonical(payload.cohort?.family_counts) === canonical(familyObject),
    gate_checks: canonical(checks) === canonical(payload.gate_checks),
    status: payload.status === (passed ? "PASS_SOURCE_PRECISION_ROBUSTNESS" : "OPEN_SOURCE_PRECISION_ROBUSTNESS"),
    score:
      payload.absolute_score?.before === BEFORE
      && payload.absolute_score?.after === expectedScore
      && payload.absolute_score?.delta === expectedScore - BEFORE,
    boundary:
      String(payload.boundary ?? "").includes("does not")
      && String(payload.absolute_score?.boundary ?? "").includes("cannot add world-SOTA"),
  };
  const valid = Object.values(gates).every(Boolean);
  const receiptPayload = {
    schema: "fin-abs-001d/node-receipt/1",
    valid,
    failed_gates: Object.entries(gates).filter(([, value]) => !value).map(([key]) => key),
    report_sha256: report.sha256,
    cohort: {
      eligible_companies: companies.size,
      eligible_relations: relations.length,
      sic_count: sics.size,
      family_counts: familyObject,
    },
    exact_metrics: exact,
    source_precision_metrics: sourcePrecision,
    naive_million_metrics: naive,
    permutation_control: permutation,
    gate_checks: checks,
    absolute_score: expectedScore,
  };
  return {payload: receiptPayload, sha256: digest(receiptPayload)};
}

if (process.argv.length !== 11) {
  console.error("usage: node verify.mjs REPORT SOURCE BASE_SIGNATURE RELATIONS INSTANCES EXACT SOURCE_PRECISION NAIVE OUTPUT");
  process.exit(2);
}
const report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const source = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const baseSignature = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const relations = JSON.parse(fs.readFileSync(process.argv[5], "utf8"));
const instances = JSON.parse(fs.readFileSync(process.argv[6], "utf8"));
const exactRows = readJsonl(process.argv[7]);
const sourceRows = readJsonl(process.argv[8]);
const naiveRows = readJsonl(process.argv[9]);
const receipt = verify(
  report,
  source,
  baseSignature,
  relations,
  instances,
  exactRows,
  sourceRows,
  naiveRows,
  process.argv[5],
  process.argv[6],
);
fs.writeFileSync(process.argv[10], `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify({
  valid: receipt.payload.valid,
  failed_gates: receipt.payload.failed_gates,
  score: receipt.payload.absolute_score,
  receipt_sha256: receipt.sha256,
}));
process.exit(receipt.payload.valid ? 0 : 2);
