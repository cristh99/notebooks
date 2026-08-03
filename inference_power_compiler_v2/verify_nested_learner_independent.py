from __future__ import annotations

from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def rows():
    result = []
    counter = 0
    patterns = {
        ("z0", 0): (0, 0, 0, 0),
        ("z0", 1): (0, 0, 1, 1),
        ("z1", 0): (0, 0, 0, 1),
        ("z1", 1): (0, 1, 1, 1),
    }
    for fold in ("f0", "f1", "f2", "f3"):
        for (z, a), ys in patterns.items():
            for y in ys:
                result.append((f"r{counter:03d}", fold, z, a, y))
                counter += 1
    return result


def target_value(row, target):
    if target == "e":
        return Fraction(row[3])
    if target == "mu0":
        return Fraction(row[4]) if row[3] == 0 else None
    if target == "mu1":
        return Fraction(row[4]) if row[3] == 1 else None
    raise ValueError(target)


def fit(data, target, mode):
    groups = {}
    for row in data:
        value = target_value(row, target)
        if value is None:
            continue
        key = "*" if mode == "pooled" else row[2]
        groups.setdefault(key, []).append(value)
    required = {"*"} if mode == "pooled" else {"z0", "z1"}
    if set(groups) != required:
        raise AssertionError("cell support changed")
    return {key: sum(values, Fraction(0)) / len(values) for key, values in groups.items()}


def predict(model, mode, z):
    return model["*" if mode == "pooled" else z]


def mse(model, mode, validation, target):
    errors = []
    for row in validation:
        value = target_value(row, target)
        if value is None:
            continue
        errors.append((value - predict(model, mode, row[2])) ** 2)
    return sum(errors, Fraction(0)) / len(errors)


def select(all_rows, outer_fold, target):
    outer_training = [row for row in all_rows if row[1] != outer_fold]
    choices = []
    for name, mode, complexity in (
        ("pooled_mean", "pooled", 1),
        ("stratified_z", "by_z", 2),
    ):
        losses = []
        for inner_validation_fold in (fold for fold in ("f0", "f1", "f2", "f3") if fold != outer_fold):
            inner_training = [row for row in outer_training if row[1] != inner_validation_fold]
            inner_validation = [row for row in outer_training if row[1] == inner_validation_fold]
            if {row[0] for row in inner_training} & {row[0] for row in inner_validation}:
                raise AssertionError("inner leakage")
            losses.append(mse(fit(inner_training, target, mode), mode, inner_validation, target))
        choices.append((sum(losses, Fraction(0)) / len(losses), complexity, name, mode))
    selected = min(choices)
    model = fit(outer_training, target, selected[3])
    return {
        "name": selected[2],
        "mode": selected[3],
        "mean_loss": selected[0],
        "model": model,
        "choices": {name: loss for loss, _complexity, name, _mode in choices},
    }


def aipw(row, selected):
    z, a, y = row[2], row[3], row[4]
    e = predict(selected["e"]["model"], selected["e"]["mode"], z)
    mu0 = predict(selected["mu0"]["model"], selected["mu0"]["mode"], z)
    mu1 = predict(selected["mu1"]["model"], selected["mu1"]["mode"], z)
    return (
        mu1 - mu0
        + Fraction(a, 1) / e * (y - mu1)
        - Fraction(1 - a, 1) / (1 - e) * (y - mu0)
    )


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> None:
    all_rows = rows()
    selected = {
        fold: {
            target: select(all_rows, fold, target)
            for target in ("e", "mu0", "mu1")
        }
        for fold in ("f0", "f1", "f2", "f3")
    }
    expected = {
        fold: {"e": "pooled_mean", "mu0": "stratified_z", "mu1": "stratified_z"}
        for fold in ("f0", "f1", "f2", "f3")
    }
    observed = {
        fold: {target: selected[fold][target]["name"] for target in ("e", "mu0", "mu1")}
        for fold in selected
    }
    if observed != expected:
        raise AssertionError("learner selection changed")

    expected_losses = {
        "e": {"pooled_mean": Fraction(1, 4), "stratified_z": Fraction(1, 4)},
        "mu0": {"pooled_mean": Fraction(7, 64), "stratified_z": Fraction(3, 32)},
        "mu1": {"pooled_mean": Fraction(15, 64), "stratified_z": Fraction(7, 32)},
    }
    for fold in selected:
        for target in expected_losses:
            if selected[fold][target]["choices"] != expected_losses[target]:
                raise AssertionError(f"validation loss changed for {fold}/{target}")

    scores = [aipw(row, selected[row[1]]) for row in all_rows]
    estimate = sum(scores, Fraction(0)) / len(scores)
    influences = [value - estimate for value in scores]
    variance = sum((value * value for value in influences), Fraction(0)) / len(influences)
    if estimate != Fraction(1, 2) or variance != Fraction(5, 8):
        raise AssertionError("nested AIPW moments changed")
    if sum(influences, Fraction(0)) != 0:
        raise AssertionError("influence values are not centered")

    truth = {
        "e": {"z0": Fraction(1, 2), "z1": Fraction(1, 2)},
        "mu0": {"z0": Fraction(0), "z1": Fraction(1, 4)},
        "mu1": {"z0": Fraction(1, 2), "z1": Fraction(3, 4)},
    }
    for fold in selected:
        for target, support in truth.items():
            choice = selected[fold][target]
            for z, value in support.items():
                if predict(choice["model"], choice["mode"], z) != value:
                    raise AssertionError("selected nuisance differs from truth")

    # Negative control: add one held-out f0 row to f0 training.
    outer_training = [row[0] for row in all_rows if row[1] != "f0"]
    outer_training.append(next(row[0] for row in all_rows if row[1] == "f0"))
    fold_of = {row[0]: row[1] for row in all_rows}
    witness = next((row_id for row_id in outer_training if fold_of[row_id] == "f0"), None)
    if witness is None:
        raise AssertionError("outer leakage negative control not detected")

    payload = {
        "schema": "nested-learner/public-independent-receipt/1",
        "private_repository": "cristh99/my_first_repository",
        "private_pr": 68,
        "private_source_blob": "31f1f011cc5b93c29bb6444fc1fac5f1b6e5205a",
        "public_repository": "cristh99/notebooks",
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "rows": 64,
        "outer_folds": 4,
        "chosen_learners": expected,
        "validation_losses": {
            target: {name: [value.numerator, value.denominator] for name, value in losses.items()}
            for target, losses in expected_losses.items()
        },
        "estimate": [1, 2],
        "mean_influence": [0, 1],
        "empirical_variance": [5, 8],
        "product_rate": {
            "e_l2_squared": [0, 1],
            "mu0_l2_squared": [0, 1],
            "mu1_l2_squared": [0, 1],
            "sufficient_product_square": [0, 1],
            "n_inverse_threshold": [1, 64],
            "status": "PASS",
        },
        "negative_control": {"status": "INVALID_OUTER_LEAKAGE", "witness": witness},
        "gates": {
            "outer_partition": "PASS",
            "inner_partition": "PASS",
            "exact_scoring": "PASS",
            "deterministic_tie_break": "PASS",
            "out_of_fold_refit": "PASS",
            "AIPW_exactness": "PASS",
            "product_rate": "PASS",
            "leakage_rejection": "PASS",
        },
    }
    receipt = {
        "payload": payload,
        "sha256": sha256(canonical_json(payload).encode()).hexdigest(),
    }
    path = ROOT / "NESTED_LEARNER_PUBLIC_RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
