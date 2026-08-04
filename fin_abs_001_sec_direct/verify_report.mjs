import fs from "node:fs";

import {
  readJsonl,
} from "./node_policy.mjs";
import {
  verify,
} from "./node_verify.mjs";

if (process.argv.length !== 8) {
  console.error(
    "usage: node verify_report.mjs "
    + "REPORT CASES INSTANCES "
    + "EXACT_JSONL ROUNDED_JSONL OUTPUT",
  );
  process.exit(2);
}

const report = JSON.parse(
  fs.readFileSync(
    process.argv[2],
    "utf8",
  ),
);
const cases = JSON.parse(
  fs.readFileSync(
    process.argv[3],
    "utf8",
  ),
);
const instances = JSON.parse(
  fs.readFileSync(
    process.argv[4],
    "utf8",
  ),
);
const exactRows = readJsonl(
  process.argv[5],
);
const roundedRows = readJsonl(
  process.argv[6],
);
const receipt = verify(
  report,
  process.argv[3],
  cases,
  instances,
  exactRows,
  roundedRows,
);
fs.writeFileSync(
  process.argv[7],
  `${JSON.stringify(
    receipt,
    null,
    2,
  )}\n`,
);
console.log(
  JSON.stringify({
    valid: receipt.payload.valid,
    failed_gates:
      receipt.payload.failed_gates,
    score:
      receipt.payload.absolute_score,
    receipt_sha256: receipt.sha256,
  }),
);
process.exit(
  receipt.payload.valid ? 0 : 2,
);
