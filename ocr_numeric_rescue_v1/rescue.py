from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

NUMERIC_RE = re.compile(
    r"(?<!\w)[+-]?(?:\d{1,3}(?:[.,\s]\d{3})+|\d+)(?:[.,]\d+)?%?(?!\w)"
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_payload(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("\u00ad", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def numeric_tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).replace(" ", "") for match in NUMERIC_RE.finditer(normalize_text(text)))


def levenshtein(left: Sequence[Any], right: Sequence[Any]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        current = [i]
        for j, b in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (a != b),
                )
            )
        previous = current
    return previous[-1]


def sequence_accuracy(reference: Sequence[str], prediction: Sequence[str]) -> float:
    return 1.0 - levenshtein(reference, prediction) / max(len(reference), len(prediction), 1)


def align_prediction_to_reference(
    reference: Sequence[str], prediction: Sequence[str]
) -> dict[str, Any]:
    """Return one deterministic edit alignment indexed by prediction position.

    Tie-breaking prefers diagonal match/substitution, then reference deletion,
    then prediction insertion. This keeps comparable predicted tokens stable.
    """

    m, n = len(reference), len(prediction)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = min(
                dp[i - 1][j - 1] + (reference[i - 1] != prediction[j - 1]),
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
            )

    assignments: list[dict[str, Any] | None] = [None] * n
    deletions: list[dict[str, Any]] = []
    i, j = m, n
    while i > 0 or j > 0:
        diagonal_cost = None
        if i > 0 and j > 0:
            diagonal_cost = dp[i - 1][j - 1] + (
                reference[i - 1] != prediction[j - 1]
            )
        if diagonal_cost is not None and dp[i][j] == diagonal_cost:
            state = "MATCH" if reference[i - 1] == prediction[j - 1] else "SUBSTITUTION"
            assignments[j - 1] = {
                "prediction_index": j - 1,
                "reference_index": i - 1,
                "state": state,
                "target": reference[i - 1],
            }
            i -= 1
            j -= 1
            continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            deletions.append(
                {
                    "reference_index": i - 1,
                    "target": reference[i - 1],
                    "state": "DELETION",
                }
            )
            i -= 1
            continue
        if j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            assignments[j - 1] = {
                "prediction_index": j - 1,
                "reference_index": None,
                "state": "INSERTION",
                "target": None,
            }
            j -= 1
            continue
        raise AssertionError("alignment backtrace failed")

    if any(item is None for item in assignments):
        raise AssertionError("alignment did not assign every predicted token")
    deletions.reverse()
    return {
        "distance": dp[m][n],
        "assignments": assignments,
        "deletions": deletions,
    }


@dataclass(frozen=True)
class RescuePolicy:
    name: str = "strict_numeric_rescue_v1"
    paddle_confidence_min: float = 0.95
    tesseract_confidence_max: float = 0.80
    require_single_numeric_token: bool = True

    def to_data(self) -> dict[str, Any]:
        return asdict(self)


def classify_candidate(
    candidate: Mapping[str, Any], policy: RescuePolicy
) -> dict[str, Any]:
    baseline = candidate.get("baseline_token")
    alternative = candidate.get("paddle_token")
    t_conf = candidate.get("tesseract_confidence")
    p_conf = candidate.get("paddle_confidence")
    state = candidate.get("alignment_state")
    target = candidate.get("target_token")

    valid = (
        isinstance(baseline, str)
        and isinstance(alternative, str)
        and isinstance(t_conf, (int, float))
        and isinstance(p_conf, (int, float))
    )
    differs = valid and baseline != alternative
    propose = bool(
        valid
        and differs
        and float(p_conf) >= policy.paddle_confidence_min
        and float(t_conf) <= policy.tesseract_confidence_max
    )
    baseline_correct = state == "MATCH"
    baseline_wrong = state in {"SUBSTITUTION", "INSERTION"}
    paddle_correct = target is not None and alternative == target

    if not propose:
        outcome = "NO_CHANGE"
    elif baseline_wrong and paddle_correct:
        outcome = "TRUE_CORRECTION"
    elif baseline_correct and alternative != target:
        outcome = "HARMFUL_CHANGE"
    elif baseline_wrong:
        outcome = "NONCORRECTING_CHANGE"
    else:
        outcome = "UNSCORABLE_CHANGE"

    return {
        "valid_alternative": valid,
        "differs": bool(differs),
        "propose_change": propose,
        "baseline_correct": baseline_correct,
        "baseline_wrong": baseline_wrong,
        "paddle_correct": bool(paddle_correct),
        "outcome": outcome,
    }


def apply_policy(candidates: Iterable[Mapping[str, Any]], policy: RescuePolicy) -> list[dict[str, Any]]:
    result = []
    for candidate in candidates:
        enriched = dict(candidate)
        enriched["decision"] = classify_candidate(enriched, policy)
        result.append(enriched)
    return result


def summarize_candidates(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    comparable = [
        item for item in candidates if item.get("alignment_state") in {"MATCH", "SUBSTITUTION"}
    ]
    substitutions = [item for item in comparable if item.get("alignment_state") == "SUBSTITUTION"]
    matches = [item for item in comparable if item.get("alignment_state") == "MATCH"]
    valid = [item for item in candidates if item.get("decision", {}).get("valid_alternative")]
    raw_rescue = [
        item for item in substitutions if item.get("decision", {}).get("paddle_correct")
    ]
    raw_harm = [
        item
        for item in matches
        if item.get("decision", {}).get("valid_alternative")
        and item.get("paddle_token") != item.get("target_token")
    ]
    proposed = [item for item in candidates if item.get("decision", {}).get("propose_change")]
    outcomes = {
        name: sum(item.get("decision", {}).get("outcome") == name for item in candidates)
        for name in (
            "TRUE_CORRECTION",
            "HARMFUL_CHANGE",
            "NONCORRECTING_CHANGE",
            "UNSCORABLE_CHANGE",
        )
    }
    flagged_errors = sum(
        item.get("decision", {}).get("valid_alternative")
        and item.get("decision", {}).get("differs")
        for item in substitutions
    )
    flagged_correct = sum(
        item.get("decision", {}).get("valid_alternative")
        and item.get("decision", {}).get("differs")
        for item in matches
    )
    flag_precision = flagged_errors / max(flagged_errors + flagged_correct, 1)
    flag_recall = flagged_errors / max(len(substitutions), 1)
    correction_precision = outcomes["TRUE_CORRECTION"] / max(len(proposed), 1)
    return {
        "candidates": len(candidates),
        "comparable_tokens": len(comparable),
        "baseline_matches": len(matches),
        "baseline_substitutions": len(substitutions),
        "baseline_insertions": sum(item.get("alignment_state") == "INSERTION" for item in candidates),
        "valid_small_model_alternatives": len(valid),
        "raw_rescue_opportunities": len(raw_rescue),
        "raw_harm_opportunities": len(raw_harm),
        "disagreement_flagged_errors": flagged_errors,
        "disagreement_flagged_correct": flagged_correct,
        "disagreement_precision": flag_precision,
        "disagreement_recall_on_substitutions": flag_recall,
        "strict_proposed_changes": len(proposed),
        "strict_true_corrections": outcomes["TRUE_CORRECTION"],
        "strict_harmful_changes": outcomes["HARMFUL_CHANGE"],
        "strict_noncorrecting_changes": outcomes["NONCORRECTING_CHANGE"],
        "strict_unscorable_changes": outcomes["UNSCORABLE_CHANGE"],
        "strict_correction_precision": correction_precision,
    }
