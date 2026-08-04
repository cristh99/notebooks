from __future__ import annotations

import types
import unittest

import numpy as np
import pandas as pd

from .serialization import canonical_json, digest_json, install_panel_serialization


class EvidenceSerializationTests(unittest.TestCase):
    def test_timestamp_missing_and_numpy_values_are_canonical(self) -> None:
        value = {
            "date": pd.Timestamp("2009-03-31"),
            "amount": np.float64(125.5),
            "missing_float": np.nan,
            "missing_scalar": pd.NA,
        }
        self.assertEqual(
            canonical_json(value),
            '{"amount":125.5,"date":"2009-03-31T00:00:00","missing_float":null,"missing_scalar":null}',
        )
        self.assertEqual(digest_json(value), digest_json(value))

    def test_infinity_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "infinity"):
            canonical_json({"value": float("inf")})

    def test_patch_is_scoped_to_panel_module(self) -> None:
        module = types.SimpleNamespace(canonical=None, digest=None)
        install_panel_serialization(module)
        payload = [{"date": pd.Timestamp("2011-12-31"), "value": np.nan}]
        self.assertEqual(module.canonical(payload), canonical_json(payload))
        self.assertEqual(module.digest(payload), digest_json(payload))


if __name__ == "__main__":
    unittest.main()
