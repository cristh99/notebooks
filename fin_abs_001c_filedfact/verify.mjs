import fs from "node:fs";
import crypto from "node:crypto";

const SCHEMA = "fin-abs-001c/filedfact-passage-breadth/1";
const POLICY_ID = "FIN-ABS-001C-PASSAGE-DIRECT-RELATION-V1";
const BEFORE = 423;
const PASS_DELTA = 6;
const EXPECTED_ROWS = 776;
const RELATIVE_TOLERANCE = 0.001;
const ABSOLUTE_TOLERANCE = 2.0;
const PERMUTATION_SEED = "FIN-ABS-001C-PERMUTATION-V1";

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

function tolerance(observed, expected, termCount, rounded) {
  const rounding = rounded ? 0.51 * (termCount + 1) : 0;
  return Math.max(
    ABSOLUTE_TOLERANCE,
    RELATIVE_TOLERANCE * Math.max(Math.abs(observed), Math.abs(expected), 1),
    rounding,
  );
}

function evaluateInstance(instance, rounded) {
  const relation = instance.relation;
  let values = Object.fromEntries(
    Object.entries(instance.values).map(([key, value]) => [key, Number(value)]),
  );
  if (rounded) {
    values = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, roundHalfAway(value / 1_000_000)]),
    );
  }
  const targetId = relation.target_fact_id;
  const observed = values[targetId];
  let expected = 0;
  for (const term of relation.terms) {
    let value = values[term.fact_id];
    if (term.absolute) value = Math.abs(value);
    expected += Number(term.coefficient) * value;
  }
  const tol = tolerance(observed, expected, relation.terms.length, rounded);
  const residual = observed - expected;
  const decision = Math.abs(residual) > tol ? "ERROR" : "CLEAN";
  return {
    instance_id: instance.instance_id,
    relation_id: relation.relation_id,
    family: relation.family,
    subtype: relation.subtype,
    ticker: relation.passage.ticker,
    cik: relation.passage.cik,
    sic_code: relation.passage.sic_code,
    form_type: relation.passage.form_type,
    variant: rounded ? "rounded_millions" : "exact",
    gold_error: Boolean(instance.ground_truth.has_error),
    decision,
    observed,
    expected,
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

function verify(report, source, relations, instances, exactRows, roundedRows, relationsPath, instancesPath) {
  const payload = report.payload ?? {};
  const recomputedExact = instances.map((instance) => evaluateInstance(instance, false));
  const recomputedRounded = instances.map((instance) => evaluateInstance(instance, true));
  const exact = metrics(recomputedExact);
  const rounded = metrics(recomputedRounded);
  const permutation = permutationControl(recomputedExact);
  const companies = new Set(relations.map((relation) => relation.passage?.cik).filter(Boolean));
  const sics = new Set(relations.map((relation) => relation.passage?.sic_code).filter(Boolean));
  const forms = new Set(relations.map((relation) => relation.passage?.form_type).filter(Boolean));
  const families = new Map();
  for (const relation of relations) {
    families.set(relation.family, (families.get(relation.family) ?? 0) + 1);
  }
  const familyObject = Object.fromEntries([...families.entries()].sort(([a], [b]) => a.localeCompare(b)));
  const checks = {
    source_revision_pinned: String(source.revision ?? "").length >= 40,
    source_manifest_verified: source.selection_manifest_present_in_readme === true,
    validation_row_count_776: Number(source.row_count ?? 0) === EXPECTED_ROWS,
    validation_companies_at_least_700: Number(payload.cohort?.validation_companies ?? 0) >= 700,
    all_relations_directly_grounded: relations.every(directProvenance),
    eligible_companies_at_least_40: companies.size >= 40,
    relations_at_least_60: relations.length >= 60,
    sic_codes_at_least_20: sics.size >= 20,
    form_types_at_least_2: forms.size >= 2,
    relation_families_at_least_2: families.size >= 2,
    each_family_at_least_5: families.size >= 2 && [...families.values()].every((count) => count >= 5),
    dimension_total_relations_at_least_20: (families.get("DIMENSION_TOTAL") ?? 0) >= 20,
    statement_equations_at_least_5: (families.get("STATEMENT_EQUATION") ?? 0) >= 5,
    exact_zero_fpr: exact.false_positive_rate === 0,
    exact_precision_one: exact.precision === 1,
    exact_recall_one: exact.recall === 1,
    exact_full_coverage: exact.coverage === 1,
    rounded_zero_fpr: rounded.false_positive_rate === 0,
    rounded_recall_at_least_95pct: (rounded.recall ?? 0) >= 0.95,
    permutation_worse:
      (permutation.metrics.false_positive_rate ?? 0) > (exact.false_positive_rate ?? 0)
      || (permutation.metrics.recall ?? 0) < (exact.recall ?? 0),
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
    source_semantics: canonical(source) === canonical(payload.source),
    relations_hash: fileSha256(relationsPath) === payload.cohort?.cases_sha256,
    instances_hash: fileSha256(instancesPath) === payload.cohort?.instances_sha256,
    exact_rows: canonical(recomputedExact) === canonical(exactRows.map(stripHash)),
    rounded_rows: canonical(recomputedRounded) === canonical(roundedRows.map(stripHash)),
    exact_metrics: canonical(exact) === canonical(payload.exact_metrics),
    rounded_metrics: canonical(rounded) === canonical(payload.rounded_metrics),
    permutation: canonical(permutation) === canonical(payload.permutation_control),
    cohort_counts:
      payload.cohort?.eligible_companies === companies.size
      && payload.cohort?.eligible_relations === relations.length
      && payload.cohort?.sic_count === sics.size
      && canonical(payload.cohort?.form_types) === canonical([...forms].sort())
      && canonical(payload.cohort?.family_counts) === canonical(familyObject),
    gate_checks: canonical(checks) === canonical(payload.gate_checks),
    status: payload.status === (passed ? "PASS_FILEDFACT_PASSAGE_BREADTH" : "OPEN_FILEDFACT_PASSAGE_BREADTH"),
    score:
      payload.absolute_score?.before === BEFORE
      && payload.absolute_score?.after === expectedScore
      && payload.absolute_score?.delta === expectedScore - BEFORE,
    boundary:
      String(payload.boundary ?? "").includes("does not")
      && String(payload.absolute_score?.boundary ?? "").includes("no world-SOTA"),
  };
  const valid = Object.values(gates).every(Boolean);
  const receiptPayload = {
    schema: "fin-abs-001c/node-receipt/1",
    valid,
    failed_gates: Object.entries(gates).filter(([, value]) => !value).map(([key]) => key),
    report_sha256: report.sha256,
    source_revision: source.revision,
    cohort: {
      eligible_companies: companies.size,
      eligible_relations: relations.length,
      sic_count: sics.size,
      form_types: [...forms].sort(),
      family_counts: familyObject,
    },
    exact_metrics: exact,
    rounded_metrics: rounded,
    permutation_control: permutation,
    gate_checks: checks,
    absolute_score: expectedScore,
  };
  return {payload: receiptPayload, sha256: digest(receiptPayload)};
}

if (process.argv.length !== 9) {
  console.error("usage: node verify.mjs REPORT SOURCE RELATIONS INSTANCES EXACT ROUNDED OUTPUT");
  process.exit(2);
}
const report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const source = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const relations = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const instances = JSON.parse(fs.readFileSync(process.argv[5], "utf8"));
const exactRows = readJsonl(process.argv[6]);
const roundedRows = readJsonl(process.argv[7]);
const receipt = verify(
  report,
  source,
  relations,
  instances,
  exactRows,
  roundedRows,
  process.argv[4],
  process.argv[5],
);
fs.writeFileSync(process.argv[8], `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify({
  valid: receipt.payload.valid,
  failed_gates: receipt.payload.failed_gates,
  score: receipt.payload.absolute_score,
  receipt_sha256: receipt.sha256,
}));
process.exit(receipt.payload.valid ? 0 : 2);
