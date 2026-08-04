"""CLI wrapper that injects stable exact bounds into the holdout report."""
from __future__ import annotations

from . import evaluate
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper

# ``evaluate.execute`` resolves these names from its module globals at runtime.
# Patching before importing the CLI preserves the existing acquisition and
# evaluation protocol while replacing only the unstable numerical primitive.
evaluate.clopper_pearson_lower = clopper_pearson_lower
evaluate.clopper_pearson_upper = clopper_pearson_upper

from .run_holdout import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
