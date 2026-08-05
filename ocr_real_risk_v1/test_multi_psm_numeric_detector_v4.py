from __future__ import annotations

import unittest

from .multi_psm_numeric_detector_v4 import (
    DetectorPolicy,
    TokenObservation,
    fuse_multi_psm_tokens,
)


def token(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    psm: int,
    source: str,
    confidence: float = 90.0,
) -> TokenObservation:
    return TokenObservation(
        text=text,
        bbox=bbox,
        confidence=confidence,
        psm=psm,
        source_id=source,
    )


class MultiPsmNumericDetectorV4Tests(unittest.TestCase):
    def test_fuses_jittered_boxes_from_multiple_psms(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("L 1,234.50", (100, 20, 180, 42), psm=3, source="p3-a"),
                token("1,234.50", (102, 19, 181, 43), psm=6, source="p6-a"),
                token("1234.50", (101, 21, 179, 42), psm=11, source="p11-a"),
            ]
        )
        self.assertEqual(result.status, "OK")
        self.assertEqual(len(result.accepted), 1)
        candidate = result.accepted[0]
        self.assertEqual(candidate.digits, "123450")
        self.assertEqual(candidate.psm_support, 3)
        self.assertEqual(candidate.status, "CONSENSUS")

    def test_emits_when_one_psm_misses_but_two_independent_psms_agree(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("6400", (10, 10, 60, 30), psm=3, source="p3"),
                token("6,400", (11, 9, 61, 31), psm=11, source="p11"),
            ]
        )
        self.assertEqual([row.digits for row in result.accepted], ["6400"])
        self.assertEqual(result.accepted[0].psm_support, 2)

    def test_conflicting_six_and_eight_is_ambiguous(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("6,400", (10, 10, 60, 30), psm=3, source="p3"),
                token("8,400", (11, 9, 61, 31), psm=6, source="p6"),
                token("6400", (9, 10, 59, 30), psm=11, source="p11"),
            ]
        )
        self.assertEqual(result.accepted, ())
        self.assertEqual(len(result.ambiguous), 1)
        self.assertEqual(result.ambiguous[0].status, "AMBIGUOUS_CONFLICT")
        self.assertEqual(result.ambiguous[0].alternatives, ("6400", "8400"))

    def test_punctuation_induced_extra_digit_is_ambiguous(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("100,000", (10, 10, 70, 30), psm=3, source="p3"),
                token("101,000", (10, 9, 71, 31), psm=6, source="p6"),
                token("100000", (11, 10, 69, 30), psm=11, source="p11"),
            ]
        )
        self.assertEqual(result.accepted, ())
        self.assertEqual(result.ambiguous[0].alternatives, ("100000", "101000"))

    def test_nearby_totals_are_not_merged(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("1234", (10, 10, 55, 30), psm=3, source="a3"),
                token("1234", (11, 9, 56, 31), psm=6, source="a6"),
                token("5678", (65, 10, 110, 30), psm=3, source="b3"),
                token("5678", (66, 9, 111, 31), psm=6, source="b6"),
            ]
        )
        self.assertEqual([row.digits for row in result.accepted], ["1234", "5678"])
        self.assertEqual(result.ambiguous, ())

    def test_input_order_does_not_change_result_or_receipt(self) -> None:
        rows = [
            token("1234", (10, 10, 55, 30), psm=3, source="p3"),
            token("1,234", (11, 9, 56, 31), psm=6, source="p6"),
            token("1234", (9, 11, 54, 30), psm=11, source="p11"),
        ]
        forward = fuse_multi_psm_tokens(rows)
        reverse = fuse_multi_psm_tokens(reversed(rows))
        self.assertEqual(forward, reverse)
        self.assertEqual(forward.result_sha256, reverse.result_sha256)

    def test_duplicate_source_ids_fail_closed(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("1234", (10, 10, 55, 30), psm=3, source="duplicate"),
                token("1234", (11, 9, 56, 31), psm=6, source="duplicate"),
            ]
        )
        self.assertEqual(result.status, "DUPLICATE_SOURCE_ID")
        self.assertEqual(result.accepted, ())
        self.assertEqual(result.clusters, ())

    def test_non_ascii_digits_are_outside_protocol(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("١٢٣٤", (10, 10, 55, 30), psm=3, source="p3"),
                token("١٢٣٤", (11, 9, 56, 31), psm=6, source="p6"),
            ]
        )
        self.assertEqual(result.accepted, ())
        self.assertEqual(result.filtered_non_numeric, 2)

    def test_same_psm_duplicates_do_not_create_independent_support(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("1234", (10, 10, 55, 30), psm=3, source="p3-a"),
                token("1234", (11, 9, 56, 31), psm=3, source="p3-b"),
            ]
        )
        self.assertEqual(result.accepted, ())
        self.assertEqual(len(result.insufficient), 1)
        self.assertEqual(result.insufficient[0].psm_support, 1)

    def test_complete_link_clustering_blocks_transitive_bridge_merges(self) -> None:
        result = fuse_multi_psm_tokens(
            [
                token("1234", (0, 0, 40, 20), psm=3, source="left"),
                token("1234", (25, 0, 65, 20), psm=6, source="bridge"),
                token("1234", (50, 0, 90, 20), psm=11, source="right"),
            ],
            policy=DetectorPolicy(min_iou=0.20, min_smaller_coverage=0.30),
        )
        self.assertEqual(len(result.clusters), 2)
        self.assertNotEqual(result.clusters[0].cluster_sha256, result.clusters[1].cluster_sha256)

    def test_observation_limit_fails_closed(self) -> None:
        policy = DetectorPolicy(max_observations=2)
        result = fuse_multi_psm_tokens(
            [
                token("1234", (0, 0, 20, 10), psm=3, source="a"),
                token("1234", (0, 0, 20, 10), psm=6, source="b"),
                token("1234", (0, 0, 20, 10), psm=11, source="c"),
            ],
            policy=policy,
        )
        self.assertEqual(result.status, "RESOURCE_LIMIT")
        self.assertEqual(result.accepted, ())


if __name__ == "__main__":
    unittest.main()
