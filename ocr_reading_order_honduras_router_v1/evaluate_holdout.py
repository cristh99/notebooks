"""Evaluate baseline, universal XY-cut and frozen contextual router."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ocr_reading_order_real_v1.core import canonical_json, levenshtein, sha256_bytes

SCHEMA = "ocr-reading-order-honduras-router-v1/evaluation/1"
ALGORITHMS = ("baseline", "geometry", "router")


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
            raise ValueError("must_precede edge must contain two nodes")
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
    predicted = [str(value) for value in predicted_full if str(value) in semantic_set]
    if len(predicted) != len(semantic) or set(predicted) != semantic_set:
        raise ValueError("predicted semantic order is not a permutation")
    canonical = [str(value) for value in annotation["correct_order"]]
    if len(canonical) != len(semantic) or set(canonical) != semantic_set:
        raise ValueError("canonical order is not a semantic permutation")
    closure = transitive_closure(semantic, annotation["must_precede"])
    position = {value: index for index, value in enumerate(predicted)}
    violations = [[left, right] for left, right in closure if position[left] >= position[right]]
    constraints = len(closure)
    correct = constraints - len(violations)
    return {
        "semantic_blocks": len(semantic),
        "constraint_pairs": constraints,
        "correct_constraint_pairs": correct,
        "constraint_accuracy": correct / max(constraints, 1),
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


def metric_key(metrics: Mapping[str, Any]) -> tuple[float, float, float]:
    return (
        -float(metrics["constraint_accuracy"]),
        float(metrics["canonical_read_order_edit"]),
        -float(bool(metrics["exact_partial_order"])),
    )


def aggregate_key(metrics: Mapping[str, Any]) -> tuple[float, float, float]:
    return (
        -float(metrics["weighted_constraint_accuracy"]),
        float(metrics["mean_canonical_read_order_edit"]),
        -float(metrics["exact_partial_order_rate"]),
    )


def compare_algorithms(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = {algorithm: metric_key(row[algorithm]) for algorithm in ALGORITHMS}
    best_key = min(keys.values())
    winners = sorted(algorithm for algorithm, key in keys.items() if key == best_key)
    best_universal_key = min(keys["baseline"], keys["geometry"])
    if keys["router"] < best_universal_key:
        router_disposition = "ROUTER_BETTER"
    elif keys["router"] > best_universal_key:
        router_disposition = "ROUTER_WORSE"
    else:
        router_disposition = "ROUTER_TIES_BEST_UNIVERSAL"
    return {
        "winners": winners,
        "router_disposition": router_disposition,
    }


def build_report(
    preparation: Mapping[str, Any],
    annotations: Mapping[str, Any],
    artifact_zip: Path | None,
) -> dict[str, Any]:
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
        available = [str(block["block_id"]) for block in observation["blocks"]]
        semantic = [str(value) for value in annotation["semantic_block_ids"]]
        ignored = [str(value) for value in annotation["ignored_block_ids"]]
        if set(semantic) & set(ignored):
            raise ValueError(f"semantic/ignored overlap: {document_id}")
        if len(semantic) + len(ignored) != len(available) or set(semantic) | set(ignored) != set(available):
            raise ValueError(f"semantic/ignored partition mismatch: {document_id}")
        row: dict[str, Any] = {
            "document_id": document_id,
            "process": observation["document"]["process"],
            "document_type": observation["document"]["document_type"],
            "page_rule": observation["document"]["page_rule"],
            "page_number": observation["page"]["page_number"],
            "pdf_page_count": observation["page"]["pdf_page_count"],
            "confidence": annotation["confidence"],
            "ignored_block_ids": ignored,
            "router_selected": observation["router_selected"],
            "router_reason": observation["router_reason"],
            "router_features": observation["router_features"],
            "baseline": order_metrics(observation["baseline_order"], annotation),
            "geometry": order_metrics(observation["geometry_order"], annotation),
            "router": order_metrics(observation["router_order"], annotation),
        }
        row["comparison"] = compare_algorithms(row)
        rows.append(row)

    aggregates = {algorithm: aggregate(rows, algorithm) for algorithm in ALGORITHMS}
    best_universal_name = min(("baseline", "geometry"), key=lambda name: aggregate_key(aggregates[name]))
    best_universal = aggregates[best_universal_name]
    router = aggregates["router"]
    router_better = sum(row["comparison"]["router_disposition"] == "ROUTER_BETTER" for row in rows)
    router_worse = sum(row["comparison"]["router_disposition"] == "ROUTER_WORSE" for row in rows)
    router_ties = len(rows) - router_better - router_worse
    oracle_edits = [
        min(
            float(row["baseline"]["canonical_read_order_edit"]),
            float(row["geometry"]["canonical_read_order_edit"]),
        )
        for row in rows
    ]
    oracle_constraint_correct = sum(
        max(
            int(row["baseline"]["correct_constraint_pairs"]),
            int(row["geometry"]["correct_constraint_pairs"]),
        )
        for row in rows
    )
    total_constraints = sum(int(row["baseline"]["constraint_pairs"]) for row in rows)
    oracle_accuracy = oracle_constraint_correct / max(total_constraints, 1)
    router_constraint_gap = oracle_accuracy - float(router["weighted_constraint_accuracy"])
    router_edit_regret = float(router["mean_canonical_read_order_edit"]) - _mean(oracle_edits)

    promotion_gate = (
        aggregate_key(router) <= aggregate_key(best_universal)
        and float(router["weighted_constraint_accuracy"]) >= float(best_universal["weighted_constraint_accuracy"])
        and float(router["mean_canonical_read_order_edit"]) <= float(best_universal["mean_canonical_read_order_edit"])
        and float(router["exact_partial_order_rate"]) >= float(best_universal["exact_partial_order_rate"])
        and router_worse / len(rows) <= 0.10
        and router_constraint_gap <= 0.01
        and router_edit_regret <= 0.02
    )
    if promotion_gate:
        verdict = "PROMOTE_ROUTER_TO_LARGER_BLINDED_HOLDOUT"
        next_experiment = "larger prospectively sampled Honduran holdout with blinded independent annotation"
    else:
        verdict = "REJECT_ROUTER_PROMOTION"
        next_experiment = "retain best universal method and redesign only after a new separating observation"

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
            **aggregates,
            "best_universal": best_universal_name,
            "router_better_pages": router_better,
            "router_worse_pages": router_worse,
            "router_tied_pages": router_ties,
            "oracle_best_mean_canonical_edit": _mean(oracle_edits),
            "oracle_weighted_constraint_accuracy": oracle_accuracy,
            "router_constraint_gap_to_oracle": router_constraint_gap,
            "router_canonical_edit_regret_to_oracle": router_edit_regret,
        },
        "decision": {
            "verdict": verdict,
            "promotion_gate": promotion_gate,
            "next_experiment": next_experiment,
            "automatic_production_change": False,
        },
        "constraints": preparation["constraints"],
    }
    return {
        **stable_payload,
        "stable_payload_sha256": sha256_bytes(canonical_json(stable_payload).encode("utf-8")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument(
        "--annotations",
        type=Path,
        default=Path("ocr_reading_order_honduras_router_v1/annotations.json"),
    )
    parser.add_argument("--artifact-zip", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ocr_reading_order_honduras_router_v1/evaluation"),
    )
    args = parser.parse_args()
    preparation = json.loads(args.preparation.read_text(encoding="utf-8"))
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
    report = build_report(preparation, annotations, args.artifact_zip)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "router_evaluation.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "router_evaluation.sha256").write_text(
        f"{sha256_file(path)}  router_evaluation.json\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "aggregate": report["aggregate"],
                "decision": report["decision"],
                "stable_payload_sha256": report["stable_payload_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
