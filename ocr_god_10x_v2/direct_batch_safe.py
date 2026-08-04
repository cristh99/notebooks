"""Stable bounded wrapper for the direct-module OCR benchmark.

The first public run proved that recognition batch 256 can crash the native
OpenVINO/UltraInfer stack with SIGSEGV. This wrapper freezes the minimum stable
hypothesis without changing pages, models, thread budget, quality metrics, or
gates: sequential detection and recognition batches of 16.
"""
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


def main() -> int:
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
