#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");

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

const weights = {
  G00: 110, G01: 100, G02: 100, G03: 110, G04: 100,
  G05: 120, G06: 100, G07: 100, G08: 80, G09: 80,
};
const statuses = {
  G00: "PASS", G01: "PASS", G02: "PASS", G03: "PASS", G04: "PASS",
  G05: "PASS", G06: "PASS", G07: "OPEN", G08: "PASS", G09: "OPEN",
};

function verify(report) {
  const errors = [];
  const certificate = report.certificate;
  if (!certificate || typeof certificate !== "object") return ["certificate"];
  const payload = certificate.payload;
  if (!payload || typeof payload !== "object") return ["payload"];
  if (certificate.payload_sha256 !== digest(payload)) errors.push("payload-hash");

  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const score = Object.keys(weights)
    .filter((key) => statuses[key] === "PASS")
    .reduce((sum, key) => sum + weights[key], 0);
  if (total !== 1000) errors.push("weight-total");
  if (score !== 820) errors.push("score-contract");

  const result = payload.result || {};
  if (result.strict_score !== score) errors.push("strict-score");
  if (JSON.stringify(result.open_gates) !== JSON.stringify(["G07", "G09"])) errors.push("open-gates");
  if (result.open_points !== 180) errors.push("open-points");
  if (result.selected_method !== "robust_minimax_regret") errors.push("selected-method");
  if (result.selected_action_portfolio !== "parallel_g07_g09_program") errors.push("selected-action");
  if (payload.status !== "BLOCKED") errors.push("terminal-status");

  const routing = report.routing || {};
  if (routing.selected_solver !== "robust_minimax_regret") errors.push("routing");
  const unsigned = {};
  for (const key of Object.keys(report)) {
    if (key !== "report_sha256") unsigned[key] = report[key];
  }
  if (report.report_sha256 !== digest(unsigned)) errors.push("report-hash");
  return errors;
}

if (process.argv.length !== 3) {
  console.error("usage: verify.js <report.json>");
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
