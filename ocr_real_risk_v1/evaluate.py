"""Execute the frozen real holdout and emit an exact, location-bound risk report."""
from __future__ import annotations

import json
import os
import shutil
import statistics
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image

from .core import (
    BOUND_ALPHA, EXCLUDED_PROCESS_FRAGMENTS, FAMILYWISE_ALPHA,
    MIN_ACCEPTED_FOR_CERTIFICATE, MIN_DOCUMENTS_FOR_CERTIFICATE,
    MIN_INSTITUTIONS_FOR_CERTIFICATE, MIN_NATIVE_WORDS, SCHEMA,
    TARGET_REDUCTION, Candidate, canonical_json, canonical_truth,
    clopper_pearson_lower, clopper_pearson_upper, mutate_one_digit, p95,
    round_robin, sha256_bytes, sha256_file,
)
from .pdf_pipeline import (
    crop_box, crop_is_usable, download_pdf, extract_word_boxes,
    page_has_full_image, pdf_page_count, render_page, selected_pages,
    tesseract_claim,
)


def _status(decision: Any) -> str:
    status = getattr(decision, "status", "")
    return str(getattr(status, "value", status))


def _prediction(decision: Any) -> str:
    return str(getattr(decision, "predicted", ""))


def _candidate_rank(source_sha256: str, page: int, bbox: Sequence[float], truth: str) -> str:
    return sha256_bytes(canonical_json({
        "source_sha256": source_sha256, "page": page,
        "bbox": [round(float(x), 4) for x in bbox], "truth": truth,
    }).encode("utf-8"))


def execute(candidates: Sequence[Candidate], output_dir: Path,
            max_documents: int, target_tokens: int, stage: str) -> dict[str, Any]:
    from pixel_digit_alignment import PixelDigitAligner

    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = output_dir / "scratch"
    crops_dir = output_dir / "evidence/crops"
    samples_dir = output_dir / "evidence/samples"
    for path in (scratch, crops_dir, samples_dir):
        path.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    aligner = PixelDigitAligner()
    _ = aligner.configuration(); _ = aligner._bank  # type: ignore[attr-defined]
    bank_ms = (time.perf_counter() - started) * 1000.0

    observations: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    institutions_with_tokens: set[str] = set()
    attempted = 0

    for candidate in round_robin(candidates):
        if attempted >= max_documents or len(observations) >= target_tokens:
            break
        attempted += 1
        document_id = candidate.key[:16]
        work = scratch / document_id
        work.mkdir(parents=True, exist_ok=True)
        pdf = work / "source.pdf"
        acquisition = download_pdf(candidate.url, pdf)
        doc: dict[str, Any] = {
            "document_id": document_id, "candidate": asdict(candidate),
            "acquisition": acquisition, "pages": [],
        }
        if acquisition["status"] != "ACQUIRED":
            failures[str(acquisition["status"])] += 1
            documents.append(doc); shutil.rmtree(work, ignore_errors=True); continue
        try:
            page_count = pdf_page_count(pdf)
        except Exception as exc:  # noqa: BLE001
            failures["PDFINFO_FAILED"] += 1
            doc["error"] = f"{type(exc).__name__}: {exc}"
            documents.append(doc); shutil.rmtree(work, ignore_errors=True); continue
        doc["page_count"] = page_count
        document_candidates: list[dict[str, Any]] = []

        for page_number in selected_pages(page_count):
            page_report: dict[str, Any] = {"page_number": page_number}
            try:
                page_w, page_h, words = extract_word_boxes(pdf, page_number, work)
                page_report["native_word_count"] = len(words)
                if len(words) < MIN_NATIVE_WORDS:
                    page_report["status"] = "INSUFFICIENT_NATIVE_WORDS"
                    failures[page_report["status"]] += 1; doc["pages"].append(page_report); continue
                full_image, coverage = page_has_full_image(pdf, page_number, page_w, page_h)
                page_report["max_image_coverage"] = coverage
                if full_image:
                    page_report["status"] = "FULL_PAGE_IMAGE_EXCLUDED"
                    failures[page_report["status"]] += 1; doc["pages"].append(page_report); continue
                image_path = render_page(pdf, page_number, work)
                with Image.open(image_path) as opened:
                    image = opened.convert("RGB")
                    page_report["image_size"] = list(image.size)
                    seen: set[tuple[Any, ...]] = set()
                    eligible = 0
                    for word in words:
                        truth = canonical_truth(str(word["text"]))
                        if truth is None: continue
                        bbox_pt = [float(x) for x in word["bbox_pt"]]
                        box_px = crop_box(bbox_pt, (page_w, page_h), image.size)
                        key = (truth, *(round(x, 4) for x in bbox_pt))
                        if key in seen: continue
                        seen.add(key)
                        crop = image.crop(box_px)
                        if not crop_is_usable(crop): continue
                        eligible += 1
                        rank = _candidate_rank(str(acquisition["sha256"]), page_number, bbox_pt, truth)
                        candidate_crop = work / f"candidate-{rank[:16]}.png"
                        crop.save(candidate_crop, optimize=True)
                        document_candidates.append({
                            "rank": rank, "truth": truth, "page_number": page_number,
                            "bbox_pt": bbox_pt, "bbox_px": list(box_px),
                            "crop_path": candidate_crop,
                        })
                    page_report["eligible_numeric_words"] = eligible
                    page_report["status"] = "PREPARED" if eligible else "NO_ELIGIBLE_NUMERIC_WORDS"
                    if not eligible: failures[page_report["status"]] += 1
                    doc["pages"].append(page_report)
            except Exception as exc:  # noqa: BLE001
                failures["PAGE_PREPARATION_FAILED"] += 1
                page_report.update(status="PAGE_PREPARATION_FAILED", error=f"{type(exc).__name__}: {exc}")
                doc["pages"].append(page_report)

        if not document_candidates:
            doc["tokens_materialized"] = 0
            documents.append(doc); shutil.rmtree(work, ignore_errors=True); continue

        # Exactly one pre-OCR, hash-selected numeric location per document.
        chosen = min(document_candidates, key=lambda x: x["rank"])
        with Image.open(chosen["crop_path"]) as opened:
            crop = opened.convert("RGB")
            truth = str(chosen["truth"])
            claim, tess_ms = tesseract_claim(crop)
            if claim and len(claim) <= 64:
                t0 = time.perf_counter(); decision = aligner.align(crop, claim)
                verifier_ms = (time.perf_counter() - t0) * 1000.0
                natural_status, prediction = _status(decision), _prediction(decision)
            else:
                natural_status, prediction, verifier_ms = "NO_CLAIM", "", 0.0
            seed = f"{acquisition['sha256']}:{chosen['page_number']}:{chosen['bbox_pt']}:{truth}"
            counterfactual = mutate_one_digit(truth, seed)
            t0 = time.perf_counter(); counter = aligner.align(crop, counterfactual)
            counter_ms = (time.perf_counter() - t0) * 1000.0
            crop_id = chosen["rank"][:20]
            crop_path = crops_dir / f"{crop_id}.png"
            crop.save(crop_path, optimize=True)

        accepted = natural_status == "ALIGNED"
        row = {
            "crop_id": crop_id, "document_id": document_id,
            "institution_code": candidate.institution_code,
            "institution_name": candidate.institution_name,
            "document_type": candidate.document_type, "process": candidate.process,
            "url_sha256": sha256_bytes(candidate.url.encode("utf-8")),
            "source_sha256": acquisition["sha256"],
            "page_number": chosen["page_number"],
            "bbox_pt": [round(float(v), 4) for v in chosen["bbox_pt"]],
            "bbox_px": chosen["bbox_px"], "truth": truth,
            "selection_rank_sha256": chosen["rank"],
            "tesseract_claim": claim, "claim_correct": claim == truth,
            "tesseract_runtime_ms": tess_ms,
            "verifier_status": natural_status, "verifier_prediction": prediction,
            "verifier_runtime_ms": verifier_ms, "accepted": accepted,
            "false_accepted": accepted and claim != truth,
            "counterfactual_claim": counterfactual,
            "counterfactual_status": _status(counter),
            "counterfactual_prediction": _prediction(counter),
            "counterfactual_runtime_ms": counter_ms,
            "counterfactual_false_accept": _status(counter) == "ALIGNED",
            "crop_sha256": sha256_file(crop_path),
            "crop_path": str(crop_path.relative_to(output_dir)),
        }
        observations.append(row)
        institutions_with_tokens.add(candidate.institution_code)
        doc["tokens_materialized"] = 1
        doc["selected_crop_id"] = crop_id
        documents.append(doc)
        if row["false_accepted"] or len(list(samples_dir.glob("*.png"))) < 40:
            shutil.copy2(crop_path, samples_dir / crop_path.name)
        shutil.rmtree(work, ignore_errors=True)

    baseline = [x for x in observations if x["tesseract_claim"]]
    baseline_false = sum(not x["claim_correct"] for x in baseline)
    accepted_rows = [x for x in observations if x["accepted"]]
    accepted_false = sum(x["false_accepted"] for x in accepted_rows)
    counter_false = sum(x["counterfactual_false_accept"] for x in observations)
    baseline_lower = clopper_pearson_lower(baseline_false, len(baseline))
    accepted_upper = clopper_pearson_upper(accepted_false, len(accepted_rows))
    reduction = baseline_lower / accepted_upper if accepted_upper > 0 else None
    statistical_gate = bool(
        len(accepted_rows) >= MIN_ACCEPTED_FOR_CERTIFICATE
        and len(observations) >= MIN_DOCUMENTS_FOR_CERTIFICATE
        and len(institutions_with_tokens) >= MIN_INSTITUTIONS_FOR_CERTIFICATE
        and accepted_upper <= baseline_lower / TARGET_REDUCTION
    )
    passed = stage == "final" and statistical_gate
    verifier_times = [x["verifier_runtime_ms"] for x in observations if x["verifier_runtime_ms"] > 0]
    tess_times = [x["tesseract_runtime_ms"] for x in observations]

    source_paths = [Path(x) for x in os.environ["OCR_HOLDOUT_SOURCE_FILES"].split(os.pathsep)]
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "files": {str(x): sha256_file(x) for x in source_paths},
            "development_processes_excluded": list(EXCLUDED_PROCESS_FRAGMENTS),
            "partitions": os.environ.get("OCR_HOLDOUT_PARTITIONS"),
            "stage": stage,
        },
        "protocol": {
            "risk_unit": "one pre-OCR hash-selected numeric location per document",
            "identity": "source_sha256 + page_number + bbox_pt",
            "ground_truth": "word-level PDF text coordinates; pages with >=75% full-page image excluded",
            "frozen_verifier_commit": os.environ.get("OCR_VERIFIER_COMMIT"),
            "familywise_alpha": FAMILYWISE_ALPHA,
            "per_bound_alpha_bonferroni": BOUND_ALPHA,
            "target_error_reduction": TARGET_REDUCTION,
            "minimum_accepted": MIN_ACCEPTED_FOR_CERTIFICATE,
            "minimum_documents": MIN_DOCUMENTS_FOR_CERTIFICATE,
            "minimum_institutions": MIN_INSTITUTIONS_FOR_CERTIFICATE,
            "threshold_tuning_on_final_holdout": False,
        },
        "execution": {
            "candidate_documents": len(candidates), "documents_attempted": attempted,
            "documents_with_tokens": len(observations),
            "institutions_with_tokens": len(institutions_with_tokens),
            "institution_codes_with_tokens": sorted(institutions_with_tokens),
            "numeric_crops": len(observations), "bank_initialization_ms": bank_ms,
            "failures": dict(sorted(failures.items())),
        },
        "baseline": {
            "predictions": len(baseline), "false_predictions": baseline_false,
            "observed_false_acceptance_rate": baseline_false / len(baseline) if baseline else None,
            "simultaneous_95pct_lower": baseline_lower,
        },
        "verifier": {
            "accepted": len(accepted_rows), "false_accepted": accepted_false,
            "observed_false_acceptance_rate": accepted_false / len(accepted_rows) if accepted_rows else None,
            "simultaneous_95pct_upper": accepted_upper,
            "accepted_coverage_of_documents": len(accepted_rows) / len(observations) if observations else 0.0,
            "certified_error_reduction_lower": reduction,
            "median_runtime_ms": statistics.median(verifier_times) if verifier_times else None,
            "p95_runtime_ms": p95(verifier_times),
        },
        "counterfactual": {
            "cases": len(observations), "false_accepts": counter_false,
            "rejection_or_abstention_rate": 1 - counter_false / len(observations) if observations else None,
        },
        "timing": {
            "median_tesseract_crop_ms": statistics.median(tess_times) if tess_times else None,
        },
        "decision": {
            "statistical_gate_passed": statistical_gate,
            "pass_statistical_10x": passed,
            "verdict": (
                "PASS_REAL_10X_CERTIFICATE" if passed
                else "CANARY_COMPLETE_NO_CERTIFICATE" if stage == "canary"
                else "HOLD_REAL_10X_NOT_CERTIFIED"
            ),
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0, "gcloud_used": False, "gpu_used": False,
            "paid_api_used": False, "logic_power_in_runtime": False,
            "production_modified": False,
        },
        "documents": documents, "observations": observations,
    }
    report["stable_payload_sha256"] = sha256_bytes(canonical_json(report).encode("utf-8"))
    return report


def write_outputs(report: Mapping[str, Any], census: Mapping[str, Any], output_dir: Path) -> None:
    reports = output_dir / "reports"; reports.mkdir(parents=True, exist_ok=True)
    (reports / "real_numeric_risk_holdout.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (reports / "candidate_census.json").write_text(
        json.dumps(census, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {key: report[key] for key in
               ("schema", "execution", "baseline", "verifier", "counterfactual", "decision", "stable_payload_sha256")}
    (reports / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "README.md").write_text(
        f"# OCR Real Risk Holdout v1\n\n`{report['decision']['verdict']}`\n\n"
        f"- documents/crops: {report['execution']['numeric_crops']}\n"
        f"- institutions: {report['execution']['institutions_with_tokens']}\n"
        f"- accepted: {report['verifier']['accepted']}\n"
        f"- false accepted: {report['verifier']['false_accepted']}\n"
        f"- certified reduction lower bound: {report['verifier']['certified_error_reduction_lower']}\n",
        encoding="utf-8")
    lines = [
        f"{sha256_file(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output_dir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
