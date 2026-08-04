import fs from "node:fs";
import crypto from "node:crypto";
import zlib from "node:zlib";

const SCHEMA = "fin-abs-004/v4-credit-calibration-benchmark/1";
const POLICY = "FIN-ABS-004-PLATT-ENSEMBLE-V1";
const PRIMARY_SHA = "e9fa1b9cb51ea03f3f2582d08674d7b5039e32fb049363f8f2aa12e4dfc76eeb";
const EPS = 1e-8;
const TOP_CAPACITY = 0.005;
const METRIC_TOLERANCE = 1e-6;

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

function fileSha(path) {
  return crypto.createHash("sha256").update(fs.readFileSync(path)).digest("hex");
}

function loadSample(path) {
  const text = zlib.gunzipSync(fs.readFileSync(path)).toString("utf8");
  return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function rocAuc(y, p) {
  const order = [...p.keys()].sort((a, b) => p[a] - p[b] || a - b);
  let rank = 1;
  let positiveRankSum = 0;
  let positives = 0;
  let negatives = 0;
  for (let start = 0; start < order.length;) {
    let end = start + 1;
    while (end < order.length && p[order[end]] === p[order[start]]) end += 1;
    const averageRank = (rank + (rank + end - start - 1)) / 2;
    for (let pos = start; pos < end; pos += 1) {
      if (y[order[pos]] === 1) {
        positiveRankSum += averageRank;
        positives += 1;
      } else {
        negatives += 1;
      }
    }
    rank += end - start;
    start = end;
  }
  return (positiveRankSum - positives * (positives + 1) / 2) / (positives * negatives);
}

function averagePrecision(y, p) {
  const order = [...p.keys()].sort((a, b) => p[b] - p[a] || a - b);
  const positives = y.reduce((a, b) => a + b, 0);
  let tp = 0;
  let fp = 0;
  let previousRecall = 0;
  let ap = 0;
  for (let start = 0; start < order.length;) {
    let end = start + 1;
    while (end < order.length && p[order[end]] === p[order[start]]) end += 1;
    for (let pos = start; pos < end; pos += 1) {
      if (y[order[pos]] === 1) tp += 1;
      else fp += 1;
    }
    const recall = tp / positives;
    const precision = tp / (tp + fp);
    ap += (recall - previousRecall) * precision;
    previousRecall = recall;
    start = end;
  }
  return ap;
}

function ece(y, p, bins = 20) {
  const order = [...p.keys()].sort((a, b) => p[a] - p[b] || a - b);
  let result = 0;
  for (let bin = 0; bin < bins; bin += 1) {
    const start = Math.floor(bin * order.length / bins);
    const end = Math.floor((bin + 1) * order.length / bins);
    if (end <= start) continue;
    let ps = 0;
    let ys = 0;
    for (let pos = start; pos < end; pos += 1) {
      ps += p[order[pos]];
      ys += y[order[pos]];
    }
    const size = end - start;
    result += size / order.length * Math.abs(ps / size - ys / size);
  }
  return result;
}

function topCapacity(y, p) {
  const k = Math.max(1, Math.ceil(y.length * TOP_CAPACITY));
  const order = [...p.keys()].sort((a, b) => p[b] - p[a] || a - b).slice(0, k);
  const captured = order.reduce((sum, index) => sum + y[index], 0);
  const positives = y.reduce((sum, value) => sum + value, 0);
  return {
    capacity: TOP_CAPACITY,
    k,
    captured_positives: captured,
    precision: captured / k,
    recall: positives ? captured / positives : 0,
  };
}

function metrics(rows, prefix) {
  const y = rows.map((row) => Number(row.y));
  const p = rows.map((row) => Math.min(1 - EPS, Math.max(EPS, Number(row[`${prefix}_probability`]))));
  const pred = rows.map((row) => Number(row[`${prefix}_prediction`]));
  let tp = 0;
  let fp = 0;
  let fn = 0;
  let brier = 0;
  let logloss = 0;
  let predictedPositive = 0;
  for (let index = 0; index < y.length; index += 1) {
    const residual = p[index] - y[index];
    brier += residual * residual;
    logloss += -(y[index] * Math.log(p[index]) + (1 - y[index]) * Math.log(1 - p[index]));
    predictedPositive += pred[index];
    if (pred[index] === 1 && y[index] === 1) tp += 1;
    if (pred[index] === 1 && y[index] === 0) fp += 1;
    if (pred[index] === 0 && y[index] === 1) fn += 1;
  }
  const positives = y.reduce((a, b) => a + b, 0);
  const precision = tp + fp ? tp / (tp + fp) : 0;
  const recall = tp + fn ? tp / (tp + fn) : 0;
  return {
    rows: y.length,
    positives,
    positive_rate: positives / y.length,
    roc_auc: rocAuc(y, p),
    average_precision: averagePrecision(y, p),
    brier: brier / y.length,
    log_loss: logloss / y.length,
    ece_20: ece(y, p, 20),
    threshold: 0.5,
    precision,
    recall,
    f1: precision + recall ? 2 * precision * recall / (precision + recall) : 0,
    predicted_positive: predictedPositive,
    top_capacity: topCapacity(y, p),
  };
}

function stableMetricView(value) {
  return {
    rows: value?.rows,
    positives: value?.positives,
    positive_rate: value?.positive_rate,
    roc_auc: value?.roc_auc,
    average_precision: value?.average_precision,
    brier: value?.brier,
    log_loss: value?.log_loss,
    ece_20: value?.ece_20,
    precision: value?.precision,
    recall: value?.recall,
    f1: value?.f1,
    predicted_positive: value?.predicted_positive,
  };
}

function close(a, b, tolerance = METRIC_TOLERANCE) {
  if (a === null || b === null || a === undefined || b === undefined) return a === b;
  if (typeof a === "number" && typeof b === "number") {
    return Math.abs(a - b) <= tolerance * Math.max(1, Math.abs(a), Math.abs(b));
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((value, index) => close(value, b[index], tolerance));
  }
  if (a !== null && b !== null && typeof a === "object" && typeof b === "object") {
    const ak = Object.keys(a).sort();
    const bk = Object.keys(b).sort();
    return canonical(ak) === canonical(bk) && ak.every((key) => close(a[key], b[key], tolerance));
  }
  return a === b;
}

function verify(report, samplePath) {
  const payload = report.payload ?? {};
  const rows = loadSample(samplePath);
  const baseline = metrics(rows, "baseline");
  const challenger = metrics(rows, "challenger");
  const passed = Object.values(payload.gate_checks ?? {}).every(Boolean);
  const expectedStatus = passed ? "PASS_CREDIT_CALIBRATION" : "FALSIFIED_CREDIT_CALIBRATION";
  const expectedScore = passed ? 429 : 423;
  const gates = {
    report_hash: digest(payload) === report.sha256,
    schema: payload.schema === SCHEMA,
    policy: payload.policy_id === POLICY,
    primary_hash: payload.data?.primary_sha256 === PRIMARY_SHA,
    folds: payload.protocol?.folds === 5 && (payload.folds ?? []).length === 5,
    sample_file_hash: fileSha(samplePath) === payload.verification_sample?.sample_sha256,
    sample_artifact_hash: fileSha(samplePath) === payload.artifacts?.verification_sample_sha256,
    sample_rows: rows.length === payload.verification_sample?.rows,
    baseline_sample_metrics: close(
      stableMetricView(baseline),
      stableMetricView(payload.verification_sample?.baseline_metrics),
    ),
    challenger_sample_metrics: close(
      stableMetricView(challenger),
      stableMetricView(payload.verification_sample?.challenger_metrics),
    ),
    status: payload.status === expectedStatus,
    score:
      payload.absolute_score?.before === 423 &&
      payload.absolute_score?.after === expectedScore &&
      payload.absolute_score?.delta === expectedScore - 423,
    no_sota_points:
      payload.protocol?.score_dimensions?.world_sota === 0 &&
      payload.protocol?.score_dimensions?.historical_originality === 0,
    boundary:
      String(payload.boundary ?? "").includes("not a causal") &&
      String(payload.boundary ?? "").includes("not"),
  };
  const valid = Object.values(gates).every(Boolean);
  const receiptPayload = {
    schema: "fin-abs-004/v4-credit-node-receipt/2",
    valid,
    failed_gates: Object.entries(gates).filter(([, value]) => !value).map(([key]) => key),
    report_sha256: report.sha256,
    sample_sha256: fileSha(samplePath),
    expected_status: expectedStatus,
    expected_score: expectedScore,
    metric_tolerance: METRIC_TOLERANCE,
    compared_metric_view: "stable-core-excludes-sample-top-capacity-tie-selection",
    sample_metrics: { baseline, challenger },
    gates,
  };
  return { payload: receiptPayload, sha256: digest(receiptPayload) };
}

if (process.argv.length !== 5) {
  console.error("usage: node verify_benchmark.mjs REPORT SAMPLE_GZ OUTPUT_JSON");
  process.exit(2);
}
const report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const receipt = verify(report, process.argv[3]);
fs.writeFileSync(process.argv[4], `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify({
  valid: receipt.payload.valid,
  failed_gates: receipt.payload.failed_gates,
  expected_status: receipt.payload.expected_status,
  expected_score: receipt.payload.expected_score,
  receipt_sha256: receipt.sha256,
}));
process.exit(receipt.payload.valid ? 0 : 2);
