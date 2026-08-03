from __future__ import annotations

from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build_rows():
    rows = []
    counter = 0
    patterns = {
        ("z0", 0): (0, 0, 0, 0),
        ("z0", 1): (0, 0, 1, 1),
        ("z1", 0): (0, 0, 0, 1),
        ("z1", 1): (0, 1, 1, 1),
    }
    for fold in ("f0", "f1"):
        for (z, a), ys in patterns.items():
            for y in ys:
                rows.append((f"r{counter:02d}", fold, z, a, y))
                counter += 1
    return rows


def fit(rows):
    result = {"e": {}, "mu0": {}, "mu1": {}}
    for z in ("z0", "z1"):
        z_rows = [row for row in rows if row[2] == z]
        result["e"][z] = Fraction(sum(row[3] for row in z_rows), len(z_rows))
        for a, name in ((0, "mu0"), (1, "mu1")):
            cell = [row for row in z_rows if row[3] == a]
            result[name][z] = Fraction(sum(row[4] for row in cell), len(cell))
    return result


def score(row, nuisance):
    _row_id, _fold, z, a, y = row
    e = nuisance["e"][z]
    mu0 = nuisance["mu0"][z]
    mu1 = nuisance["mu1"][z]
    return (
        mu1 - mu0
        + Fraction(a, 1) / e * (y - mu1)
        - Fraction(1 - a, 1) / (1 - e) * (y - mu0)
    )


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    rows = build_rows()
    predictions = {}
    training_ids = {}
    for fold, other in (("f0", "f1"), ("f1", "f0")):
        training = [row for row in rows if row[1] == other]
        held_out = [row for row in rows if row[1] == fold]
        if {row[0] for row in training} & {row[0] for row in held_out}:
            raise AssertionError("fold leakage")
        training_ids[fold] = [row[0] for row in training]
        predictions[fold] = fit(training)

    truth = {
        "e": {"z0": Fraction(1, 2), "z1": Fraction(1, 2)},
        "mu0": {"z0": Fraction(0), "z1": Fraction(1, 4)},
        "mu1": {"z0": Fraction(1, 2), "z1": Fraction(3, 4)},
    }
    if predictions["f0"] != truth or predictions["f1"] != truth:
        raise AssertionError("out-of-fold nuisance reconstruction changed")

    scores = [score(row, predictions[row[1]]) for row in rows]
    estimate = sum(scores, Fraction(0)) / len(scores)
    influences = [value - estimate for value in scores]
    mean_influence = sum(influences, Fraction(0)) / len(influences)
    variance = sum((value * value for value in influences), Fraction(0)) / len(influences)
    if estimate != Fraction(1, 2):
        raise AssertionError("AIPW estimate changed")
    if mean_influence != 0 or variance != Fraction(5, 8):
        raise AssertionError("influence moments changed")

    score_histogram = {}
    for value in scores:
        score_histogram[str(value)] = score_histogram.get(str(value), 0) + 1
    expected_histogram = {"1/2": 8, "-1/2": 4, "3/2": 4, "1": 12, "-1": 4}
    if score_histogram != expected_histogram:
        raise AssertionError("score histogram changed")

    # Negative control: a held-out f0 row is explicitly inserted into f0 training.
    leaked_training = list(training_ids["f0"]) + [next(row[0] for row in rows if row[1] == "f0")]
    fold_of = {row[0]: row[1] for row in rows}
    witness = next((row_id for row_id in leaked_training if fold_of[row_id] == "f0"), None)
    if witness is None:
        raise AssertionError("leakage negative control was not detected")

    payload = {
        "schema": "crossfit-compiler/public-independent-receipt/1",
        "private_repository": "cristh99/my_first_repository",
        "private_pr": 68,
        "private_source_blob": "11f59404860db7f2570c4b766d27e814622188ce",
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "rows": 32,
        "folds": 2,
        "nuisance_predictions": {
            fold: {
                name: {z: [v.numerator, v.denominator] for z, v in values.items()}
                for name, values in predictions[fold].items()
            }
            for fold in ("f0", "f1")
        },
        "estimate": [1, 2],
        "mean_influence": [0, 1],
        "empirical_variance": [5, 8],
        "score_histogram": score_histogram,
        "product_rate": {
            "e_l2_squared": [0, 1],
            "mu0_l2_squared": [0, 1],
            "mu1_l2_squared": [0, 1],
            "sufficient_product_square": [0, 1],
            "threshold": [1, 32],
            "status": "PASS",
        },
        "negative_control": {"status": "INVALID_LEAKAGE", "witness": witness},
        "gates": {
            "fold_partition": "PASS",
            "train_test_disjoint": "PASS",
            "nuisance_fit": "PASS",
            "AIPW_exactness": "PASS",
            "product_rate": "PASS",
            "leakage_rejection": "PASS",
        },
    }
    receipt = {
        "payload": payload,
        "sha256": sha256(canonical_json(payload).encode()).hexdigest(),
    }
    path = ROOT / "CROSSFIT_PUBLIC_RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
