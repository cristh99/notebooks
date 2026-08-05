from __future__ import annotations

import math
import unittest

from .adaptive_route_v4 import (
    CacheReceipt,
    CacheRecipe,
    FastPixelEvidence,
    NativeWord,
    PairedLatency,
    RouteProfile,
    canonical_cache_key,
    evaluate_measured_speed_gate,
    maximum_tesseract_fraction,
    project_route_budget,
    required_fast_path_speedup,
    route_page,
    validate_native_text,
)

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


def valid_words() -> list[NativeWord]:
    texts = [
        "SECRETARIA DE FINANZAS",
        "ORDEN DE COMPRA 2026-0041",
        "Proveedor Ejemplo S.A.",
        "Total L 125,430.00",
        "Fecha 05/08/2026",
        "Documento público verificable",
    ]
    return [
        NativeWord(text=text, bbox=(20, 20 + index * 25, 300, 38 + index * 25))
        for index, text in enumerate(texts)
    ]


class AdaptiveRouteV4Tests(unittest.TestCase):
    def test_valid_native_text_passes(self) -> None:
        result = validate_native_text(valid_words(), page_width=612, page_height=792)
        self.assertTrue(result.passed)
        self.assertEqual(result.reason_codes, ())

    def test_repeated_invisible_like_text_fails_closed(self) -> None:
        rows = [
            NativeWord(text="x x x x x x", bbox=(10, 10, 100, 20))
            for _ in range(20)
        ]
        result = validate_native_text(rows, page_width=612, page_height=792)
        self.assertFalse(result.passed)
        self.assertIn("DOMINANT_TOKEN_REPEAT", result.reason_codes)
        self.assertIn("DUPLICATE_BOXES", result.reason_codes)

    def test_out_of_page_boxes_reject_native_route(self) -> None:
        rows = valid_words()
        rows[-1] = NativeWord(text=rows[-1].text, bbox=(600, 700, 900, 730))
        result = validate_native_text(rows, page_width=612, page_height=792)
        self.assertFalse(result.passed)
        self.assertIn("OUT_OF_PAGE_BOXES", result.reason_codes)

    def test_cache_key_is_deterministic_and_recipe_sensitive(self) -> None:
        recipe = CacheRecipe(
            page_pixels_sha256=H0,
            width=1200,
            height=1600,
            mode="RGB",
            engine_sha256=H1,
            model_sha256=(H2,),
            language="spa",
            oem=1,
            psm=6,
            dpi=300,
            preprocessing_sha256=H3,
            formats=("tsv", "txt"),
        )
        self.assertEqual(canonical_cache_key(recipe), canonical_cache_key(recipe))
        changed = CacheRecipe(
            page_pixels_sha256=H0,
            width=1200,
            height=1600,
            mode="RGB",
            engine_sha256=H1,
            model_sha256=(H2,),
            language="spa",
            oem=1,
            psm=3,
            dpi=300,
            preprocessing_sha256=H3,
            formats=("txt", "tsv"),
        )
        self.assertNotEqual(canonical_cache_key(recipe), canonical_cache_key(changed))

    def test_route_order_prefers_native_then_exact_cache_then_fast_pixel(self) -> None:
        native = validate_native_text(valid_words(), page_width=612, page_height=792)
        key = H0
        cache = CacheReceipt(
            key_sha256=key,
            object_sha256=H1,
            output_sha256=H2,
            verified=True,
        )
        fast = FastPixelEvidence(
            output_sha256=H3,
            quality_gate_pass=True,
            coverage_gate_pass=True,
            stable_builds=2,
            runtime_ms=10,
        )
        self.assertEqual(
            route_page(
                native=native,
                expected_cache_key=key,
                cache=cache,
                fast_pixel=fast,
                tesseract_available=True,
            ).route,
            "NATIVE",
        )
        self.assertEqual(
            route_page(
                native=None,
                expected_cache_key=key,
                cache=cache,
                fast_pixel=fast,
                tesseract_available=True,
            ).route,
            "EXACT_CACHE",
        )
        self.assertEqual(
            route_page(
                native=None,
                expected_cache_key=key,
                cache=None,
                fast_pixel=fast,
                tesseract_available=True,
            ).route,
            "FAST_PIXEL",
        )

    def test_unverified_or_wrong_cache_key_never_routes_to_cache(self) -> None:
        cache = CacheReceipt(
            key_sha256=H0,
            object_sha256=H1,
            output_sha256=H2,
            verified=False,
        )
        decision = route_page(
            native=None,
            expected_cache_key=H3,
            cache=cache,
            fast_pixel=None,
            tesseract_available=True,
        )
        self.assertEqual(decision.route, "TESSERACT")

    def test_fast_pixel_requires_quality_coverage_and_stability(self) -> None:
        fast = FastPixelEvidence(
            output_sha256=H3,
            quality_gate_pass=True,
            coverage_gate_pass=False,
            stable_builds=2,
            runtime_ms=10,
        )
        decision = route_page(
            native=None,
            expected_cache_key=None,
            cache=None,
            fast_pixel=fast,
            tesseract_available=True,
        )
        self.assertEqual(decision.route, "TESSERACT")

    def test_historical_native_fast_fallback_mix_projects_above_tenfold(self) -> None:
        budget = project_route_budget(
            [
                RouteProfile("NATIVE", 160 / 200, 0.00268),
                RouteProfile("FAST_PIXEL", 29 / 200, 1 / 6.9),
                RouteProfile("TESSERACT", 11 / 200, 1.0),
            ]
        )
        self.assertTrue(budget.pass_projection)
        self.assertGreater(budget.throughput_speedup, 10.0)
        self.assertTrue(budget.projected)

    def test_current_native_tesseract_mix_projects_far_below_tenfold(self) -> None:
        native = 13259 / 27574
        budget = project_route_budget(
            [
                RouteProfile("NATIVE", native, 0.00268),
                RouteProfile("TESSERACT", 1.0 - native, 1.0),
            ]
        )
        self.assertFalse(budget.pass_projection)
        self.assertLess(budget.throughput_speedup, 2.0)

    def test_current_mix_needs_about_fivefold_fast_path_without_fallback(self) -> None:
        native = 13259 / 27574
        required = required_fast_path_speedup(
            fast_fraction=1.0 - native,
            fixed_profiles=[RouteProfile("NATIVE", native, 0.00268)],
        )
        self.assertGreater(required, 5.2)
        self.assertLess(required, 5.4)

    def test_sevenfold_fast_path_allows_only_about_three_percent_tesseract(self) -> None:
        native = 13259 / 27574
        maximum = maximum_tesseract_fraction(
            native_fraction=native,
            cache_fraction=0.0,
            native_relative_latency=0.00268,
            cache_relative_latency=1 / 15.2,
            fast_speedup=7.2,
        )
        self.assertGreater(maximum, 0.030)
        self.assertLess(maximum, 0.032)

    def test_measured_speed_gate_passes_only_with_all_four_speed_legs(self) -> None:
        pairs = [
            PairedLatency(
                page_id=f"page-{index}",
                baseline_ms=1000 + index,
                candidate_ms=70 + (index % 3),
                route="FAST_PIXEL",
            )
            for index in range(40)
        ]
        result = evaluate_measured_speed_gate(pairs, bootstrap_samples=500)
        self.assertTrue(result.pass_gate)
        self.assertGreater(result.bootstrap_lower_95, 10.0)

    def test_tail_or_sample_failure_blocks_speed_certificate(self) -> None:
        pairs = [
            PairedLatency(
                page_id=f"page-{index}",
                baseline_ms=1000,
                candidate_ms=70 if index < 9 else 300,
                route="FAST_PIXEL",
            )
            for index in range(10)
        ]
        result = evaluate_measured_speed_gate(
            pairs,
            min_pairs=30,
            bootstrap_samples=500,
        )
        self.assertFalse(result.pass_gate)
        self.assertIn("INSUFFICIENT_PAIRS", result.reason_codes)
        self.assertIn("P95_BELOW_TARGET", result.reason_codes)

    def test_impossible_fixed_latency_returns_infinity(self) -> None:
        required = required_fast_path_speedup(
            fast_fraction=0.1,
            fixed_profiles=[RouteProfile("TESSERACT", 0.9, 1.0)],
        )
        self.assertTrue(math.isinf(required))


if __name__ == "__main__":
    unittest.main()
