from __future__ import annotations

import unittest

from PIL import Image

from .isolated_crop import isolated_native_word_box, recrop_from_artifact


class IsolatedCropTests(unittest.TestCase):
    def test_fixed_padding_does_not_expand_with_long_number_width(self) -> None:
        box = isolated_native_word_box(
            [100.0, 20.0, 200.0, 30.0],
            (600.0, 800.0),
            (1800, 2400),
        )
        self.assertEqual(box, (297, 54, 603, 96))

    def test_artifact_recrop_is_contained_and_exact(self) -> None:
        image = Image.new("RGB", (140, 60), "white")
        isolated, global_box, relative_box = recrop_from_artifact(
            image,
            [280, 40, 420, 100],
            [100.0, 20.0, 130.0, 30.0],
            (600.0, 800.0),
            (1800, 2400),
        )
        self.assertEqual(global_box, (297, 54, 393, 96))
        self.assertEqual(relative_box, (17, 14, 113, 56))
        self.assertEqual(isolated.size, (96, 42))

    def test_invalid_geometry_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            isolated_native_word_box(
                [10.0, 10.0, 10.0, 20.0],
                (600.0, 800.0),
                (1800, 2400),
            )


if __name__ == "__main__":
    unittest.main()
