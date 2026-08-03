from __future__ import annotations

import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fin_rvi_002_stage1 import run_stage1 as base
from fin_rvi_002_stage1.identity_v2 import adjudicate_object_v2, compact_identity_pairs_v2
from fin_rvi_002_stage1.run_stage1_v2 import _best_document, generate_candidates_v2
from fin_rvi_002_stage3 import run_stage3 as core

DOWNLOAD_WORKERS = 16
EXTRACT_WORKERS = 8


def evaluate_stage3_parallel(connection, holdout: list[dict[str, Any]], acquire_documents: bool):
    prepared: list[dict[str, Any]] = []
    unique_urls: set[str] = set()
    for candidate in holdout:
        left = base.load_summary(connection, int(candidate["oncae_release_pk"]))
        right = base.load_summary(connection, int(candidate["sefin_release_pk"]))
        policy = adjudicate_object_v2(left, right)
        facts = core.supplier_facts(left, right)
        selected_document = _best_document(left, right)
        if acquire_documents and selected_document and selected_document.get("url"):
            unique_urls.add(str(selected_document["url"]))
        prepared.append(
            {
                "candidate": candidate,
                "left": left,
                "right": right,
                "policy": policy,
                "facts": facts,
                "selected_document": selected_document,
            }
        )

    acquisitions: dict[str, dict[str, Any]] = {}
    extractions: dict[str, dict[str, Any]] = {}
    started = time.monotonic()
    if acquire_documents and unique_urls:
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
            futures = {executor.submit(core.download_document, url): url for url in sorted(unique_urls)}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    acquisitions[url] = future.result()
                except Exception as exc:
                    acquisitions[url] = {
                        "url": url,
                        "status": "FAILED",
                        "error": f"{type(exc).__name__}: {exc}",
                        "seconds": 0.0,
                    }
        with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as executor:
            futures = {
                executor.submit(core.extract_document_text, record): url
                for url, record in acquisitions.items()
            }
            for future in as_completed(futures):
                url = futures[future]
                try:
                    extractions[url] = future.result()
                except Exception as exc:
                    extractions[url] = {
                        "status": "FAILED",
                        "error": f"{type(exc).__name__}: {exc}",
                        "text": "",
                    }

    decisions: list[dict[str, Any]] = []
    for item in prepared:
        selected_document = item["selected_document"]
        url = str(selected_document.get("url")) if selected_document and selected_document.get("url") else ""
        raw_acquisition = acquisitions.get(url)
        raw_extraction = extractions.get(url)
        document_text = str(raw_extraction.get("text", "")) if raw_extraction else ""
        label = core.evidence_label(
            item["left"],
            item["right"],
            item["policy"],
            document_text,
            item["facts"],
        )
        acquisition = (
            {key: value for key, value in raw_acquisition.items() if key != "path"}
            if raw_acquisition
            else None
        )
        extraction = (
            {key: value for key, value in raw_extraction.items() if key != "text"}
            if raw_extraction
            else None
        )
        decisions.append(
            {
                **item["candidate"],
                "supplier_facts": item["facts"],
                "structured_policy": item["policy"],
                "evidence_label": label,
                "oncae_object_text": item["left"].object_text[:10000],
                "sefin_object_text": item["right"].object_text[:10000],
                "oncae_classifications": list(item["left"].classifications),
                "sefin_classifications": list(item["right"].classifications),
                "selected_document": selected_document,
                "document_acquisition": acquisition,
                "document_extraction": extraction,
            }
        )

    labels = Counter(row["evidence_label"]["label"] for row in decisions)
    baseline_promotions = sum(
        row["supplier_facts"]["baseline_supplier_support"] for row in decisions
    )
    baseline_unsafe = sum(
        row["supplier_facts"]["baseline_supplier_support"]
        and row["evidence_label"]["label"] == "REJECTED"
        for row in decisions
    )
    policy_promotions = sum(
        row["structured_policy"]["decision"] == "SUPPORTED" for row in decisions
    )
    policy_unsafe = sum(
        row["structured_policy"]["decision"] == "SUPPORTED"
        and row["evidence_label"]["label"] == "REJECTED"
        for row in decisions
    )
    metrics = {
        "holdout_size": len(decisions),
        "decision_counts": dict(labels),
        "baseline_promotions": baseline_promotions,
        "baseline_unsupported_promotions": baseline_unsafe,
        "baseline_unsupported_promotion_rate": (
            baseline_unsafe / baseline_promotions if baseline_promotions else None
        ),
        "evidence_policy_promotions": policy_promotions,
        "evidence_policy_unsupported_promotions": policy_unsafe,
        "unsupported_amount_at_risk_avoided": round(
            sum(
                float(row["amount_sefin"])
                for row in decisions
                if row["supplier_facts"]["baseline_supplier_support"]
                and row["structured_policy"]["decision"] != "SUPPORTED"
            ),
            2,
        ),
        "document_acquisition_attempts": len(acquisitions),
        "document_acquisition_successes": sum(
            record.get("status") == "ACQUIRED" for record in acquisitions.values()
        ),
        "document_acquisition_bytes": sum(
            int(record.get("bytes", 0))
            for record in acquisitions.values()
            if record.get("status") == "ACQUIRED"
        ),
        "document_acquisition_seconds": round(time.monotonic() - started, 3),
        "download_workers": DOWNLOAD_WORKERS,
        "extract_workers": EXTRACT_WORKERS,
    }
    return decisions, metrics


def main() -> None:
    base.compact_identity_pairs = compact_identity_pairs_v2
    base.generate_candidates = generate_candidates_v2
    base.freeze_holdout = core.freeze_stage3
    base.adjudicate_object = adjudicate_object_v2
    base.evaluate_holdout = evaluate_stage3_parallel
    output = Path("reports/fin_rvi_002_stage3")
    if "--output" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output") + 1])
    base.main()
    core.rewrite_report(output)


if __name__ == "__main__":
    main()
