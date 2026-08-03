"""Evaluate baseline y/x versus frozen XY-cut on the Honduran holdout.

The primary ground truth is a partial order over semantic Tesseract blocks.
Decorative/noise blocks remain in the frozen observations but are excluded
from semantic scoring. Ambiguous parallel signature columns are represented
as a DAG rather than forced into an arbitrary total order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ocr_reading_order_real_v1.core import canonical_json, levenshtein, sha256_bytes

SCHEMA = "ocr-reading-order-honduras-v1/evaluation/1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_preparation_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "stable_payload_sha256"}


def transitive_closure(nodes: Sequence[str], edges: Sequence[Sequence[str]]) -> list[tuple[str, str]]:
    node_set = set(nodes)
    reach: dict[str, set[str]] = {node: set() for node in nodes}
    for raw_edge in edges:
        if len(raw_edge) != 2:
            raise ValueError("must_precede edge must have two nodes")
        left, right = str(raw_edge[0]), str(raw_edge[1])
        if left not in node_set or right not in node_set or left == right:
            raise ValueError(f"invalid must_precede edge: {raw_edge}")
        reach[left].add(right)
    changed = True
    while changed:
        changed = False
        for node in nodes:
            expanded = set(reach[node])
            for successor in tuple(reach[node]):
                expanded.update(reach[successor])
            if expanded != reach[node]:
                reach[node] = expanded
                changed = True
    if any(node in reach[node] for node in nodes):
        raise ValueError("must_precede graph contains a cycle")
    return sorted((left, right) for left in nodes for right in reach[left])


def order_metrics(predicted_full: Sequence[str], annotation: Mapping[str, Any]) -> dict[str, Any]:
    semantic = [str(value) for value in annotation["semantic_block_ids"]]
    semantic_set = set(semantic)
    predicted = [value for value in predicted_full if value in semantic_set]
    if len(predicted) != len(semantic) or set(predicted) != semantic_set:
        raise ValueError("predicted semantic order is not a permutation")
    canonical = [str(value) for value in annotation["correct_order"]]
    if len(canonical) != len(semantic) or set(canonical) != semantic_set:
        raise ValueError("canonical order is not a permutation")
    closure = transitive_closure(semantic, annotation["must_precede"])
    position = {value: index for index, value in enumerate(predicted)}
    violations = [[left, right] for left, right in closure if position[left] >= position[right]]
    constraint_count = len(closure)
    correct_count = constraint_count - len(violations)
    return {
        "semantic_blocks": len(semantic),
        "constraint_pairs": constraint_count,
        "correct_constraint_pairs": correct_count,
        "constraint_accuracy": correct_count / max(constraint_count, 1),
        "violations": violations,
        "exact_partial_order": not violations,
        "canonical_read_order_edit": levenshtein(canonical, predicted) / max(len(canonical), len(predicted), 1),
        "predicted_semantic_order": predicted,
    }


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / max(len(items), 1)


def aggregate(rows: Sequence[Mapping[str, Any]], algorithm: str) -> dict[str, Any]:
    total_constraints = sum(int(row[algorithm]["constraint_pairs"]) for row in rows)
    total_correct = sum(int(row[algorithm]["correct_constraint_pairs"]) for row in rows)
    return {
        "pages": len(rows),
        "semantic_blocks": sum(int(row[algorithm]["semantic_blocks"]) for row in rows),
        "constraint_pairs": total_constraints,
        "weighted_constraint_accuracy": total_correct / max(total_constraints, 1),
        "mean_constraint_accuracy": _mean(float(row[algorithm]["constraint_accuracy"]) for row in rows),
        "exact_partial_order_rate": _mean(float(bool(row[algorithm]["exact_partial_order"])) for row in rows),
        "mean_canonical_read_order_edit": _mean(float(row[algorithm]["canonical_read_order_edit"]) for row in rows),
    }


def compare_page(row: Mapping[str, Any]) -> str:
    baseline = row["baseline"]
    geometry = row["geometry"]
    baseline_key = (
        -float(baseline["constraint_accuracy"]),
        float(baseline["canonical_read_order_edit"]),
    )
    geometry_key = (
        -float(geometry["constraint_accuracy"]),
        float(geometry["canonical_read_order_edit"]),
    )
    if geometry_key < baseline_key:
        return "GEOMETRY_BETTER"
    if geometry_key > baseline_key:
        return "BASELINE_BETTER"
    return "TIE"


def build_report(preparation: Mapping[str, Any], annotations: Mapping[str, Any], artifact_zip: Path | None) -> dict[str, Any]:
    preparation_payload = stable_preparation_payload(preparation)
    preparation_sha = sha256_bytes(canonical_json(preparation_payload).encode("utf-8"))
    if preparation.get("stable_payload_sha256") != preparation_sha:
        raise ValueError("preparation stable payload hash mismatch")
    if preparation_sha != annotations["preparation_stable_payload_sha256"]:
        raise ValueError("annotations are not bound to this preparation")
    artifact_sha = sha256_file(artifact_zip) if artifact_zip is not None else None
    if artifact_sha is not None and artifact_sha != annotations["preparation_artifact_sha256"]:
        raise ValueError("preparation artifact ZIP hash mismatch")

    observations = {
        item["document"]["id"]: item
        for item in preparation["observations"]
        if item.get("status") == "PREPARED"
    }
    annotation_items = {item["document_id"]: item for item in annotations["annotations"]}
    if set(observations) != set(annotation_items):
        raise ValueError("annotation/preparation document denominator mismatch")

    rows: list[dict[str, Any]] = []
    for document_id in sorted(observations):
        observation = observations[document_id]
        annotation = annotation_items[document_id]
        available = [block["block_id"] for block in observation["blocks"]]
        semantic = [str(value) for value in annotation["semantic_block_ids"]]
        ignored = [str(value) for value in annotation["ignored_block_ids"]]
        if set(semantic) & set(ignored):
            raise ValueError(f"semantic/ignored overlap: {document_id}")
        if len(semantic) + len(ignored) != len(available) or set(semantic) | set(ignored) != set(available):
            raise ValueError(f"semantic/ignored partition mismatch: {document_id}")
        baseline = order_metrics(observation["baseline_order"], annotation)
        geometry = order_metrics(observation["geometry_order"], annotation)
        row = {
            "document_id": document_id,
            "process": observation["document"]["process"],
            "document_type": observation["document"]["document_type"],
            "confidence": annotation["confidence"],
            "ignored_block_ids": ignored,
            "baseline": baseline,
            "geometry": geometry,
        }
        row["comparison"] = compare_page(row)
        rows.append(row)

    baseline_aggregate = aggregate(rows, "baseline")
    geometry_aggregate = aggregate(rows, "geometry")
    improved = sum(row["comparison"] == "GEOMETRY_BETTER" for row in rows)
    harmed = sum(row["comparison"] == "BASELINE_BETTER" for row in rows)
    tied = len(rows) - improved - harmed
    baseline_edit = float(baseline_aggregate["mean_canonical_read_order_edit"])
    geometry_edit = float(geometry_aggregate["mean_canonical_read_order_edit"])
    relative_edit_improvement = (baseline_edit - geometry_edit) / baseline_edit if baseline_edit > 0 else 0.0
    constraint_delta = (
        float(geometry_aggregate["weighted_constraint_accuracy"])
        - float(baseline_aggregate["weighted_constraint_accuracy"])
    )
    universal_pass = (
        constraint_delta >= 0.02
        and relative_edit_improvement >= 0.20
        and float(geometry_aggregate["exact_partial_order_rate"])
        >= float(baseline_aggregate["exact_partial_order_rate"])
        and harmed / len(rows) <= 0.20
    )
    if universal_pass:
        verdict = "PROMOTE_HONDURAN_GEOMETRY_CANDIDATE"
        next_experiment = "independent annotation replay before production integration"
    elif improved > 0 and harmed > 0:
        verdict = "CONTEXT_DEPENDENT_BUILD_ROUTER"
        next_experiment = "predeclare a header-versus-body geometry router and test it on a new sealed Honduran holdout"
    else:
        verdict = "REJECT_UNIVERSAL_HONDURAN_PROMOTION"
        next_experiment = "retain Tesseract baseline for this domain and acquire genuinely multi-column Honduran pages"

    oracle_rows = [
        min(
            float(row["baseline"]["canonical_read_order_edit"]),
            float(row["geometry"]["canonical_read_order_edit"]),
        )
        for row in rows
    ]
    stable_payload = {
        "schema": SCHEMA,
        "preparation": {
            "stable_payload_sha256": preparation_sha,
            "artifact_id": annotations["preparation_artifact_id"],
            "artifact_sha256": annotations["preparation_artifact_sha256"],
            "artifact_zip_verified": artifact_sha is not None,
        },
        "annotations": {
            "sha256": sha256_bytes(canonical_json(annotations).encode("utf-8")),
            "method": annotations["annotation_method"],
            "blinding": annotations["blinding"],
            "independence": annotations["independence"],
            "ground_truth": annotations["primary_ground_truth"],
        },
        "rows": rows,
        "aggregate": {
            "baseline": baseline_aggregate,
            "geometry": geometry_aggregate,
            "geometry_better_pages": improved,
            "baseline_better_pages": harmed,
            "tied_pages": tied,
            "relative_canonical_edit_improvement": relative_edit_improvement,
            "weighted_constraint_accuracy_delta": constraint_delta,
            "oracle_best_mean_canonical_edit": _mean(oracle_rows),
        },
        "decision": {
            "verdict": verdict,
            "universal_promotion_gate": universal_pass,
            "next_experiment": next_experiment,
            "automatic_production_change": False,
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "paid_api_used": False,
            "gpu_used": False,
            "second_ocr_pass_used": False,
            "logic_power_in_runtime": False,
        },
    }
    return {
        **stable_payload,
        "stable_payload_sha256": sha256_bytes(canonical_json(stable_payload).encode("utf-8")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, default=Path("ocr_reading_order_honduras_v1/annotations.json"))
    parser.add_argument("--artifact-zip", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("ocr_reading_order_honduras_v1/evaluation"))
    args = parser.parse_args()
    preparation = json.loads(args.preparation.read_text(encoding="utf-8"))
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
    report = build_report(preparation, annotations, args.artifact_zip)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "honduras_evaluation.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "honduras_evaluation.sha256").write_text(
        f"{sha256_file(path)}  honduras_evaluation.json\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "aggregate": report["aggregate"],
        "decision": report["decision"],
        "stable_payload_sha256": report["stable_payload_sha256"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
