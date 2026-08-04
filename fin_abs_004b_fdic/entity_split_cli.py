from __future__ import annotations

from fin_abs_004_fdic import entity_split as base

from .protocol import (
    ENTITY_SPLIT_SEED,
    TRAIN_BUCKET_END,
    VALIDATION_BUCKET_END,
)


def main() -> None:
    # Assignment uses CERT and original temporal split only. The larger test
    # bucket was frozen ex ante to preserve power under rare 2012-2013 events.
    base.ENTITY_SPLIT_SEED = ENTITY_SPLIT_SEED
    base.TRAIN_BUCKET_END = TRAIN_BUCKET_END
    base.VALIDATION_BUCKET_END = VALIDATION_BUCKET_END
    base.main()


if __name__ == "__main__":
    main()
