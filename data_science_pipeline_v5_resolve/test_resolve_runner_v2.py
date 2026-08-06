from __future__ import annotations

import unittest

from resolve_runner_v2 import resolve_entities_with_coexistence


def line(text: str):
    return {
        "text": text,
        "line_id": "doc:page:0001:b1:p1:l1",
        "page_number": 1,
        "block_num": 1,
        "paragraph_num": 1,
        "line_num": 1,
        "word_count": len(text.split()),
        "mean_confidence": 90.0,
        "lineage_parent_sha256": "a" * 64,
    }


class CoexistenceTests(unittest.TestCase):
    def test_cich_and_educredito_are_distinct_coexisting_entities(self):
        entities, mentions, collisions = resolve_entities_with_coexistence([
            line("Colegio de Ingenieros Civiles de Honduras (CICH), Edificio EDUCREDITO")
        ])
        ids = {item["entity_id"] for item in entities}
        self.assertIn("hn:organization:cich", ids)
        self.assertIn("hn:organization:educredito", ids)
        self.assertFalse(collisions)
        self.assertGreaterEqual(len(mentions), 2)

    def test_country_can_coexist_inside_organization_name(self):
        entities, _, collisions = resolve_entities_with_coexistence([
            line("Colegio de Ingenieros Civiles de Honduras (CICH)")
        ])
        ids = {item["entity_id"] for item in entities}
        self.assertIn("hn:organization:cich", ids)
        self.assertIn("hn:country:honduras", ids)
        self.assertFalse(collisions)


if __name__ == "__main__":
    unittest.main()
