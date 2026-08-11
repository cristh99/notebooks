from __future__ import annotations

import unittest

from ocr_sota_real_canary_v2.run_canary import (
    bbox_from_poly,
    parse_paddle_result,
    region_score,
    select_pages,
    text_metrics,
)
from ocr_sota_real_canary_v2.verify_report import aggregate, verify


class FakeResult:
    @property
    def json(self):
        return {"res": {"rec_texts": ["Hello", "123"], "rec_scores": [0.9, 0.8], "rec_polys": [[[0, 0], [40, 0], [40, 10], [0, 10]], [[0, 20], [30, 20], [30, 30], [0, 30]]]}}


class CanaryTests(unittest.TestCase):
    def test_text_metrics(self):
        result = text_metrics("Total 123", "Total 124")
        self.assertFalse(result["numeric_exact"])
        self.assertLess(result["numeric_sequence_accuracy"], 1.0)

    def test_bbox(self):
        self.assertEqual(bbox_from_poly([1, 2, 5, 2, 5, 9, 1, 9]), (1.0, 2.0, 5.0, 9.0))

    def test_region_score(self):
        result = region_score([(0, 0, 100, 100)], [(0, 0, 50, 100), (50, 0, 100, 100)])
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["precision"], 1.0)

    def test_parse_paddle_result(self):
        result = parse_paddle_result([FakeResult()])
        self.assertEqual(result["text"], "Hello\n123")
        self.assertEqual(len(result["lines"]), 2)

    def test_select_pages_deterministic(self):
        raw = []
        for index in range(12):
            raw.append({
                "page_info": {"image_path": f"p{index}.png", "width": 100, "height": 100, "page_attribute": {"language": "en", "data_source": "note" if index == 0 else "book", "layout": "double_column" if index == 1 else "single_column", "fuzzy_scan": index == 2}},
                "layout_dets": [
                    {"category_type": "text_block", "poly": [0, 0, 100, 0, 100, 80, 0, 80], "order": 0, "text": "A" * 140},
                    *([{"category_type": "table", "poly": [0, 80, 100, 80, 100, 100, 0, 100], "order": 1}] if index == 3 else []),
                    *([{"category_type": "equation_isolated", "poly": [0, 80, 100, 80, 100, 100, 0, 100], "order": 1}] if index == 4 else []),
                ],
            })
        first = [page.page_id for page in select_pages(raw, 8)]
        second = [page.page_id for page in select_pages(raw, 8)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)

    def test_verifier_detects_tamper(self):
        row = {"page_id": "p", "engine": "e", "text": {"cer": 0.0, "wer": 0.0, "numeric_sequence_accuracy": 1.0, "numeric_exact": True}, "text_region": {"f1": 1.0, "recall": 1.0}, "latency_seconds": 1.0, "prediction": {"lines": [{"text": "x"}]}}
        agg = aggregate([row])
        base = {"schema": "ocr-sota-real-canary-v2/report/1", "dataset": {"selected_pages": ["p"]}, "input_manifest": [{"page_id": "p"}], "rows": [row], "aggregate": agg, "denominators": {"pages": 1, "engines": 1, "page_engine_pairs": 1}, "constraints": {"external_spend_usd": 0, "gcloud_used": False, "paid_api_used": False, "gpu_used": False}}
        import hashlib, json
        payload = json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        base["stable_payload_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
        self.assertEqual(verify(base), [])
        base["aggregate"]["e"]["word_accuracy"] = 0.5
        self.assertIn("aggregate", verify(base))


if __name__ == "__main__":
    unittest.main()
