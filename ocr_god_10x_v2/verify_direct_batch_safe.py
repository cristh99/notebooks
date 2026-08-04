"""Semantic replay wrapper for the bounded direct-module benchmark."""
from __future__ import annotations

from . import direct_batch as core

SAFE_SPECS: dict[str, tuple[int, int, int]] = {
    "direct_1536_d1_r16": (1536, 1, 16),
    "direct_1024_d1_r16": (1024, 1, 16),
    "direct_768_d1_r16": (768, 1, 16),
    "direct_512_d1_r16": (512, 1, 16),
}

core.SPECS.clear()
core.SPECS.update(SAFE_SPECS)

from .verify_direct_batch import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
