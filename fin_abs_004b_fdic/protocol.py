from __future__ import annotations

import pandas as pd

WINDOWS = {
    "train": (pd.Timestamp("1992-12-31"), pd.Timestamp("2004-12-31")),
    "validation": (pd.Timestamp("2007-03-31"), pd.Timestamp("2009-12-31")),
    "test": (pd.Timestamp("2012-03-31"), pd.Timestamp("2013-12-31")),
}

FETCH_RANGES = (
    (pd.Timestamp("1992-03-31"), pd.Timestamp("2004-12-31")),
    (pd.Timestamp("2006-03-31"), pd.Timestamp("2009-12-31")),
    (pd.Timestamp("2011-03-31"), pd.Timestamp("2013-12-31")),
)

ENTITY_SPLIT_SEED = "FIN-ABS-004B-ENTITY-SPLIT-V1"
TRAIN_BUCKET_END = 20
VALIDATION_BUCKET_END = 30

EXPECTED_BUCKET_RULE = {
    "train": [0, TRAIN_BUCKET_END - 1],
    "validation": [TRAIN_BUCKET_END, VALIDATION_BUCKET_END - 1],
    "test": [VALIDATION_BUCKET_END, 99],
}

ABSOLUTE_SCORE = 423
