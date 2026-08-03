"""Replay and select a region composer on the 20 previously opened pages.

These pages are development data only. The script binds the two exact frozen
preparation artifacts and annotations, evaluates a finite candidate family,
performs leave-one-process-out diagnostics, and freezes a candidate only for a
future independent holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ocr_reading_order_real_v1.core import canonical_json, sha256_bytes
from ocr_reading_order_honduras_router_v1.evaluate_holdout import order_metrics
from .composer import FROZEN_WIDE_RATIO, compose_with_parameters

SCHEMA = "ocr-reading-order-region-composer-v1/development/1"
EXPECTED_SELECTED = "band_30_65"
HEADER_FRACTIONS = (0.25, 0.30, 0.35, 0.40)
LOWER_SPLITS = (0.55, 0.65, 0.75)

SET1_PREPARATION_SHA256 = "9c2d97c0c3b7b0929d43c8a257bbac3f1cbbc8446270cb1d39c5b5c70bb3087a"
SET1_ARTIFACT_SHA256 = "dabdf25820e910e4d7b7966e419cc7e28b69082cca24d1367f7b9c9926e1ab1d"
SET2_PREPARATION_SHA256 = "7f870c18ecfab5c0d3fc22e1d64f123d0c1a13cf2ff2aeafec6d1d38294de291"
SET2_ARTIFACT_SHA256 = "37fda26ae4ddbb40ed97652318cf7db5f6a930e48894fee12fcba6331ed19bb3"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_preparation_sha(report: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "stable_payload_sha256"}
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def candidate_specs() -> list[dict[str, Any]]:
    specs = [{"name": "baseline", "header_fraction": None, "lower_split": None}]
    for header in HEADER_FRACTIONS:
        for lower in LOWER_SPLITS:
            specs.append(
                {
                    "name": f"band_{int(round(header * 100)):02d}_{int(round(lower * 100)):02d}",
                    "header_fraction": header,
                    "lower_split": lower,
                }
            )
    return specs


def evaluate_order(order: Sequence[str], annotation: Mapping[str, Any]) -> dict[str, Any]:
    return order_metrics(order, annotation)


def evaluate_candidate(
    specification: Mapping[str, Any],
    pages: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], float]:
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for page in pages:
        observation = page["observation"]
        if specification["name"] == "baseline":
            order = observation["baseline_order"]
            features = {"mode": "baseline"}
        else:
            decision = compose_with_parameters(
                observation["blocks"],
                float(observation["page"]["page_width"]),
                float(observation["page"]["page_height"]),
                header_fraction=float(specification["header_fraction"]),
                lower_split=float(specification["lower_split"]),
                wide_ratio=FROZEN_WIDE_RATIO,
            )
            order = decision.order
            features = decision.features
        metrics = evaluate_order(order, page["annotation"])
        rows.append(
            {
                "set": page["set"],
                "document_id": page["document_id"],
                "process": observation["document"]["process"],
                "document_type": observation["document"]["document_type"],
                "metrics": metrics,
                "features": features,
            }
        )
    return rows, time.perf_counter() - started


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    constraints = sum(int(row["metrics"]["constraint_pairs"]) for row in rows)
    correct = sum(int(row["metrics"]["correct_constraint_pairs"]) for row in rows)
    return {
        "pages": len(rows),
        "processes": len({row["process"] for row in rows}),
        "semantic_blocks": sum(int(row["metrics"]["semantic_blocks"]) for row in rows),
        "constraint_pairs": constraints,
        "weighted_constraint_accuracy": correct / max(constraints, 1),
        "exact_partial_order_rate": sum(bool(row["metrics"]["exact_partial_order"]) for row in rows) / max(len(rows), 1),
        "mean_canonical_read_order_edit": sum(float(row["metrics"]["canonical_read_order_edit"]) for row in rows) / max(len(rows), 1),
    }


def selection_key(specification: Mapping[str, Any], summary: Mapping[str, Any]) -> tuple[Any, ...]:
    safe = (
        abs(float(summary["weighted_constraint_accuracy"]) - 1.0) <= 1e-12
        and abs(float(summary["exact_partial_order_rate"]) - 1.0) <= 1e-12
    )
    header = float(specification["header_fraction"] or 0.0)
    lower = float(specification["lower_split"] or 0.0)
    return (
        not safe,
        float(summary["mean_canonical_read_order_edit"]),
        -header,
        -lower,
        str(specification["name"]),
    )


def solver_receipt() -> dict[str, Any]:
    worlds = (
        "whole_page_switching_is_sufficient",
        "local_region_composition_is_required",
        "text_semantics_are_required",
        "tesseract_blocks_are_too_coarse",
    )
    actions = {
        "threshold_sweep_seen_holdout": (2, 3, 2, 1),
        "new_page_level_router": (4, 5, 3, 2),
        "region_composition_development_replay": (7, 10, 7, 6),
        "add_layout_model": (6, 7, 9, 5),
    }
    best = [max(values[index] for values in actions.values()) for index in range(len(worlds))]
    regrets = {
        action: [best[index] - value for index, value in enumerate(values)]
        for action, values in actions.items()
    }
    max_regret = {action: max(values) for action, values in regrets.items()}
    selected = min(max_regret, key=lambda action: (max_regret[action], action))
    payload = {
        "problem_ir": {
            "schema": "logic-power-problem-ir/1",
            "problem_id": "OCR-HN-REGION-COMPOSITION-DEV-001",
            "goal": "find the minimum zero-cost structure that closes page-router oracle regret without reopening a holdout",
            "states": list(worlds),
            "conditions": [
                "external_spend_usd == 0",
                "gcloud_used == false",
                "seen pages are development only",
                "no threshold may be promoted without a new holdout",
                "Logic Power is absent from OCR runtime",
            ],
            "solution_concept": "finite minimax regret followed by exact development replay",
        },
        "utilities": {key: list(value) for key, value in sorted(actions.items())},
        "regrets": {key: value for key, value in sorted(regrets.items())},
        "max_regret": {key: max_regret[key] for key in sorted(max_regret)},
        "selected_experiment": selected,
    }
    return {**payload, "receipt_sha256": sha256_bytes(canonical_json(payload).encode("utf-8"))}


def load_pages(
    preparation: Mapping[str, Any],
    annotations: Mapping[str, Any],
    set_name: str,
) -> list[dict[str, Any]]:
    observations = {
        item["document"]["id"]: item
        for item in preparation["observations"]
        if item.get("status") == "PREPARED"
    }
    annotation_map = {item["document_id"]: item for item in annotations["annotations"]}
    if set(observations) != set(annotation_map):
        raise ValueError(f"{set_name} annotation/preparation denominator mismatch")
    return [
        {
            "set": set_name,
            "document_id": document_id,
            "observation": observations[document_id],
            "annotation": annotation_map[document_id],
        }
        for document_id in sorted(observations)
    ]


def build_report(
    set1_preparation: Mapping[str, Any],
    set1_annotations: Mapping[str, Any],
    set2_preparation: Mapping[str, Any],
    set2_annotations: Mapping[str, Any],
    set1_artifact: Path | None,
    set2_artifact: Path | None,
) -> dict[str, Any]:
    set1_sha = stable_preparation_sha(set1_preparation)
    set2_sha = stable_preparation_sha(set2_preparation)
    if set1_sha != SET1_PREPARATION_SHA256 or set1_preparation.get("stable_payload_sha256") != set1_sha:
        raise ValueError("set1 preparation binding mismatch")
    if set2_sha != SET2_PREPARATION_SHA256 or set2_preparation.get("stable_payload_sha256") != set2_sha:
        raise ValueError("set2 preparation binding mismatch")
    if set1_artifact is not None and sha256_file(set1_artifact) != SET1_ARTIFACT_SHA256:
        raise ValueError("set1 artifact ZIP mismatch")
    if set2_artifact is not None and sha256_file(set2_artifact) != SET2_ARTIFACT_SHA256:
        raise ValueError("set2 artifact ZIP mismatch")

    pages = [
        *load_pages(set1_preparation, set1_annotations, "honduras_seen_1"),
        *load_pages(set2_preparation, set2_annotations, "honduras_seen_2"),
    ]
    if len(pages) != 20 or len({page["observation"]["document"]["process"] for page in pages}) != 10:
        raise ValueError("development denominator drift")

    specifications = candidate_specs()
    evaluations: dict[str, Any] = {}
    rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    runtimes: dict[str, float] = {}
    for specification in specifications:
        rows, elapsed = evaluate_candidate(specification, pages)
        summary = summarize(rows)
        evaluations[specification["name"]] = {
            "specification": specification,
            "summary": summary,
        }
        rows_by_candidate[specification["name"]] = rows
        runtimes[specification["name"]] = elapsed

    selected_name = min(
        evaluations,
        key=lambda name: selection_key(
            evaluations[name]["specification"],
            evaluations[name]["summary"],
        ),
    )
    selected = evaluations[selected_name]
    selected_rows = rows_by_candidate[selected_name]
    baseline_rows = rows_by_candidate["baseline"]

    baseline_by_id = {row["document_id"]: row for row in baseline_rows}
    dispositions: list[dict[str, Any]] = []
    for row in selected_rows:
        baseline = baseline_by_id[row["document_id"]]["metrics"]
        candidate = row["metrics"]
        candidate_key = (
            -float(candidate["constraint_accuracy"]),
            float(candidate["canonical_read_order_edit"]),
        )
        baseline_key = (
            -float(baseline["constraint_accuracy"]),
            float(baseline["canonical_read_order_edit"]),
        )
        disposition = (
            "COMPOSER_BETTER"
            if candidate_key < baseline_key
            else "COMPOSER_WORSE"
            if candidate_key > baseline_key
            else "TIE"
        )
        dispositions.append(
            {
                "document_id": row["document_id"],
                "process": row["process"],
                "disposition": disposition,
                "baseline": baseline,
                "composer": candidate,
            }
        )

    processes = sorted({page["observation"]["document"]["process"] for page in pages})
    folds: list[dict[str, Any]] = []
    for process in processes:
        training_pages = [page for page in pages if page["observation"]["document"]["process"] != process]
        testing_pages = [page for page in pages if page["observation"]["document"]["process"] == process]
        fold_evaluations: dict[str, Any] = {}
        for specification in specifications:
            train_rows, _ = evaluate_candidate(specification, training_pages)
            fold_evaluations[specification["name"]] = {
                "specification": specification,
                "summary": summarize(train_rows),
            }
        fold_selected = min(
            fold_evaluations,
            key=lambda name: selection_key(
                fold_evaluations[name]["specification"],
                fold_evaluations[name]["summary"],
            ),
        )
        test_rows, _ = evaluate_candidate(
            fold_evaluations[fold_selected]["specification"],
            testing_pages,
        )
        folds.append(
            {
                "held_out_process": process,
                "selected_candidate": fold_selected,
                "matches_full_selection": fold_selected == selected_name,
                "held_out_summary": summarize(test_rows),
            }
        )

    baseline_summary = evaluations["baseline"]["summary"]
    selected_summary = selected["summary"]
    baseline_edit = float(baseline_summary["mean_canonical_read_order_edit"])
    selected_edit = float(selected_summary["mean_canonical_read_order_edit"])
    relative_improvement = (baseline_edit - selected_edit) / baseline_edit if baseline_edit > 0 else 0.0
    improved_pages = sum(item["disposition"] == "COMPOSER_BETTER" for item in dispositions)
    harmed_pages = sum(item["disposition"] == "COMPOSER_WORSE" for item in dispositions)
    stable_folds = sum(item["matches_full_selection"] for item in folds)
    fold_safety = sum(
        abs(float(item["held_out_summary"]["weighted_constraint_accuracy"]) - 1.0) <= 1e-12
        and abs(float(item["held_out_summary"]["exact_partial_order_rate"]) - 1.0) <= 1e-12
        for item in folds
    )

    freeze_gate = (
        selected_name == EXPECTED_SELECTED
        and abs(float(selected_summary["weighted_constraint_accuracy"]) - 1.0) <= 1e-12
        and abs(float(selected_summary["exact_partial_order_rate"]) - 1.0) <= 1e-12
        and relative_improvement >= 0.50
        and harmed_pages == 0
        and improved_pages >= 5
        and stable_folds >= 8
    )
    decision = {
        "verdict": "FREEZE_FOR_NEW_HOLDOUT" if freeze_gate else "DO_NOT_FREEZE",
        "freeze_gate": freeze_gate,
        "selected_candidate": selected_name,
        "next_experiment": (
            "evaluate the frozen composer on unused Honduran processes with first/last page rules"
            if freeze_gate
            else "acquire a new separating observation before changing the composer"
        ),
        "development_only": True,
        "automatic_production_change": False,
    }

    stable_payload = {
        "schema": SCHEMA,
        "bindings": {
            "set1_preparation_sha256": set1_sha,
            "set1_artifact_sha256": SET1_ARTIFACT_SHA256,
            "set2_preparation_sha256": set2_sha,
            "set2_artifact_sha256": SET2_ARTIFACT_SHA256,
            "set1_artifact_verified": set1_artifact is not None,
            "set2_artifact_verified": set2_artifact is not None,
            "set1_annotations_sha256": sha256_bytes(canonical_json(set1_annotations).encode("utf-8")),
            "set2_annotations_sha256": sha256_bytes(canonical_json(set2_annotations).encode("utf-8")),
        },
        "solver": solver_receipt(),
        "development": {
            "pages": len(pages),
            "processes": len(processes),
            "candidate_family": specifications,
            "selection_rule": (
                "perfect weighted constraints and exact partial-order pages; then minimum mean canonical edit; "
                "ties prefer more protected header and later lower split"
            ),
            "selected_candidate": selected_name,
            "evaluations": evaluations,
            "selected_rows": selected_rows,
            "baseline_comparison": dispositions,
            "leave_one_process_out": folds,
            "summary": {
                "baseline": baseline_summary,
                "selected": selected_summary,
                "relative_edit_improvement": relative_improvement,
                "improved_pages": improved_pages,
                "harmed_pages": harmed_pages,
                "tied_pages": len(dispositions) - improved_pages - harmed_pages,
                "selection_stable_folds": stable_folds,
                "selection_stability_rate": stable_folds / len(folds),
                "fold_selected_candidate_safety_rate": fold_safety / len(folds),
            },
        },
        "decision": decision,
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "paid_api_used": False,
            "gpu_used": False,
            "ocr_rerun_used": False,
            "logic_power_in_runtime": False,
            "seen_pages_promoted_as_holdout": False,
        },
    }
    return {
        **stable_payload,
        "stable_payload_sha256": sha256_bytes(canonical_json(stable_payload).encode("utf-8")),
        "runtime": {
            "candidate_seconds": runtimes,
            "selected_microseconds_per_page": runtimes[selected_name] * 1_000_000 / len(pages),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set1-preparation", type=Path, required=True)
    parser.add_argument("--set1-annotations", type=Path, required=True)
    parser.add_argument("--set2-preparation", type=Path, required=True)
    parser.add_argument("--set2-annotations", type=Path, required=True)
    parser.add_argument("--set1-artifact", type=Path)
    parser.add_argument("--set2-artifact", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_reading_order_region_composer_v1/development"),
    )
    args = parser.parse_args()
    report = build_report(
        json.loads(args.set1_preparation.read_text(encoding="utf-8")),
        json.loads(args.set1_annotations.read_text(encoding="utf-8")),
        json.loads(args.set2_preparation.read_text(encoding="utf-8")),
        json.loads(args.set2_annotations.read_text(encoding="utf-8")),
        args.set1_artifact,
        args.set2_artifact,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "development_report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "development_report.sha256").write_text(
        f"{sha256_file(path)}  development_report.json\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "summary": report["development"]["summary"],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
                "runtime": report["runtime"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
