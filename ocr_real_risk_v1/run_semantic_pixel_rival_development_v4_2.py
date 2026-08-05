"""Compact post-outcome development replay for semantic+pixel OCR v4.2."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

os.environ["OMP_THREAD_LIMIT"] = "1"

from PIL import Image

from .sroie_numeric_eval_helpers_v4_2 import (
    match_annotation, page_tokens, parse_annotations, sha256_path, tesseract_version,
)
from .semantic_pixel_rival_v4_2 import RivalAction, SemanticPixelRivalResolverV42
from .semantic_rival_detector_v4_2 import SemanticOCRToken, detect_semantic_rivals

SCHEMA = "ocr-semantic-pixel-rival-development-v4-2/1"


def evaluate(root: Path, stems: list[str]) -> dict[str, object]:
    resolver = SemanticPixelRivalResolverV42()
    started = time.perf_counter(); resolver.warm()
    warm_seconds = time.perf_counter() - started
    pages: list[dict[str, object]] = []
    flags_out: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    ocr_seconds = pixel_seconds = 0.0

    for stem in stems:
        image_path, annotation_path = root / f"{stem}.jpg", root / f"{stem}.txt"
        with Image.open(image_path) as opened:
            page = opened.convert("RGB")
        semantic_tokens, elapsed = page_tokens(page)
        ocr_seconds += elapsed
        semantic_flags = detect_semantic_rivals(semantic_tokens)
        baseline_by_index = {int(token.index): token for token in semantic_tokens}
        decisions: dict[int, dict[str, object]] = {}

        # All runtime decisions are sealed before annotations are opened.
        for flag in semantic_flags:
            token = baseline_by_index[flag.token_index]
            started = time.perf_counter()
            if flag.ambiguous or flag.rival_digits is None:
                decision = {
                    "action": RivalAction.QUARANTINE.value,
                    "reason_code": "AMBIGUOUS_SEMANTIC_RIVALS",
                    "output": flag.baseline_digits, "decision_sha256": None,
                    "views": [],
                }
            else:
                resolved = resolver.resolve(
                    page, token.bbox, flag.baseline_digits, flag.rival_digits
                )
                decision = {
                    "action": resolved.action.value,
                    "reason_code": resolved.reason_code,
                    "output": resolved.output,
                    "decision_sha256": resolved.decision_sha256,
                    "views": [asdict(view) for view in resolved.views],
                }
            runtime = time.perf_counter() - started
            pixel_seconds += runtime
            decisions[flag.token_index] = {
                "flag": {
                    "baseline_digits": flag.baseline_digits,
                    "rival_digits": flag.rival_digits,
                    "all_rivals": list(flag.all_rivals),
                    "reasons": [reason.value for reason in flag.reasons],
                },
                "token": {
                    "index": int(token.index), "text": str(token.text),
                    "digits": str(token.digits), "bbox": list(token.bbox),
                    "confidence": float(token.confidence),
                },
                "decision": decision, "runtime_seconds": runtime,
            }

        annotations = parse_annotations(annotation_path)
        truths: dict[int, set[str]] = {}
        eligible = 0
        for annotation in annotations:
            matched = match_annotation(annotation, semantic_tokens)
            if matched is None:
                continue
            token, geometry = matched
            if len(token.digits) != len(annotation["truth"]) or geometry["truth_coverage"] < 0.50:
                continue
            eligible += 1
            truths.setdefault(int(token.index), set()).add(str(annotation["truth"]))
            semantic = decisions.get(int(token.index))
            accepted = semantic is None or semantic["decision"]["action"] == RivalAction.REPLACE.value
            final_digits = (
                str(semantic["decision"]["output"])
                if semantic is not None and accepted else str(token.digits)
            )
            observations.append({
                "stem": stem, "truth": annotation["truth"],
                "annotation_text": annotation["text"],
                "baseline_text": token.text, "baseline_digits": token.digits,
                "baseline_correct": token.digits == annotation["truth"],
                "token_index": int(token.index), "token_bbox": list(token.bbox),
                "semantic_pixel_decision": semantic, "final_accepted": accepted,
                "final_digits": final_digits,
                "final_correct": accepted and final_digits == annotation["truth"],
            })

        for token_index, record in sorted(decisions.items()):
            matched_truths = sorted(truths.get(token_index, set()))
            flags_out.append({
                "stem": stem, **record, "matched_truths": matched_truths,
                "truth_match_status": (
                    "UNMATCHED" if not matched_truths else
                    "UNIQUE" if len(matched_truths) == 1 else "AMBIGUOUS"
                ),
            })
        pages.append({
            "stem": stem, "image_sha256": sha256_path(image_path),
            "annotation_sha256": sha256_path(annotation_path),
            "image_size": list(page.size), "ocr_seconds": elapsed,
            "numeric_annotations_in_scope": len(annotations),
            "eligible_claims": eligible, "semantic_flags": len(semantic_flags),
        })

    baseline_errors = sum(not row["baseline_correct"] for row in observations)
    flagged = [row for row in observations if row["semantic_pixel_decision"] is not None]
    accepted = [row for row in observations if row["final_accepted"]]
    flagged_accepted = [row for row in flagged if row["final_accepted"]]
    metrics = {
        "eligible_claims": len(observations), "baseline_errors": baseline_errors,
        "semantic_flags": len(flags_out),
        "flags_with_unique_truth_match": sum(row["truth_match_status"] == "UNIQUE" for row in flags_out),
        "flagged_baseline_errors": sum(not row["baseline_correct"] for row in flagged),
        "flagged_replacements": len(flagged_accepted),
        "flagged_quarantines": len(flagged) - len(flagged_accepted),
        "flagged_final_errors": sum(not row["final_correct"] for row in flagged_accepted),
        "false_replacements": sum(
            row["baseline_correct"] and row["final_digits"] != row["baseline_digits"]
            for row in flagged_accepted
        ),
        "global_final_accepted": len(accepted),
        "global_final_errors": sum(not row["final_correct"] for row in accepted),
    }
    report: dict[str, object] = {
        "schema": SCHEMA, "status": "POST_OUTCOME_DEVELOPMENT_ONLY",
        "source": {"corpus": "ICDAR2019 SROIE Task 1 natural receipts",
                   "stems": stems, "pages": len(stems),
                   "already_used_for_development": True,
                   "annotations_used_at_inference": False},
        "candidate": {
            "pixel_views": [view[0] for view in resolver.VIEW_SPECS],
            "minimum_rival_score": resolver.policy.minimum_rival_score,
            "minimum_rival_advantage": resolver.policy.minimum_rival_advantage,
            "replacement_rule": "both pixel views must predict the unique semantic rival and cross both evidence floors; otherwise quarantine",
            "global_pixel_autocorrection_allowed": False,
        },
        "metrics": metrics,
        "timing": {
            "bank_warm_seconds": warm_seconds,
            "full_page_tesseract_seconds": ocr_seconds,
            "selective_pixel_seconds": pixel_seconds,
            "mean_selective_pixel_ms_per_flag": pixel_seconds * 1000 / len(flags_out),
            "candidate_runtime_ratio_warm": (ocr_seconds + pixel_seconds) / ocr_seconds,
        },
        "constraints": {"external_spend_usd": 0.0, "gcloud_used": False,
                        "gpu_used": False, "paid_api_used": False,
                        "github_actions_used": False,
                        "production_modified": False,
                        "python": platform.python_version(), "tesseract": tesseract_version()},
        "decision": {"production_promotion": False,
                     "external_certification": False,
                     "verdict": "READY_TO_FREEZE_FOR_NEW_UNTOUCHED_SELECTIVE_FLAG_VALIDATION"},
        "pages": pages, "flags": flags_out, "observations": observations,
    }
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    report["stable_payload_sha256"] = hashlib.sha256(payload).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stems", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.root, args.stems)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"metrics": report["metrics"], "timing": report["timing"],
                      "stable_payload_sha256": report["stable_payload_sha256"]},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
