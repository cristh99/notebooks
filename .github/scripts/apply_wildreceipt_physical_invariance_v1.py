from __future__ import annotations

from pathlib import Path


ADAPTER = Path("ocr_real_risk_v1/wildreceipt_adapter.py")
CANDIDATE = Path(
    "ocr_real_risk_v1/numeric_consensus_candidate_v4_wildreceipt.py"
)
EVALUATOR = Path("ocr_real_risk_v1/wildreceipt_external.py")
ADAPTER_TEST = Path("ocr_real_risk_v1/test_wildreceipt_adapter.py")
CANDIDATE_TEST = Path(
    "ocr_real_risk_v1/test_numeric_consensus_candidate_v4_wildreceipt.py"
)
EVALUATOR_TEST = Path("ocr_real_risk_v1/test_wildreceipt_external.py")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    replace_once(
        ADAPTER,
        '''def selection_rank(
    *,
    shard_id: str,
    key: str,
    image_sha256: str,
    bbox: Sequence[int],
    truth: str,
) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "dataset_revision": DATASET_REVISION,
                "shard_id": shard_id,
                "receipt_key": key,
                "image_sha256": image_sha256,
                "bbox": [int(value) for value in bbox],
                "truth": truth,
            }
        ).encode("utf-8")
    )''',
        '''def selection_rank(
    *,
    image_sha256: str,
    bbox: Sequence[int],
    truth: str,
) -> str:
    """Rank a physical annotation independently of shard or row association."""
    return sha256_bytes(
        canonical_json(
            {
                "dataset_revision": DATASET_REVISION,
                "image_sha256": image_sha256,
                "bbox": [int(value) for value in bbox],
                "truth": truth,
            }
        ).encode("utf-8")
    )''',
        "physical selection rank",
    )
    replace_once(
        ADAPTER,
        '''    key = receipt_key(row, shard_id)
    candidates: dict[tuple[str, tuple[int, int, int, int]], dict[str, Any]] = {}''',
        '''    receipt_key(row, shard_id)
    candidates: dict[tuple[str, tuple[int, int, int, int]], dict[str, Any]] = {}''',
        "receipt identity validation",
    )
    replace_once(
        ADAPTER,
        '''        rank = selection_rank(
            shard_id=shard_id,
            key=key,
            image_sha256=image_sha256,
            bbox=bbox,
            truth=truth,
        )''',
        '''        rank = selection_rank(
            image_sha256=image_sha256,
            bbox=bbox,
            truth=truth,
        )''',
        "physical selection rank call",
    )

    replace_once(
        CANDIDATE,
        'CANDIDATE_SCHEMA = "ocr-numeric-consensus-wildreceipt-candidate/5"\n'
        'CANDIDATE_ID = "numeric-consensus-v4-wildreceipt-schema-v2"\n',
        'CANDIDATE_SCHEMA = "ocr-numeric-consensus-wildreceipt-candidate/6"\n'
        'CANDIDATE_ID = "numeric-consensus-v4-wildreceipt-schema-v3"\n',
        "candidate version",
    )
    replace_once(
        CANDIDATE,
        '''        "protocol_id": (
            "wildreceipt-one-numeric-word-per-receipt-v2-layoutlm-geometry"
        ),''',
        '''        "protocol_id": (
            "wildreceipt-one-numeric-word-per-receipt-v3-physical-invariance"
        ),''',
        "protocol version",
    )
    replace_once(
        CANDIDATE,
        '''            "rank": (
                "SHA-256(dataset revision, shard, receipt id, image SHA-256, "
                "projected pixel bbox, canonical truth)"
            ),
            "deduplicate_candidates_within_receipt": "canonical truth plus bbox",''',
        '''            "rank": (
                "SHA-256(dataset revision, image SHA-256, projected pixel bbox, "
                "canonical truth); invariant to shard and row association"
            ),
            "physical_association_invariant": True,
            "deduplicate_candidates_within_receipt": "canonical truth plus bbox",''',
        "protocol physical rank",
    )
    replace_once(
        CANDIDATE,
        '''        "counterfactual": {
            "one_equal_length_digit_substitution_per_selected_receipt": True,
            "generated_before_candidate_inference": True,
        },''',
        '''        "counterfactual": {
            "one_equal_length_digit_substitution_per_selected_receipt": True,
            "seed": (
                "SHA-256-bound physical evidence key; invariant to shard and "
                "row association"
            ),
            "physical_association_invariant": True,
            "generated_before_candidate_inference": True,
        },''',
        "protocol counterfactual invariance",
    )

    replace_once(
        EVALUATOR,
        '''def build_shard_manifest(
    parquet_path: Path,
    shard_id: str,
    candidate_manifest: Mapping[str, Any],
) -> dict[str, Any]:''',
        '''def physical_counterfactual(truth: str, evidence_key: str) -> str:
    """Create one deterministic substitution for the physical risk unit."""
    return mutate_one_digit(
        truth,
        f"{DATASET_REVISION}:{evidence_key}:counterfactual-v1",
    )


def build_shard_manifest(
    parquet_path: Path,
    shard_id: str,
    candidate_manifest: Mapping[str, Any],
) -> dict[str, Any]:''',
        "physical counterfactual helper",
    )
    replace_once(
        EVALUATOR,
        '''        counterfactual = mutate_one_digit(
            str(selected["truth"]),
            (
                f"{DATASET_REVISION}:{shard_id}:{key}:"
                f"{selected['selection_rank_sha256']}"
            ),
        )''',
        '''        counterfactual = physical_counterfactual(
            str(selected["truth"]), evidence_key
        )''',
        "physical counterfactual call",
    )

    replace_once(
        ADAPTER_TEST,
        '''        self.assertEqual(
            first["selection_rank_sha256"], second["selection_rank_sha256"]
        )
        self.assertEqual(first["bbox_coordinate_space"], "image_pixels")''',
        '''        self.assertEqual(
            first["selection_rank_sha256"], second["selection_rank_sha256"]
        )
        third, _ = select_numeric_annotation(
            row=base,
            shard_id="a-different-shard",
            image_sha256="a" * 64,
            image_size=(100, 100),
        )
        self.assertEqual(first["truth"], third["truth"])
        self.assertEqual(first["bbox"], third["bbox"])
        self.assertEqual(
            first["selection_rank_sha256"], third["selection_rank_sha256"]
        )
        self.assertEqual(first["bbox_coordinate_space"], "image_pixels")''',
        "adapter cross-shard invariance test",
    )

    replace_once(
        CANDIDATE_TEST,
        '''        self.assertEqual(
            protocol["selection"]["deduplicate_receipts_across_shards"],
            "decoded image SHA-256",
        )''',
        '''        self.assertEqual(
            protocol["selection"]["deduplicate_receipts_across_shards"],
            "decoded image SHA-256",
        )
        self.assertTrue(
            protocol["selection"]["physical_association_invariant"]
        )
        self.assertTrue(
            protocol["counterfactual"]["physical_association_invariant"]
        )''',
        "candidate invariance test",
    )

    replace_once(
        EVALUATOR_TEST,
        '''    TARGET_REDUCTION,
    exact_summary,
)''',
        '''    TARGET_REDUCTION,
    exact_summary,
    physical_counterfactual,
)''',
        "external helper import",
    )
    replace_once(
        EVALUATOR_TEST,
        '''    def test_underpowered_denominator_fails_even_with_zero_errors(self) -> None:
''',
        '''    def test_physical_counterfactual_is_association_invariant(self) -> None:
        first = physical_counterfactual("12345", "e" * 64)
        second = physical_counterfactual("12345", "e" * 64)
        other = physical_counterfactual("12345", "f" * 64)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 5)
        self.assertNotEqual(first, "12345")
        self.assertNotEqual(first, other)

    def test_underpowered_denominator_fails_even_with_zero_errors(self) -> None:
''',
        "physical counterfactual test",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
