from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from .audit import canonical


def file_sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--verification-rows", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    frame = pd.read_csv(args.predictions, low_memory=False)
    columns = [
        "case_id",
        "GRCODE",
        "LOB",
        "cutoff",
        "split",
        "method",
        "actual_reserve",
        "prediction",
    ]
    rows = frame[columns].copy()
    rows["GRCODE"] = rows["GRCODE"].astype(str)
    rows = rows.sort_values(
        ["split", "method", "LOB", "GRCODE", "cutoff", "case_id"]
    ).reset_index(drop=True)
    args.verification_rows.parent.mkdir(parents=True, exist_ok=True)
    with args.verification_rows.open("w", encoding="utf-8") as handle:
        for row in rows.to_dict(orient="records"):
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    payload = report["payload"]
    payload["sealed_test"]["verification_rows_file"] = args.verification_rows.name
    payload["sealed_test"]["verification_rows_sha256"] = file_sha(
        args.verification_rows
    )
    canonical_payload = canonical(payload)
    report["payload_canonical"] = canonical_payload
    report["sha256"] = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "verification_rows_sha256": payload["sealed_test"][
                    "verification_rows_sha256"
                ],
                "report_sha256": report["sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
