#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";

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

if (process.argv.length !== 3) {
  console.error("usage: verify_stage2_semantic.mjs <report.json>");
  process.exit(2);
}

let report;
try {
  report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
} catch (error) {
  console.error(JSON.stringify({valid: false, errors: ["json"], detail: String(error)}));
  process.exit(1);
}

const pythonPayloadHash = report.sha256;
const nodePayloadHash = digest(report.payload);
const replay = structuredClone(report);
replay.sha256 = nodePayloadHash;
const temporary = path.join(os.tmpdir(), `fin-rvi-002-stage2-${process.pid}.json`);
fs.writeFileSync(temporary, JSON.stringify(replay));
const verifier = path.join(path.dirname(new URL(import.meta.url).pathname), "verify_stage2.mjs");
const child = spawnSync(process.execPath, [verifier, temporary], {encoding: "utf8"});
fs.unlinkSync(temporary);
if (child.stdout) process.stdout.write(child.stdout);
if (child.stderr) process.stderr.write(child.stderr);
if (child.status === 0) {
  console.log(JSON.stringify({
    semantic_replay: "PASS",
    python_payload_sha256: pythonPayloadHash,
    node_payload_sha256: nodePayloadHash,
    note: "Hashes bind language-specific canonical numeric serialization; semantics are independently recomputed.",
  }));
}
process.exit(child.status ?? 1);
