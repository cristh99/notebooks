from __future__ import annotations

import hashlib
import json
from pathlib import Path

SOURCE_SHA256 = "1de1c1127d7380703f6b8fd56e9c8449456d23e878ee13e59fb23ec64a8f7d15"
TARGET_SHA256 = "1bec64d84784ab81a8b8da13a800b2ea679ec59e87fd542af95a7a2e70ad3562"
OLD_QUANTILE = "quantile = float(np.quantile(np.abs(pooled), min(0.995, 1.0 - alpha / 2.0)))"
NEW_QUANTILE = "conformal_level = min(0.995, max(interval_level, np.ceil((pooled.size + 1) * interval_level) / pooled.size))\n    quantile = float(np.quantile(np.abs(pooled), conformal_level))"
OLD_WIDTH = "width = 1.10 * quantile * growth"
NEW_WIDTH = "width = quantile * growth"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path("data_science_god_level/time_series_transfer")
    path = root / "forecaster.py"
    if digest(path) != SOURCE_SHA256:
        raise SystemExit("unexpected source forecaster hash")
    text = path.read_text(encoding="utf-8")
    if text.count(OLD_QUANTILE) != 1 or text.count(OLD_WIDTH) != 1:
        raise SystemExit("calibration patch anchors are not unique")
    text = text.replace(OLD_QUANTILE, NEW_QUANTILE).replace(OLD_WIDTH, NEW_WIDTH)
    path.write_text(text, encoding="utf-8")
    if digest(path) != TARGET_SHA256:
        raise SystemExit("derived forecaster hash mismatch")
    receipt = {
        "schema": "data-science-god-level/time-series-conformal-calibration-patch/1",
        "source_forecaster_sha256": SOURCE_SHA256,
        "target_forecaster_sha256": TARGET_SHA256,
        "changed_semantics": "finite-sample conformal quantile for absolute residuals; duplicate 1.10 inflation removed",
        "point_forecast_selection_and_combination_changed": False,
        "public_evidence_used": "prior public gate failed only normalized interval width while coverage was 1.0",
        "official_suite_accessed": False,
    }
    (root / "calibration-patch-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
