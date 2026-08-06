from __future__ import annotations

import json
import unittest

import entity_provider_candidates as lane

SOURCE = "a" * 64
NORMALIZE = "b" * 64
REGISTRY_ROW = "c" * 64
REGISTRY_MANIFEST = "d" * 64


def word(text_raw: str, token: str, n: int, left: int, *, line_no: int = 1):
    line_id = f"sha256:{SOURCE}:page:0001:b1:p1:l{line_no}"
    return {
        "document_id": f"sha256:{SOURCE}",
        "page_id": f"sha256:{SOURCE}:page:0001",
        "word_id": f"{line_id}:w{n}",
        "page_number": 1,
        "block_num": 1,
        "paragraph_num": 1,
        "line_num": line_no,
        "word_num": n,
        "text_raw": text_raw,
        "token_normalized": token,
        "confidence": 95.0,
        "left_px": left,
        "top_px": 100,
        "width_px": max(10, len(text_raw) * 8),
        "height_px": 20,
        "lineage_parent_sha256": "e" * 64,
    }


def registry(*, alias=("acme",), identifier=(), generic=False, entity_id="hn:supplier:acme"):
    return [{
        "entity_id": entity_id,
        "canonical_name": "ACME, S.A.",
        "entity_type": "supplier",
        "registry_record_sha256": REGISTRY_ROW,
        "alias_tokens_normalized": [list(alias)] if alias else [],
        "identifier_tokens_normalized": [list(identifier)] if identifier else [],
        "generic_jurisdiction": generic,
    }]


class LaneETests(unittest.TestCase):
    def extract(self, words, reg=None):
        return lane.extract_candidates(
            words=words,
            registry=reg or registry(),
            source_sha256=SOURCE,
            normalization_manifest_sha256=NORMALIZE,
        )

    def test_exact_alias_with_supplier_role_is_body_supported(self):
        rows = self.extract([
            word("Proveedor", "proveedor", 1, 10),
            word("ACME", "acme", 2, 100),
        ])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["match_kind"], "EXACT_ALIAS")
        self.assertEqual(row["role"], "supplier")
        self.assertTrue(row["body_support"])
        self.assertFalse(row["registry_support"])
        self.assertEqual(row["resolution_hint"], "DOCUMENT_LOCAL_ENTITY_MENTION")
        self.assertFalse(row["canonical_promotion"])

    def test_substring_is_not_a_match(self):
        rows = self.extract([word("ACMEurope", "acmeurope", 1, 10)])
        self.assertEqual(rows, [])

    def test_multitoken_alias_requires_contiguous_exact_tokens(self):
        reg = registry(alias=("servicios", "acme"))
        miss = self.extract([
            word("Servicios", "servicios", 1, 10),
            word("Nacionales", "nacionales", 2, 90),
            word("ACME", "acme", 3, 180),
        ], reg)
        self.assertEqual(miss, [])
        hit = self.extract([
            word("Servicios", "servicios", 1, 10),
            word("ACME", "acme", 2, 90),
        ], reg)
        self.assertEqual(len(hit), 1)

    def test_identifier_requires_body_role_before_registry_support(self):
        reg = registry(alias=(), identifier=("08011999123456",))
        contextual = self.extract([word("0801-1999-123456", "08011999123456", 1, 10)], reg)[0]
        self.assertFalse(contextual["body_support"])
        self.assertFalse(contextual["registry_support"])
        self.assertEqual(contextual["resolution_hint"], "CONTEXTUAL_ORGANIZATION_ONLY")
        supported = self.extract([
            word("Contratista", "contratista", 1, 10),
            word("0801-1999-123456", "08011999123456", 2, 130),
        ], reg)[0]
        self.assertTrue(supported["body_support"])
        self.assertTrue(supported["registry_support"])
        self.assertEqual(supported["resolution_hint"], "EXACT_SOURCE_BOUND_ENTITY")

    def test_generic_jurisdiction_always_abstains(self):
        reg = registry(alias=("honduras",), generic=True, entity_id="hn:country:honduras")
        row = self.extract([
            word("Proveedor", "proveedor", 1, 10),
            word("Honduras", "honduras", 2, 100),
        ], reg)[0]
        self.assertTrue(row["generic_jurisdiction"])
        self.assertFalse(row["body_support"])
        self.assertFalse(row["registry_support"])
        self.assertEqual(row["resolution_hint"], "GENERIC_JURISDICTION_ABSTAIN")

    def test_conflicting_registry_sequence_fails_closed(self):
        reg = registry()
        reg.append({
            "entity_id": "hn:supplier:other",
            "canonical_name": "OTHER",
            "entity_type": "supplier",
            "registry_record_sha256": "f" * 64,
            "alias_tokens_normalized": [["acme"]],
            "identifier_tokens_normalized": [],
        })
        with self.assertRaises(ValueError):
            self.extract([word("ACME", "acme", 1, 10)], reg)

    def test_multiple_role_cues_do_not_create_role_support(self):
        rows = self.extract([
            word("Proveedor", "proveedor", 1, 10),
            word("Comprador", "comprador", 2, 100),
            word("ACME", "acme", 3, 200),
        ])
        self.assertEqual(rows[0]["role"], None)
        self.assertFalse(rows[0]["body_support"])
        self.assertEqual(rows[0]["resolution_hint"], "CONTEXTUAL_ORGANIZATION_ONLY")

    def test_exact_span_word_ids_and_bbox_are_preserved(self):
        rows = self.extract([
            word("Proveedor", "proveedor", 1, 10),
            word("ACME", "acme", 2, 100),
        ])
        row = rows[0]
        self.assertEqual(row["surface_text"], "ACME")
        self.assertEqual(row["span_start"], len("Proveedor "))
        self.assertEqual(row["span_end"], len("Proveedor ACME"))
        self.assertEqual(len(row["word_ids"]), 1)
        self.assertEqual(row["bbox"]["left_px"], 100)

    def test_public_commitment_excludes_raw_name_and_ocr_text(self):
        row = self.extract([
            word("Proveedor", "proveedor", 1, 10),
            word("ACME", "acme", 2, 100),
        ])[0]
        public = lane.candidate_public_commitment(row)
        encoded = lane.canonical_json(public)
        self.assertNotIn("ACME, S.A.", encoded)
        self.assertNotIn("Proveedor", encoded)
        self.assertNotIn("surface_text", encoded)
        self.assertNotIn("candidate_value_display", encoded)
        self.assertFalse(public["canonical_promotion"])

    def test_manifest_is_deterministic_and_declares_zero_leakage(self):
        rows = self.extract([
            word("Proveedor", "proveedor", 1, 10),
            word("ACME", "acme", 2, 100),
        ])
        one = lane.build_manifest(
            candidates=rows,
            source_sha256=SOURCE,
            normalization_manifest_sha256=NORMALIZE,
            registry_manifest_sha256=REGISTRY_MANIFEST,
        )
        two = lane.build_manifest(
            candidates=list(reversed(rows)),
            source_sha256=SOURCE,
            normalization_manifest_sha256=NORMALIZE,
            registry_manifest_sha256=REGISTRY_MANIFEST,
        )
        self.assertEqual(one, two)
        self.assertFalse(one["fuzzy_similarity_used"])
        self.assertFalse(one["substring_matching_used"])
        self.assertFalse(one["ground_truth_labels_used_as_features"])
        self.assertFalse(one["ground_truth_rtn_used_as_feature"])
        self.assertEqual(one["canonical_promotions"], 0)
        self.assertEqual(one["external_cost_usd"], "0.00")

    def test_invalid_normalized_registry_token_fails_closed(self):
        bad = registry(alias=("ACME",))
        with self.assertRaises(ValueError):
            self.extract([word("ACME", "acme", 1, 10)], bad)


if __name__ == "__main__":
    unittest.main()
