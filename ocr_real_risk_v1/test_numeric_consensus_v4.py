from __future__ import annotations

import unittest

from .numeric_consensus_v4 import (
    Observation,
    ReplacementPolicy,
    decide_replacement,
    format_like_baseline,
    speed_gate,
)


def obs(
    text: str,
    *,
    source: str,
    crop: str,
    modality: str,
    psm: int | None = None,
    confidence: float = 0.95,
) -> Observation:
    return Observation(
        text=text,
        source_id=source,
        crop_family=crop,
        modality=modality,
        psm=psm,
        confidence=confidence,
    )


class NumericConsensusV4Tests(unittest.TestCase):
    def test_format_preserves_currency_grouping_and_decimal_punctuation(self) -> None:
        self.assertEqual(format_like_baseline("$ 1,234.50", "123850"), "$ 1,238.50")
        self.assertEqual(format_like_baseline("18.00", "1500"), "15.00")

    def test_rejects_candidate_supported_by_only_one_crop_family(self) -> None:
        decision = decide_replacement(
            "18.00",
            [
                obs("15.00", source="pixel-a", crop="tight", modality="pixel"),
                obs("1500", source="ocr-a", crop="tight", modality="ocr", psm=7),
                obs("15.00", source="ocr-b", crop="tight", modality="ocr", psm=13),
            ],
        )
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertEqual(decision.reason, "INSUFFICIENT_INDEPENDENT_CROPS")

    def test_rejects_digit_forest_style_single_modality_false_correction(self) -> None:
        decision = decide_replacement(
            "96802",
            [
                obs("76502", source="pixel-tight", crop="tight", modality="pixel"),
                obs("76502", source="pixel-pad", crop="padded", modality="pixel"),
                obs("76502", source="pixel-wide", crop="wide", modality="pixel"),
            ],
        )
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertEqual(decision.reason, "INSUFFICIENT_MODALITY_DIVERSITY")

    def test_rejects_when_independent_high_confidence_conflict_exists(self) -> None:
        decision = decide_replacement(
            "96802",
            [
                obs("76502", source="pixel-tight", crop="tight", modality="pixel"),
                obs("76502", source="ocr-tight", crop="tight", modality="ocr", psm=7),
                obs("76502", source="ocr-pad", crop="padded", modality="ocr", psm=13),
                obs("96802", source="ocr-wide", crop="wide", modality="ocr", psm=6),
                obs("96802", source="pixel-wide", crop="wide", modality="pixel"),
            ],
        )
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertEqual(decision.reason, "INDEPENDENT_CONFLICT")

    def test_accepts_only_cross_modality_cross_crop_cross_psm_consensus(self) -> None:
        decision = decide_replacement(
            "18.00",
            [
                obs("15.00", source="pixel-tight", crop="tight", modality="pixel"),
                obs("1500", source="ocr-tight", crop="tight", modality="ocr", psm=7),
                obs("15.00", source="ocr-pad", crop="padded", modality="ocr", psm=13),
                obs("1500", source="pixel-wide", crop="wide", modality="pixel"),
            ],
        )
        self.assertEqual(decision.action, "REPLACE")
        self.assertEqual(decision.output, "15.00")
        self.assertEqual(decision.support.votes, 4)
        self.assertEqual(decision.support.crop_families, 3)
        self.assertEqual(decision.support.modalities, 2)
        self.assertEqual(decision.support.psms, 2)

    def test_duplicate_source_ids_are_fail_closed(self) -> None:
        decision = decide_replacement(
            "1234",
            [
                obs("1284", source="same", crop="tight", modality="ocr", psm=7),
                obs("1284", source="same", crop="padded", modality="ocr", psm=13),
                obs("1284", source="pixel", crop="wide", modality="pixel"),
            ],
        )
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertEqual(decision.reason, "DUPLICATE_SOURCE_ID")

    def test_length_change_is_outside_safe_substitution_scope(self) -> None:
        decision = decide_replacement(
            "1234",
            [
                obs("12345", source="ocr-a", crop="tight", modality="ocr", psm=7),
                obs("12345", source="ocr-b", crop="padded", modality="ocr", psm=13),
                obs("12345", source="pixel", crop="wide", modality="pixel"),
            ],
        )
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertEqual(decision.reason, "NO_ELIGIBLE_ALTERNATIVE")

    def test_policy_can_raise_the_evidence_bar(self) -> None:
        policy = ReplacementPolicy(min_votes=5)
        decision = decide_replacement(
            "1234",
            [
                obs("1284", source="p1", crop="tight", modality="pixel"),
                obs("1284", source="o1", crop="tight", modality="ocr", psm=7),
                obs("1284", source="o2", crop="padded", modality="ocr", psm=13),
                obs("1284", source="p2", crop="wide", modality="pixel"),
            ],
            policy=policy,
        )
        self.assertEqual(decision.action, "ABSTAIN")
        self.assertEqual(decision.reason, "INSUFFICIENT_VOTES")

    def test_speed_gate_requires_tenfold_median_and_tail_speedup(self) -> None:
        passing = speed_gate(
            tesseract_ms=[700, 800, 900, 1000, 1100],
            candidate_ms=[50, 60, 70, 80, 90],
            required_speedup=10.0,
        )
        self.assertTrue(passing.pass_gate)
        self.assertGreaterEqual(passing.median_speedup, 10.0)
        self.assertGreaterEqual(passing.p95_speedup, 10.0)

        failing = speed_gate(
            tesseract_ms=[700, 800, 900, 1000, 1100],
            candidate_ms=[60, 70, 80, 90, 120],
            required_speedup=10.0,
        )
        self.assertFalse(failing.pass_gate)
        self.assertLess(failing.p95_speedup, 10.0)


if __name__ == "__main__":
    unittest.main()
