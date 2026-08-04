from __future__ import annotations

from fin_abs_004_fdic import panel as base

from .protocol import FETCH_RANGES, WINDOWS


def main() -> None:
    # The inherited acquisition and feature engine remains unchanged. Only the
    # preregistered temporal windows are rebound before any data are read.
    base.WINDOWS = dict(WINDOWS)
    base.FETCH_RANGES = tuple(FETCH_RANGES)
    base.main()


if __name__ == "__main__":
    main()
