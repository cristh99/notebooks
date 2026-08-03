"""Frozen agent-visual annotations for the independent Honduran router holdout.

The exact numbered overlays were inspected once after the preparation artifact
was frozen. Every observed Tesseract block is partitioned into semantic or
ignored. Semantic ground truth is a partial-order DAG; a canonical total order
is retained only as a secondary tie-break and for deterministic replay.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA = "ocr-reading-order-honduras-router-v1/annotations/2"
PREPARATION_RUN_ID = 30856610387
PREPARATION_ARTIFACT_ID = 8872737306
PREPARATION_ARTIFACT_SHA256 = "37fda26ae4ddbb40ed97652318cf7db5f6a930e48894fee12fcba6331ed19bb3"
PREPARATION_STABLE_PAYLOAD_SHA256 = "7f870c18ecfab5c0d3fc22e1d64f123d0c1a13cf2ff2aeafec6d1d38294de291"
MANIFEST_SHA256 = "e738ace06157b1aa155e58aacba98793261b2215dc257b18970b37373f164359"


def chain(nodes: Sequence[str]) -> list[list[str]]:
    return [[nodes[index], nodes[index + 1]] for index in range(len(nodes) - 1)]


def cross(left: Iterable[str], right: Iterable[str]) -> list[list[str]]:
    return [[source, target] for source in left for target in right]


def entry(
    document_id: str,
    available: Sequence[str],
    semantic: Sequence[str],
    ignored: Sequence[str],
    must_precede: Sequence[Sequence[str]],
    *,
    confidence: str,
    ambiguity_note: str,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "available_block_ids": list(available),
        "semantic_block_ids": list(semantic),
        "ignored_block_ids": list(ignored),
        "correct_order": list(semantic),
        "must_precede": [list(edge) for edge in must_precede],
        "confidence": confidence,
        "ambiguity_note": ambiguity_note,
    }


def build_annotations() -> dict[str, Any]:
    annotations: list[dict[str, Any]] = []

    semantic = [
        "B000", "B002", "B003", "B005", "B006", "B008", "B009", "B007",
        "B010", "B011", "B013", "B014", "B015", "B016", "B017", "B018",
    ]
    headers = ["B006", "B008", "B009", "B007"]
    edges = chain(["B000", "B002", "B003", "B005"])
    edges += [["B005", block] for block in headers]
    edges += [[block, "B010"] for block in headers]
    edges += chain(["B010", "B011", "B013", "B014", "B015", "B016", "B017", "B018"])
    annotations.append(
        entry(
            "HR01_tender_HN-SEDECOAS-371604-CW-RFB",
            [f"B{index:03d}" for index in range(19)],
            semantic,
            ["B001", "B004", "B012"],
            edges,
            confidence="HIGH",
            ambiguity_note=(
                "Table header cells are parallel within one row; their left-to-right "
                "canonical order is retained, while the primary DAG only requires all "
                "headers before the data row."
            ),
        )
    )

    semantic = ["B002", "B003", "B004", "B005", "B006", "B008", "B007", "B010", "B009"]
    edges = chain(["B002", "B003", "B004", "B005", "B006"])
    edges += [["B006", block] for block in ["B008", "B007"]]
    edges += cross(["B008", "B007"], ["B010", "B009"])
    annotations.append(
        entry(
            "HR02_opening_HN-SEDECOAS-371604-CW-RFB",
            [f"B{index:03d}" for index in range(13)],
            semantic,
            ["B000", "B001", "B011", "B012"],
            edges,
            confidence="HIGH",
            ambiguity_note=(
                "Name and company fragments inside each table row are read left-to-right "
                "canonically but are not forced relative to one another by the primary DAG."
            ),
        )
    )

    semantic = [
        "B003", "B004", "B005", "B006", "B007", "B008", "B009", "B010",
        "B011", "B012", "B013", "B015", "B014", "B016",
    ]
    edges = chain(["B003", "B004", "B005", "B006", "B007"])
    edges += [["B007", "B008"], ["B007", "B009"]]
    edges += [["B008", "B010"], ["B009", "B010"]]
    edges += chain(["B010", "B011", "B012"])
    edges += [["B012", "B013"], ["B012", "B014"], ["B013", "B015"], ["B014", "B016"]]
    annotations.append(
        entry(
            "HR03_amendment_HN-SEDECOAS-407817-CW-RFB",
            [f"B{index:03d}" for index in range(17)],
            semantic,
            ["B000", "B001", "B002"],
            edges,
            confidence="HIGH",
            ambiguity_note=(
                "The final 'Donde se lee' and 'Debera leerse asi' panels are parallel "
                "columns; the DAG preserves each column internally without forcing one "
                "column before the other."
            ),
        )
    )

    semantic = [
        "B002", "B003", "B004", "B005", "B006", "B007", "B008", "B009",
        "B010", "B012", "B011", "B013",
    ]
    edges = chain(["B002", "B003", "B004", "B005", "B006", "B007", "B008", "B009", "B010"])
    edges += [["B010", "B012"], ["B010", "B011"], ["B012", "B013"], ["B011", "B013"]]
    annotations.append(
        entry(
            "HR04_opening_HN-SEDECOAS-407817-CW-RFB",
            [f"B{index:03d}" for index in range(18)],
            semantic,
            ["B000", "B001", "B014", "B015", "B016", "B017"],
            edges,
            confidence="MEDIUM",
            ambiguity_note=(
                "The final name/company fragments occupy parallel table cells; the DAG "
                "does not force B011 versus B012."
            ),
        )
    )

    headers = ["B005", "B006", "B007", "B008"]
    rows = [
        ["B009", "B010", "B011"],
        ["B012", "B013", "B014"],
        ["B015", "B016", "B017"],
        ["B018", "B019", "B020"],
        ["B022", "B023", "B024"],
        ["B025", "B026", "B027"],
        ["B028", "B029", "B030"],
        ["B031", "B032", "B033"],
    ]
    semantic = ["B000", "B002", "B003", "B004", *headers]
    for row in rows:
        semantic.extend(row)
    semantic.extend(["B034", "B035", "B036", "B037", "B038"])
    edges = chain(["B000", "B002", "B003", "B004"])
    edges += [["B004", block] for block in headers]
    edges += cross(headers, rows[0])
    for current, following in zip(rows, rows[1:]):
        edges += cross(current, following)
    edges += [[block, "B034"] for block in rows[-1]]
    edges += chain(["B034", "B035", "B036", "B037", "B038"])
    annotations.append(
        entry(
            "HR05_tender_LPN-SIT-160-2023",
            [f"B{index:03d}" for index in range(39)],
            semantic,
            ["B001", "B021"],
            edges,
            confidence="HIGH",
            ambiguity_note=(
                "The main table is scored row-by-row. Cells inside the same row are "
                "parallel; every row must precede the following row."
            ),
        )
    )

    semantic = ["B000", "B001", "B002", "B005", "B004"]
    edges = chain(["B000", "B001", "B002"])
    edges += [["B002", "B005"], ["B002", "B004"]]
    annotations.append(
        entry(
            "HR06_contract_LPN-SIT-160-2023",
            [f"B{index:03d}" for index in range(8)],
            semantic,
            ["B003", "B006", "B007"],
            edges,
            confidence="MEDIUM",
            ambiguity_note=(
                "The two signature/name regions are parallel after the signing sentence "
                "and are not ordered relative to one another."
            ),
        )
    )

    semantic = ["B000", "B001", "B002", "B003", "B006", "B007", "B008", "B009", "B010", "B011"]
    annotations.append(
        entry(
            "HR07_tender_LPN-FHIS-33-2025",
            [f"B{index:03d}" for index in range(12)],
            semantic,
            ["B004", "B005"],
            chain(semantic),
            confidence="HIGH",
            ambiguity_note="Single-column notice; vertical website strips are excluded as decorative metadata.",
        )
    )

    semantic = ["B000", "B001", "B002", "B003", "B004", "B005", "B007", "B008"]
    edges = chain(["B000", "B001", "B002", "B003", "B004", "B005"])
    edges += [["B005", "B007"], ["B005", "B008"]]
    annotations.append(
        entry(
            "HR08_opening_LPN-FHIS-33-2025",
            [f"B{index:03d}" for index in range(9)],
            semantic,
            ["B006"],
            edges,
            confidence="MEDIUM",
            ambiguity_note="The two lower signature-label blocks are parallel after the closing paragraph.",
        )
    )

    semantic = [f"B{index:03d}" for index in range(1, 11)]
    annotations.append(
        entry(
            "HR09_clarification_CPN-SIT-054-2023",
            [f"B{index:03d}" for index in range(11)],
            semantic,
            ["B000"],
            chain(semantic),
            confidence="HIGH",
            ambiguity_note="Single-column clarification; the Honduras logo is excluded as branding.",
        )
    )

    semantic = ["B005", "B004", "B003", "B002", "B001"]
    annotations.append(
        entry(
            "HR10_contract_CPN-SIT-054-2023",
            [f"B{index:03d}" for index in range(6)],
            semantic,
            ["B000"],
            chain(semantic),
            confidence="HIGH",
            ambiguity_note=(
                "The source page is rotated. Semantic order follows the page after "
                "clockwise normalization; the page number is excluded."
            ),
        )
    )

    return {
        "schema": SCHEMA,
        "annotation_method": (
            "Agent visual inspection of the exact frozen numbered overlays, including "
            "clockwise normalization of the rotated contract page. Every Tesseract block "
            "is partitioned into semantic or ignored; no block is added, removed, split, "
            "merged, or renamed."
        ),
        "primary_ground_truth": (
            "Partial-order DAG over semantic Tesseract blocks; transitive closure defines "
            "the primary scoring constraints. A canonical total order is retained only as "
            "a secondary tie-break and for exact replay."
        ),
        "blinding": "NOT_BLINDED_TO_BASELINE_GEOMETRY_OR_ROUTER_ORDERS",
        "independence": "NOT_INDEPENDENT_HUMAN_GROUND_TRUTH",
        "preparation_run_id": PREPARATION_RUN_ID,
        "preparation_artifact_id": PREPARATION_ARTIFACT_ID,
        "preparation_artifact_sha256": PREPARATION_ARTIFACT_SHA256,
        "preparation_stable_payload_sha256": PREPARATION_STABLE_PAYLOAD_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "annotations": annotations,
    }


def validate_annotations(payload: dict[str, Any]) -> None:
    seen_documents: set[str] = set()
    for annotation in payload["annotations"]:
        document_id = annotation["document_id"]
        if document_id in seen_documents:
            raise ValueError(f"duplicate document: {document_id}")
        seen_documents.add(document_id)
        available = annotation["available_block_ids"]
        semantic = annotation["semantic_block_ids"]
        ignored = annotation["ignored_block_ids"]
        if len(available) != len(set(available)):
            raise ValueError(f"duplicate available block: {document_id}")
        if set(semantic) & set(ignored):
            raise ValueError(f"semantic/ignored overlap: {document_id}")
        if set(semantic) | set(ignored) != set(available):
            raise ValueError(f"semantic/ignored partition mismatch: {document_id}")
        if annotation["correct_order"] != semantic:
            raise ValueError(f"canonical order drift: {document_id}")
        for left, right in annotation["must_precede"]:
            if left not in semantic or right not in semantic or left == right:
                raise ValueError(f"invalid edge in {document_id}: {left}->{right}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ocr_reading_order_honduras_router_v1/annotations.json"),
    )
    args = parser.parse_args()
    payload = build_annotations()
    validate_annotations(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"documents": len(payload["annotations"]), "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
