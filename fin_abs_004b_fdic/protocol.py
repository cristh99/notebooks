from __future__ import annotations

import pandas as pd

# Version 3 is the final Stage 0 power correction. Version 2 produced
# 34/76/47 positive train/validation/test entities against gates 30/10/50.
# Without changing the seed, dates, rows, labels, or inspecting any model
# output, five surplus validation buckets are transferred to the test. If this
# still misses a gate, the route stops rather than redesigning again.
WINDOWS = {
    "train": (pd.Timestamp("1992-12-31"), pd.Timestamp("2004-12-31")),
    "validation": (pd.Timestamp("2007-03-31"), pd.Timestamp("2009-12-31")),
    "test": (pd.Timestamp("2012-03-31"), pd.Timestamp("2014-12-31")),
}

FETCH_RANGES = (
    (pd.Timestamp("1992-03-31"), pd.Timestamp("2004-12-31")),
    (pd.Timestamp("2006-03-31"), pd.Timestamp("2009-12-31")),
    (pd.Timestamp("2011-03-31"), pd.Timestamp("2014-12-31")),
)

ENTITY_SPLIT_SEED = "FIN-ABS-004B-ENTITY-SPLIT-V2"
TRAIN_BUCKET_END = 30
VALIDATION_BUCKET_END = 45

EXPECTED_BUCKET_RULE = {
    "train": [0, TRAIN_BUCKET_END - 1],
    "validation": [TRAIN_BUCKET_END, VALIDATION_BUCKET_END - 1],
    "test": [VALIDATION_BUCKET_END, 99],
}

ABSOLUTE_SCORE = 423
