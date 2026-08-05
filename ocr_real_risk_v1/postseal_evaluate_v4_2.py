"""Post-seal evaluator for v4.2 selective OCR flags.

Annotations are unavailable to candidate inference. This module is invoked only
after a sealed decision record exists. It parses numeric truth, including short
receipt tax-code suffixes such as ``30.00 SR``, matches truth geometrically, and
reports accepted/quarantined risk units without running a significance look.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

_DIGIT = re.compile(r"[0-9]")
_AMOUNT = re.compile(
    r"^\s*(?:(?:RM|MYR|USD|US\$|\$)\s*:?\s*)?"
    r"([+-]?[0-9]+(?:[.,][0-9]+)?)"
    r"(?:\s+(?:[A-Z]{1,4}|\*))?\s*$",
    re.IGNORECASE,
)
_YEAR = re.compile(r"^(?:19|20)[0-9]{2}$")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digits(value: object) -> str:
    return "".join(_DIGIT.findall(str(value or "")))


def numeric_truth(text: str) -> str | None:
    match = _AMOUNT.fullmatch(str(text or ""))
    if match is None:
        return None
    digits = canonical_digits(match.group(1))
    if not 4 <= len(digits) <= 12 or _YEAR.fullmatch(digits):
        return None
    if len(digits) >= 6 and len(set(digits)) == 1:
        return None
    return digits


def parse_annotations(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", errors="strict", newline="") as handle:
        for line, row in enumerate(csv.reader(handle), start=1):
            if len(row) < 9:
                continue
            try:
                coords = [float(value) for value in row[:8]]
            except ValueError:
                continue
            text = ",".join(row[8:]).strip()
            truth = numeric_truth(text)
            if truth is None:
                continue
            output.append({
                "line": line,
                "text": text,
                "truth": truth,
                "bbox": [min(coords[0::2]), min(coords[1::2]),
                         max(coords[0::2]), max(coords[1::2])],
            })
    return output


def _overlap(a: Sequence[float], b: Sequence[float]) -> dict[str, float]:
    ax0, ay0, ax1, ay1 = map(float, a)
    bx0, by0, bx1, by1 = map(float, b)
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(1e-9, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1e-9, (bx1 - bx0) * (by1 - by0))
    union = area_a + area_b - inter
    ca, cb = ((ax0 + ax1) / 2, (ay0 + ay1) / 2), ((bx0 + bx1) / 2, (by0 + by1) / 2)
    return {
        "iou": inter / union,
        "flag_coverage": inter / area_a,
        "truth_coverage": inter / area_b,
        "center_distance": ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5,
    }


def match_truth(bbox: Sequence[float], truths: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, float]] | None:
    fx0, fy0, fx1, fy1 = map(float, bbox)
    center = ((fx0 + fx1) / 2, (fy0 + fy1) / 2)
    ranked: list[tuple[float, int, dict[str, Any], dict[str, float]]] = []
    for truth in truths:
        metrics = _overlap(bbox, truth["bbox"])
        tx0, ty0, tx1, ty1 = map(float, truth["bbox"])
        inside = tx0 <= center[0] <= tx1 and ty0 <= center[1] <= ty1
        if metrics["flag_coverage"] < 0.35 and metrics["truth_coverage"] < 0.35 and not inside:
            continue
        score = (3 * metrics["flag_coverage"] + 2 * metrics["truth_coverage"]
                 + metrics["iou"] - 0.001 * metrics["center_distance"])
        ranked.append((score, -int(truth["line"]), truth, metrics))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2], ranked[0][3]


def evaluate(sealed: dict[str, Any], annotation_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    receipts: dict[str, Any] = {}
    for page in sealed["pages"]:
        flags = page.get("semantic_flags") or []
        if not flags:
            continue
        path = annotation_dir / f"{page['stem']}.txt"
        truths = parse_annotations(path)
        receipts[page["stem"]] = {"sha256": sha256_path(path), "numeric_truths": len(truths)}
        for flag in flags:
            match = match_truth(flag["bbox"], truths)
            if match is None:
                rows.append({"stem": page["stem"], "token_index": flag["token_index"],
                             "status": "NO_GEOMETRIC_TRUTH_MATCH"})
                continue
            truth, geometry = match
            action = flag["decision"]["action"]
            accepted = action == "REPLACE"
            rows.append({
                "stem": page["stem"], "token_index": flag["token_index"], "status": "EVALUATED",
                "baseline": flag["baseline_digits"], "rival": flag["rival_digits"],
                "truth": truth["truth"], "truth_text": truth["text"], "truth_line": truth["line"],
                "geometry": geometry, "baseline_correct": flag["baseline_digits"] == truth["truth"],
                "action": action, "reason": flag["decision"]["reason_code"],
                "decision_sha256": flag["decision"].get("decision_sha256"),
                "accepted": accepted, "output": flag["decision"]["output"],
                "final_correct_if_accepted": (flag["decision"]["output"] == truth["truth"]) if accepted else None,
            })
    evaluated = [row for row in rows if row["status"] == "EVALUATED"]
    accepted = [row for row in evaluated if row["accepted"]]
    metrics = {
        "flags": len(rows), "evaluated": len(evaluated),
        "baseline_errors": sum(not row["baseline_correct"] for row in evaluated),
        "false_semantic_flags": sum(row["baseline_correct"] for row in evaluated),
        "accepted": len(accepted), "quarantined": len(evaluated) - len(accepted),
        "final_errors_among_accepted": sum(not row["final_correct_if_accepted"] for row in accepted),
        "false_replacements": sum(row["accepted"] and row["rival"] != row["truth"] for row in evaluated),
    }
    metrics["selective_coverage"] = metrics["accepted"] / metrics["evaluated"] if metrics["evaluated"] else None
    return {"schema": "ocr-v4-2-postseal-evaluation/1", "metrics": metrics,
            "annotation_receipts": receipts, "rows": rows,
            "significance_look_performed": False,
            "annotations_used_at_inference": False}


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
