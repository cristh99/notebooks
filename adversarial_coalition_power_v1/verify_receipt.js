#!/usr/bin/env node
'use strict';
const fs = require('fs');
const crypto = require('crypto');
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.keys(value).sort().reduce((out, key) => { out[key] = canonical(value[key]); return out; }, {});
  }
  return value;
}
function digest(value) { return crypto.createHash('sha256').update(JSON.stringify(canonical(value)), 'utf8').digest('hex'); }
function fail(msg) { console.error(`FAIL: ${msg}`); process.exit(1); }
const path = process.argv[2] || 'reports/benchmark_receipt.json';
const receipt = JSON.parse(fs.readFileSync(path, 'utf8'));
if (receipt.schema !== 'adversarial-coalition-power/receipt/1') fail('unexpected schema');
if (!receipt.payload || receipt.payload.status !== 'PASS') fail('status is not PASS');
if (receipt.payload.scenario_count !== 72 || receipt.payload.passed !== 72) fail('72/72 gate not met');
const body = {schema: receipt.schema, payload: receipt.payload};
const expected = digest(body);
if (receipt.sha256 !== expected) fail('digest mismatch');
console.log(JSON.stringify({status: 'PASS', scenarios: 72, sha256: expected}, null, 2));
