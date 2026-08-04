from __future__ import annotations

import json
from typing import Any

from fin_abs_004_fdic import panel as base

from .protocol import FETCH_RANGES, WINDOWS


def _json_default(value: object) -> object:
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_with_dates(value: Any) -> str:
    """Canonical JSON that changes representation, never financial values."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )


def main() -> None:
    # The inherited acquisition and feature engine remains unchanged. Only the
    # preregistered temporal windows and deterministic date serialization are
    # rebound before any data are read.
    base.WINDOWS = dict(WINDOWS)
    base.FETCH_RANGES = tuple(FETCH_RANGES)
    base.canonical = canonical_with_dates
    base.main()


if __name__ == "__main__":
    main()
