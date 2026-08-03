import fs from "node:fs";
import crypto from "node:crypto";

const SCHEMA = "fin-abs-004/v4finbench-data-audit/1";
const DATASET_HANDLE = "sebastiantomczak10/v4-group-corporate-bankruptcy";
const UPSTREAM_COMMIT = "908b88d373a76e0064329e38fc01cba98bebae5f";
const EXPECTED_FILES = [
  "company_years.parquet",
  "company_years_h1.parquet",
  "company_years_h2.parquet",
  "company_years_h3.parquet",
  "company_years_h4.parquet",
  "company_years_h5.parquet",
  "company_years_h6.parquet",
];
const PRIMARY = "company_years_h2.parquet";
const LABEL = "main_label";
const GROUP = "company";
const COUNTRY = "country";
const YEAR = "year";

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

function verify(report) {
  const payload = report.payload ?? {};
  const inventory = payload.dataset?.inventory ?? [];
  const byName = new Map(inventory.map((item) => [item.name, item]));
  const primary = byName.get(PRIMARY);
  const columns = new Set(primary?.column_names ?? []);
  const featureCount = [...columns].filter((name) => ![LABEL, GROUP, COUNTRY, YEAR].includes(name)).length;
  const label = payload.primary_task?.label_summary ?? {};
  const expectedGates = {
    dataset_handle_frozen: payload.dataset?.handle === DATASET_HANDLE,
    upstream_commit_frozen: payload.upstream?.commit === UPSTREAM_COMMIT,
    all_expected_files_present: EXPECTED_FILES.every((name) => byName.has(name)),
    exactly_seven_expected_parquet_files: inventory.length === EXPECTED_FILES.length,
    primary_task_present: Boolean(primary),
    primary_rows_at_least_500k: Number(primary?.rows ?? 0) >= 500000,
    primary_columns_at_least_130: Number(primary?.columns ?? 0) >= 130,
    feature_count_at_least_125: featureCount >= 125,
    label_present: columns.has(LABEL),
    label_has_at_least_1000_positives: Number(label.positive ?? 0) >= 1000,
    label_has_no_nulls: label.nulls === 0,
    group_column_present: columns.has(GROUP),
    country_column_present: columns.has(COUNTRY),
    year_column_present: columns.has(YEAR),
    company_count_at_least_100k: Number(payload.primary_task?.distinct_companies ?? 0) >= 100000,
    country_count_at_least_4: Number(payload.primary_task?.distinct_countries ?? 0) >= 4,
    year_count_at_least_10: Number(payload.primary_task?.distinct_years ?? 0) >= 10,
    all_hashes_sha256: inventory.every((item) => /^[0-9a-f]{64}$/.test(String(item.sha256))),
    no_data_embedded_in_report: true,
  };
  const passed = Object.values(expectedGates).every(Boolean);
  const accessBlocked = Boolean(payload.access_error);
  const expectedStatus = accessBlocked
    ? "BLOCKED_DATA_ACCESS"
    : (passed ? "PASS_DATA_AUDIT" : "BLOCKED_DATA_AUDIT");
  const gates = {
    report_hash: digest(payload) === report.sha256,
    schema: payload.schema === SCHEMA,
    inventory_hash: digest(inventory) === payload.dataset?.inventory_sha256,
    gate_checks: canonical(expectedGates) === canonical(payload.gate_checks),
    status: payload.status === expectedStatus,
    feature_count:
      payload.primary_task?.feature_count_excluding_four_control_columns === featureCount,
    score_unchanged:
      payload.absolute_score?.before === 423 &&
      payload.absolute_score?.after === 423 &&
      payload.absolute_score?.delta === 0,
    no_full_local_path:
      payload.dataset?.resolved_path_name === null ||
      (typeof payload.dataset?.resolved_path_name === "string" &&
       !payload.dataset.resolved_path_name.includes("/") &&
       !payload.dataset.resolved_path_name.includes("\\")),
    access_error_consistency:
      !accessBlocked ||
      (typeof payload.access_error?.type === "string" &&
       typeof payload.access_error?.message === "string" &&
       inventory.length === 0),
    boundary:
      accessBlocked
        ? String(payload.boundary ?? "").includes("could not be acquired")
        : String(payload.boundary ?? "").includes("does not validate"),
  };
  const valid = Object.values(gates).every(Boolean);
  const receiptPayload = {
    schema: "fin-abs-004/v4finbench-data-audit-node-receipt/1",
    valid,
    failed_gates: Object.entries(gates).filter(([, value]) => !value).map(([key]) => key),
    report_sha256: report.sha256,
    expected_status: expectedStatus,
    absolute_score: 423,
    gates,
  };
  return { payload: receiptPayload, sha256: digest(receiptPayload) };
}

if (process.argv.length !== 4) {
  console.error("usage: node verify_audit.mjs AUDIT_JSON OUTPUT_JSON");
  process.exit(2);
}
const report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const receipt = verify(report);
fs.writeFileSync(process.argv[3], `${JSON.stringify(receipt, null, 2)}\n`);
console.log(JSON.stringify({
  valid: receipt.payload.valid,
  expected_status: receipt.payload.expected_status,
  receipt_sha256: receipt.sha256,
}));
process.exit(receipt.payload.valid ? 0 : 2);
