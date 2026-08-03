from __future__ import annotations

import copy
from collections import Counter
from typing import Any, Mapping, Sequence

from .constants import PERMUTATION_SEED
from .utils import digest, safe_div


def metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    eligible = [row for row in rows if row["observable"]]
    clean = [row for row in eligible if not row["gold_error"]]
    errors = [row for row in eligible if row["gold_error"]]
    tp = sum(row["decision"] == "ERROR" for row in errors)
    fn = len(errors) - tp
    tn = sum(row["decision"] == "CLEAN" for row in clean)
    fp = sum(row["decision"] == "ERROR" for row in clean)
    abstain_clean = sum(row["decision"] == "ABSTAIN" for row in clean)
    abstain_error = sum(row["decision"] == "ABSTAIN" for row in errors)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    specificity = safe_div(tn, tn + fp)
    fpr = safe_div(fp, fp + tn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    family_total: Counter[str] = Counter()
    family_hit: Counter[str] = Counter()
    for row in errors:
        family = str(row.get("family") or "")
        family_total[family] += 1
        if row["decision"] == "ERROR":
            family_hit[family] += 1
    return {
        "eligible_rows": len(eligible),
        "clean_rows": len(clean),
        "error_rows": len(errors),
        "true_positive": tp,
        "false_negative": fn,
        "true_negative": tn,
        "false_positive": fp,
        "clean_abstentions": abstain_clean,
        "error_abstentions": abstain_error,
        "coverage": safe_div(
            len(eligible) - abstain_clean - abstain_error,
            len(eligible),
        ),
        "accuracy": safe_div(tp + tn, len(eligible)),
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": fpr,
        "f1": f1,
        "family_recall": {
            family: safe_div(family_hit[family], total)
            for family, total in sorted(family_total.items())
        },
    }


def permutation_control(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    eligible = sorted(
        (copy.deepcopy(row) for row in rows if row["observable"]),
        key=lambda row: digest(
            f"{row['instance_id']}|{PERMUTATION_SEED}"
        ),
    )
    decisions = [row["decision"] for row in eligible]
    if decisions:
        decisions = decisions[1:] + decisions[:1]
    permuted = [
        dict(row, decision=decision)
        for row, decision in zip(eligible, decisions, strict=True)
    ]
    return {
        "seed": PERMUTATION_SEED,
        "metrics": metrics(permuted),
    }
