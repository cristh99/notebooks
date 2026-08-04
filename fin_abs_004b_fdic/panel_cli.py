from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from fin_abs_004_fdic import panel as base

from .protocol import FETCH_RANGES, WINDOWS


def _json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, type(pd.NA))) and bool(missing):
            return None
    except (TypeError, ValueError, OverflowError):
        pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except (TypeError, ValueError):
            pass
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if isinstance(scalar, float) and not math.isfinite(scalar):
            return None
        return _json_safe(scalar)
    return value


def canonical_with_dates(value: Any) -> str:
    """Canonicalize representation only: timestamps to ISO, missing to null."""
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def main() -> None:
    # Acquisition, labels, financial values and rows remain unchanged. Only
    # preregistered windows and deterministic hash serialization are rebound.
    base.WINDOWS = dict(WINDOWS)
    base.FETCH_RANGES = tuple(FETCH_RANGES)
    base.canonical = canonical_with_dates
    base.main()


if __name__ == "__main__":
    main()
