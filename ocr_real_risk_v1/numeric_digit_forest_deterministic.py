"""Deterministic entry point for the frozen digit-forest candidate.

The development implementation remains unchanged for auditability. This entry
point fixes every relevant source of execution parallelism before any model is
constructed, then delegates to the frozen protocol. A candidate is accepted
only after a workflow independently rebuilds it twice and verifies byte-level
identity of the model, report, decisions, and manifest.
"""
from __future__ import annotations

import os

os.environ.setdefault("PYTHONHASHSEED", "0")
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import cv2
import numpy as np

from . import numeric_digit_forest as base

cv2.setNumThreads(1)
np.random.seed(0)
base.MODEL_PARAMETERS["n_jobs"] = 1

MODEL_PARAMETERS = base.MODEL_PARAMETERS
THRESHOLD = base.THRESHOLD
CANDIDATE_SCHEMA = base.CANDIDATE_SCHEMA
FEATURE_SCHEMA = base.FEATURE_SCHEMA
load_frozen_candidate = base.load_frozen_candidate


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
