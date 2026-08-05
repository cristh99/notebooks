"""Train and freeze a learned numeric crop verifier from opened SROIE data.

SROIE is development data. The produced model is a candidate for a different,
untouched external validation set; this module never grants production status.
Inference uses only the OCR-produced crop and the proposed digit claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import cv2
import joblib
import numpy as np
import sklearn
from PIL import Image, ImageOps
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.model_selection import GroupKFold

from .core import canonical_json, sha256_bytes
from .exact_bounds import clopper_pearson_lower, clopper_pearson_upper
from .pixel_digit_alignment import PixelDigitAligner, _ink, _segment
from .sroie_natural_holdout import verify_stable_payload

CANDIDATE_SCHEMA = "ocr-numeric-digit-forest-candidate/3"
REPORT_SCHEMA = "ocr-numeric-digit-forest-development/3"
FEATURE_SCHEMA = "ocr-numeric-digit-patch-feature/1"
MODEL_FILENAME = "digit_forest.joblib"
THRESHOLD = 0.25
ALPHA_PER_LEG = 0.0125
VIEW_NAMES = ("original", "autocontrast2", "clahe2", "otsu2")
MODEL_PARAMETERS: dict[str, Any] = {
    "n_estimators": 500,
    "max_depth": None,
    "min_samples_leaf": 2,
    "max_features": 0.2,
    "class_weight": "balanced",
    "criterion": "gini",
    "bootstrap": False,
    "n_jobs": -1,
}
TRAIN_ONLY_RANDOM_STATE = 777
FINAL_RANDOM_STATE = 20260804
CV_RANDOM_STATES = (100, 101, 102, 103, 104)
EXPECTED_SPLIT_COUNTS = {
    "train": {"selected": 537, "eligible": 355},
    "test": {"selected": 308, "eligible": 216},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hash_manifest(root: Path) -> None:
    path = root / "SHA256SUMS.txt"
    if not path.exists():
        raise RuntimeError(f"missing SHA256SUMS.txt in {root}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        expected, relative = raw.split("  ", 1)
        target = root / relative
        if _sha256(target) != expected:
            raise RuntimeError(f"hash mismatch: {target}")


def deterministic_views(image: Image.Image) -> dict[str, Image.Image]:
    gray = image.convert("L")
    array = np.array(gray)
    doubled_size = (
        max(2, gray.width * 2),
        max(2, gray.height * 2),
    )
    contrast = ImageOps.autocontrast(gray, cutoff=1).resize(
        doubled_size,
        Image.Resampling.LANCZOS,
    )
    clahe_array = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(4, 4),
    ).apply(array)
    clahe = Image.fromarray(clahe_array).resize(
        doubled_size,
        Image.Resampling.LANCZOS,
    )
    _, otsu_array = cv2.threshold(
        array,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    otsu = Image.fromarray(otsu_array).resize(
        doubled_size,
        Image.Resampling.LANCZOS,
    )
    return {
        "original": gray,
        "autocontrast2": contrast,
        "clahe2": clahe,
        "otsu2": otsu,
    }


def digit_patch_feature(patch: np.ndarray) -> np.ndarray:
    return PixelDigitAligner._feature(patch).astype(np.float32, copy=False)


def _new_model(random_state: int) -> ExtraTreesClassifier:
    return ExtraTreesClassifier(
        random_state=random_state,
        **MODEL_PARAMETERS,
    )


def load_receipts(roots: Iterable[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    source: dict[str, Any] = {
        "splits": {},
        "selected_locations": 0,
        "eligible_claims": 0,
    }
    for root in roots:
        _verify_hash_manifest(root)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        report = json.loads((root / "split_report.json").read_text(encoding="utf-8"))
        if not verify_stable_payload(manifest, "manifest_sha256"):
            raise RuntimeError(f"manifest stable payload mismatch: {root}")
        if not verify_stable_payload(report, "stable_payload_sha256"):
            raise RuntimeError(f"report stable payload mismatch: {root}")
        if report["manifest_sha256"] != manifest["manifest_sha256"]:
            raise RuntimeError(f"manifest/report mismatch: {root}")
        split = str(report["dataset"]["split"])
        if split not in EXPECTED_SPLIT_COUNTS:
            raise RuntimeError(f"unexpected split: {split}")
        expected = EXPECTED_SPLIT_COUNTS[split]
        execution = report["execution"]
        if int(execution["selected_locations"]) != expected["selected"]:
            raise RuntimeError(f"unexpected selected count for {split}")
        if int(execution["eligible_claims"]) != expected["eligible"]:
            raise RuntimeError(f"unexpected eligible count for {split}")
        eligible_observations = [
            row
            for row in report["observations"]
            if row["tesseract"]["eligible"]
        ]
        if len(eligible_observations) != expected["eligible"]:
            raise RuntimeError(f"eligible observation mismatch for {split}")
        split_receipts: list[dict[str, Any]] = []
        for row in eligible_observations:
            claim = str(row["tesseract"]["claim"])
            truth = str(row["truth"])
            counterfactual = str(row["counterfactual"]["claim"])
            if not claim.isdigit() or not truth.isdigit() or not counterfactual.isdigit():
                raise RuntimeError("candidate accepts digit-only claims")
            if not (len(claim) == len(truth) == len(counterfactual)):
                raise RuntimeError("candidate requires equal-length claims")
            crop_path = root / str(row["verifier"]["crop_file"])
            if _sha256(crop_path) != str(row["verifier"]["crop_sha256"]):
                raise RuntimeError(f"crop hash mismatch: {crop_path}")
            record = {
                "split": split,
                "key": str(row["key"]),
                "company_group": str(row["company_group"]),
                "evidence_key": str(row["evidence_key"]),
                "claim": claim,
                "truth": truth,
                "counterfactual_claim": counterfactual,
                "claim_correct": bool(row["tesseract"]["claim_correct"]),
                "crop_path": crop_path,
                "crop_sha256": str(row["verifier"]["crop_sha256"]),
            }
            split_receipts.append(record)
        split_receipts.sort(key=lambda row: row["key"])
        receipts.extend(split_receipts)
        source["splits"][split] = {
            "root": str(root),
            "manifest_sha256": manifest["manifest_sha256"],
            "report_stable_payload_sha256": report["stable_payload_sha256"],
            "selected_locations": expected["selected"],
            "eligible_claims": expected["eligible"],
            "eligible_key_set_sha256": sha256_bytes(
                canonical_json([row["key"] for row in split_receipts]).encode("utf-8")
            ),
        }
        source["selected_locations"] += expected["selected"]
        source["eligible_claims"] += expected["eligible"]
    split_names = Counter(row["split"] for row in receipts)
    if split_names != {"train": 355, "test": 216}:
        raise RuntimeError(f"unexpected combined split counts: {dict(split_names)}")
    if len({row["key"] for row in receipts}) != len(receipts):
        raise RuntimeError("receipt keys overlap")
    source["training_receipt_set_sha256"] = sha256_bytes(
        canonical_json(
            [
                {
                    "split": row["split"],
                    "key": row["key"],
                    "company_group": row["company_group"],
                    "crop_sha256": row["crop_sha256"],
                    "truth": row["truth"],
                }
                for row in receipts
            ]
        ).encode("utf-8")
    )
    return receipts, source


def build_patch_matrix(
    receipts: Sequence[Mapping[str, Any]],
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    features: list[np.ndarray] = []
    labels: list[int] = []
    receipt_indices: list[int] = []
    positions: list[int] = []
    views: list[int] = []
    for receipt_index, record in enumerate(receipts):
        with Image.open(record["crop_path"]) as opened:
            view_map = deterministic_views(opened.convert("L"))
        length = len(str(record["claim"]))
        truth = str(record["truth"])
        for view_index, view_name in enumerate(VIEW_NAMES):
            patches, _ = _segment(_ink(view_map[view_name]), length)
            if len(patches) != length:
                raise RuntimeError("digit segmentation count mismatch")
            for position, (patch, truth_digit) in enumerate(
                zip(patches, truth, strict=True)
            ):
                features.append(digit_patch_feature(patch))
                labels.append(int(truth_digit))
                receipt_indices.append(receipt_index)
                positions.append(position)
                views.append(view_index)
    matrix = np.vstack(features).astype(np.float32, copy=False)
    label_array = np.asarray(labels, dtype=np.int8)
    metadata = {
        "receipt_index": np.asarray(receipt_indices, dtype=np.int32),
        "position": np.asarray(positions, dtype=np.int16),
        "view": np.asarray(views, dtype=np.int8),
    }
    if matrix.shape[0] != label_array.shape[0]:
        raise RuntimeError("feature/label count mismatch")
    if matrix.shape[1] != 1564:
        raise RuntimeError(f"unexpected patch feature width: {matrix.shape[1]}")
    if set(np.unique(label_array)) != set(range(10)):
        raise RuntimeError("training data does not cover all ten digits")
    return matrix, label_array, metadata


def predict_patch_probabilities(
    model: ExtraTreesClassifier,
    matrix: np.ndarray,
) -> np.ndarray:
    if list(model.classes_) != list(range(10)):
        raise RuntimeError("model class order is not 0..9")
    probabilities = model.predict_proba(matrix).astype(np.float64, copy=False)
    if probabilities.shape != (matrix.shape[0], 10):
        raise RuntimeError("unexpected probability matrix shape")
    if not np.all(np.isfinite(probabilities)):
        raise RuntimeError("non-finite model probabilities")
    return probabilities


def receipt_decisions(
    receipts: Sequence[Mapping[str, Any]],
    probabilities: np.ndarray,
    metadata: Mapping[str, np.ndarray],
    receipt_subset: Iterable[int],
    *,
    threshold: float = THRESHOLD,
) -> list[dict[str, Any]]:
    by_position: dict[tuple[int, int], list[tuple[int, np.ndarray]]] = defaultdict(list)
    for patch_index, receipt_index in enumerate(metadata["receipt_index"]):
        by_position[(int(receipt_index), int(metadata["position"][patch_index]))].append(
            (int(metadata["view"][patch_index]), probabilities[patch_index])
        )
    decisions: list[dict[str, Any]] = []
    for receipt_index in sorted(set(int(value) for value in receipt_subset)):
        record = receipts[receipt_index]
        claim = str(record["claim"])
        predicted_digits: list[str] = []
        position_payloads: list[dict[str, Any]] = []
        minimum_probability = 1.0
        for position in range(len(claim)):
            rows = sorted(by_position[(receipt_index, position)], key=lambda row: row[0])
            if [row[0] for row in rows] != list(range(len(VIEW_NAMES))):
                raise RuntimeError("receipt position is missing one or more views")
            view_probabilities = np.vstack([row[1] for row in rows])
            mean_probability = view_probabilities.mean(axis=0)
            predicted_digit = str(int(np.argmax(mean_probability)))
            confidence = float(np.max(mean_probability))
            view_predictions = [
                str(int(np.argmax(row))) for row in view_probabilities
            ]
            predicted_digits.append(predicted_digit)
            minimum_probability = min(minimum_probability, confidence)
            position_payloads.append(
                {
                    "position": position,
                    "claim_digit": claim[position],
                    "truth_digit": str(record["truth"])[position],
                    "predicted_digit": predicted_digit,
                    "mean_probability": confidence,
                    "claim_probability": float(mean_probability[int(claim[position])]),
                    "view_predictions": view_predictions,
                    "views_matching_claim": sum(
                        value == claim[position] for value in view_predictions
                    ),
                }
            )
        prediction = "".join(predicted_digits)
        natural_accepted = bool(
            prediction == claim and minimum_probability >= threshold
        )
        counterfactual_accepted = bool(
            prediction == str(record["counterfactual_claim"])
            and minimum_probability >= threshold
        )
        decisions.append(
            {
                "split": record["split"],
                "key": record["key"],
                "company_group": record["company_group"],
                "evidence_key": record["evidence_key"],
                "claim": claim,
                "truth": record["truth"],
                "claim_correct": record["claim_correct"],
                "counterfactual_claim": record["counterfactual_claim"],
                "prediction": prediction,
                "minimum_mean_probability": minimum_probability,
                "threshold": threshold,
                "natural_accepted": natural_accepted,
                "natural_false_accept": bool(
                    natural_accepted and not record["claim_correct"]
                ),
                "counterfactual_accepted": counterfactual_accepted,
                "positions": position_payloads,
            }
        )
    return decisions


def summarize_decisions(
    decisions: Sequence[Mapping[str, Any]],
    *,
    selected_locations: int,
) -> dict[str, Any]:
    accepted = [row for row in decisions if row["natural_accepted"]]
    false_accepted = sum(bool(row["natural_false_accept"]) for row in accepted)
    counterfactual_false = sum(
        bool(row["counterfactual_accepted"]) for row in decisions
    )
    eligible = len(decisions)
    return {
        "selected_locations": selected_locations,
        "eligible_claims": eligible,
        "accepted": len(accepted),
        "accepted_correct": len(accepted) - false_accepted,
        "natural_false_accepts": false_accepted,
        "counterfactual_false_accepts": counterfactual_false,
        "coverage_of_selected": len(accepted) / selected_locations,
        "coverage_of_eligible": len(accepted) / eligible,
        "simultaneous_95pct_selected_coverage_lower": clopper_pearson_lower(
            len(accepted), selected_locations, ALPHA_PER_LEG
        ),
        "simultaneous_95pct_eligible_coverage_lower": clopper_pearson_lower(
            len(accepted), eligible, ALPHA_PER_LEG
        ),
        "simultaneous_95pct_natural_risk_upper": (
            clopper_pearson_upper(
                false_accepted,
                len(accepted),
                ALPHA_PER_LEG,
            )
            if accepted
            else 1.0
        ),
        "simultaneous_95pct_counterfactual_upper": clopper_pearson_upper(
            counterfactual_false,
            eligible,
            ALPHA_PER_LEG,
        ),
        "natural_false_accept_keys": [
            row["key"] for row in accepted if row["natural_false_accept"]
        ],
        "counterfactual_false_accept_keys": [
            row["key"] for row in decisions if row["counterfactual_accepted"]
        ],
    }


def cross_validated_train_predictions(
    receipts: Sequence[Mapping[str, Any]],
    matrix: np.ndarray,
    labels: np.ndarray,
    metadata: Mapping[str, np.ndarray],
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    train_receipts = [
        index for index, row in enumerate(receipts) if row["split"] == "train"
    ]
    groups = np.asarray(
        [str(receipts[index]["company_group"]) for index in train_receipts],
        dtype=object,
    )
    receipt_array = np.asarray(train_receipts, dtype=np.int32)
    probabilities = np.full((matrix.shape[0], 10), np.nan, dtype=np.float64)
    folds: list[dict[str, Any]] = []
    splitter = GroupKFold(n_splits=5)
    for fold_index, (train_rows, validation_rows) in enumerate(
        splitter.split(receipt_array, groups=groups)
    ):
        training_receipt_set = set(int(receipt_array[index]) for index in train_rows)
        validation_receipt_set = set(
            int(receipt_array[index]) for index in validation_rows
        )
        patch_train = np.isin(
            metadata["receipt_index"],
            list(training_receipt_set),
        )
        patch_validation = np.isin(
            metadata["receipt_index"],
            list(validation_receipt_set),
        )
        model = _new_model(CV_RANDOM_STATES[fold_index])
        model.fit(matrix[patch_train], labels[patch_train])
        probabilities[patch_validation] = predict_patch_probabilities(
            model,
            matrix[patch_validation],
        )
        folds.append(
            {
                "fold": fold_index,
                "random_state": CV_RANDOM_STATES[fold_index],
                "training_receipts": int(len(training_receipt_set)),
                "validation_receipts": int(len(validation_receipt_set)),
                "training_companies": int(
                    len(
                        {
                            receipts[index]["company_group"]
                            for index in training_receipt_set
                        }
                    )
                ),
                "validation_companies": int(
                    len(
                        {
                            receipts[index]["company_group"]
                            for index in validation_receipt_set
                        }
                    )
                ),
            }
        )
    train_patch_mask = np.isin(metadata["receipt_index"], train_receipts)
    if not np.all(np.isfinite(probabilities[train_patch_mask])):
        raise RuntimeError("cross-validation left train patches unpredicted")
    return probabilities, folds


def fit_train_only_and_predict_test(
    receipts: Sequence[Mapping[str, Any]],
    matrix: np.ndarray,
    labels: np.ndarray,
    metadata: Mapping[str, np.ndarray],
) -> tuple[ExtraTreesClassifier, np.ndarray]:
    train_receipts = [
        index for index, row in enumerate(receipts) if row["split"] == "train"
    ]
    test_receipts = [
        index for index, row in enumerate(receipts) if row["split"] == "test"
    ]
    train_mask = np.isin(metadata["receipt_index"], train_receipts)
    test_mask = np.isin(metadata["receipt_index"], test_receipts)
    model = _new_model(TRAIN_ONLY_RANDOM_STATE)
    model.fit(matrix[train_mask], labels[train_mask])
    probabilities = np.full((matrix.shape[0], 10), np.nan, dtype=np.float64)
    probabilities[test_mask] = predict_patch_probabilities(
        model,
        matrix[test_mask],
    )
    if not np.all(np.isfinite(probabilities[test_mask])):
        raise RuntimeError("test patches were not predicted")
    return model, probabilities


def development_report(
    receipts: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    matrix: np.ndarray,
    labels: np.ndarray,
    metadata: Mapping[str, np.ndarray],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    train_indices = [
        index for index, row in enumerate(receipts) if row["split"] == "train"
    ]
    test_indices = [
        index for index, row in enumerate(receipts) if row["split"] == "test"
    ]
    oof_probabilities, folds = cross_validated_train_predictions(
        receipts,
        matrix,
        labels,
        metadata,
    )
    train_decisions = receipt_decisions(
        receipts,
        oof_probabilities,
        metadata,
        train_indices,
    )
    _, test_probabilities = fit_train_only_and_predict_test(
        receipts,
        matrix,
        labels,
        metadata,
    )
    test_decisions = receipt_decisions(
        receipts,
        test_probabilities,
        metadata,
        test_indices,
    )
    all_decisions = sorted(
        [*train_decisions, *test_decisions],
        key=lambda row: (row["split"], row["key"]),
    )
    train_summary = summarize_decisions(
        train_decisions,
        selected_locations=EXPECTED_SPLIT_COUNTS["train"]["selected"],
    )
    test_summary = summarize_decisions(
        test_decisions,
        selected_locations=EXPECTED_SPLIT_COUNTS["test"]["selected"],
    )
    combined_summary = summarize_decisions(
        all_decisions,
        selected_locations=int(source["selected_locations"]),
    )
    baseline_false = sum(not bool(row["claim_correct"]) for row in receipts)
    baseline_total = len(receipts)
    baseline_lower = clopper_pearson_lower(
        baseline_false,
        baseline_total,
        ALPHA_PER_LEG,
    )
    retained_upper = combined_summary["simultaneous_95pct_natural_risk_upper"]
    reduction_lower = (
        baseline_lower / retained_upper if retained_upper > 0 else None
    )
    ready = bool(
        train_summary["natural_false_accepts"] == 0
        and train_summary["counterfactual_false_accepts"] == 0
        and test_summary["natural_false_accepts"] == 0
        and test_summary["counterfactual_false_accepts"] == 0
        and combined_summary["accepted"] >= 300
        and combined_summary[
            "simultaneous_95pct_selected_coverage_lower"
        ]
        >= 0.25
        and combined_summary[
            "simultaneous_95pct_counterfactual_upper"
        ]
        <= 0.01
    )
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "POST_OUTCOME_DEVELOPMENT_ONLY",
        "source": source,
        "protocol": {
            "views": list(VIEW_NAMES),
            "feature_schema": FEATURE_SCHEMA,
            "feature_width": int(matrix.shape[1]),
            "training_patch_count": int(matrix.shape[0]),
            "model_class": "sklearn.ensemble.ExtraTreesClassifier",
            "model_parameters": MODEL_PARAMETERS,
            "cross_validation": "5-fold company-disjoint GroupKFold on SROIE train",
            "train_only_random_state": TRAIN_ONLY_RANDOM_STATE,
            "cv_random_states": list(CV_RANDOM_STATES),
            "threshold": THRESHOLD,
            "decision_rule": (
                "accept iff every averaged four-view digit argmax equals the "
                "claim and the minimum position probability is at least 0.25"
            ),
            "truth_available_at_inference": False,
            "sroie_used_for_certification": False,
        },
        "baseline": {
            "eligible_claims": baseline_total,
            "false_predictions": baseline_false,
            "observed_error_rate": baseline_false / baseline_total,
            "simultaneous_95pct_lower": baseline_lower,
        },
        "development": {
            "train_company_disjoint_oof": train_summary,
            "test_trained_on_train_only": test_summary,
            "combined_out_of_sample_predictions": combined_summary,
            "certified_error_reduction_lower_if_treated_as_validation": reduction_lower,
            "formal_certificate_claimed": False,
        },
        "folds": folds,
        "decision": {
            "candidate_frozen_for_external_validation": ready,
            "untouched_external_validation_required": True,
            "pass_statistical_10x_claimed": False,
            "automatic_production_change": False,
            "verdict": (
                "DIGIT_FOREST_V3_READY_FOR_UNTOUCHED_EXTERNAL_VALIDATION"
                if ready
                else "DIGIT_FOREST_V3_NOT_READY_TO_FREEZE"
            ),
        },
        "constraints": {
            "external_spend_usd": 0,
            "gcloud_used": False,
            "gpu_used": False,
            "paid_api_used": False,
            "production_modified": False,
        },
    }
    report["stable_payload_sha256"] = sha256_bytes(
        canonical_json(report).encode("utf-8")
    )
    return report, all_decisions


def train_final_model(
    matrix: np.ndarray,
    labels: np.ndarray,
) -> ExtraTreesClassifier:
    model = _new_model(FINAL_RANDOM_STATE)
    model.fit(matrix, labels)
    return model


def freeze_candidate(
    roots: Sequence[Path],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    receipts, source = load_receipts(roots)
    matrix, labels, metadata = build_patch_matrix(receipts)
    report, decisions = development_report(
        receipts,
        source,
        matrix,
        labels,
        metadata,
    )
    if not report["decision"]["candidate_frozen_for_external_validation"]:
        raise RuntimeError("candidate did not satisfy development freeze gates")
    model = train_final_model(matrix, labels)
    model_path = output_dir / MODEL_FILENAME
    joblib.dump(
        {
            "schema": CANDIDATE_SCHEMA,
            "feature_schema": FEATURE_SCHEMA,
            "threshold": THRESHOLD,
            "view_names": VIEW_NAMES,
            "model_parameters": MODEL_PARAMETERS,
            "random_state": FINAL_RANDOM_STATE,
            "model": model,
        },
        model_path,
        compress=3,
        protocol=5,
    )
    model_sha256 = _sha256(model_path)
    candidate: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": "digit-forest-v3",
        "status": "FROZEN_FOR_UNTOUCHED_EXTERNAL_VALIDATION_ONLY",
        "model": {
            "filename": MODEL_FILENAME,
            "sha256": model_sha256,
            "class": "sklearn.ensemble.ExtraTreesClassifier",
            "parameters": MODEL_PARAMETERS,
            "random_state": FINAL_RANDOM_STATE,
            "classes": [int(value) for value in model.classes_],
            "tree_count": len(model.estimators_),
        },
        "inference": {
            "views": list(VIEW_NAMES),
            "feature_schema": FEATURE_SCHEMA,
            "feature_width": int(matrix.shape[1]),
            "threshold": THRESHOLD,
            "uses_truth": False,
            "uses_annotation_bbox": False,
            "input": "OCR-produced numeric token crop plus equal-length digit claim",
            "decision_rule": report["protocol"]["decision_rule"],
        },
        "training": {
            "dataset": "jsdnrs/ICDAR2019-SROIE",
            "dataset_status": "opened development data; never external validation",
            "receipt_count": len(receipts),
            "patch_count": int(matrix.shape[0]),
            "training_receipt_set_sha256": source[
                "training_receipt_set_sha256"
            ],
            "development_report_stable_payload_sha256": report[
                "stable_payload_sha256"
            ],
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
            "repository_commit": os.environ.get("GITHUB_SHA"),
        },
        "decision": {
            "untouched_external_validation_required": True,
            "production_ready": False,
            "automatic_production_change": False,
        },
    }
    candidate["stable_payload_sha256"] = sha256_bytes(
        canonical_json(candidate).encode("utf-8")
    )
    report_path = output_dir / "development_report.json"
    decisions_path = output_dir / "development_decisions.jsonl"
    candidate_path = output_dir / "frozen_candidate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with decisions_path.open("w", encoding="utf-8") as handle:
        for row in decisions:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    candidate_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    outputs = [model_path, candidate_path, report_path, decisions_path]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{_sha256(path)}  {path.name}" for path in outputs) + "\n",
        encoding="utf-8",
    )
    return {
        "candidate": candidate,
        "development_report": report,
    }


def load_frozen_candidate(
    root: Path,
) -> tuple[dict[str, Any], ExtraTreesClassifier]:
    candidate_path = root / "frozen_candidate.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not verify_stable_payload(candidate, "stable_payload_sha256"):
        raise RuntimeError("candidate stable payload mismatch")
    model_path = root / str(candidate["model"]["filename"])
    if _sha256(model_path) != str(candidate["model"]["sha256"]):
        raise RuntimeError("candidate model hash mismatch")
    payload = joblib.load(model_path)
    if payload["schema"] != CANDIDATE_SCHEMA:
        raise RuntimeError("unexpected model payload schema")
    if float(payload["threshold"]) != float(candidate["inference"]["threshold"]):
        raise RuntimeError("model/candidate threshold mismatch")
    model = payload["model"]
    if list(model.classes_) != list(range(10)):
        raise RuntimeError("loaded model classes are not 0..9")
    return candidate, model


def infer_claim(
    model: ExtraTreesClassifier,
    crop: Image.Image,
    claim: str,
    *,
    threshold: float = THRESHOLD,
) -> dict[str, Any]:
    if not claim or not claim.isdigit():
        raise ValueError("claim must be a non-empty digit string")
    feature_rows: list[np.ndarray] = []
    patch_positions: list[int] = []
    patch_views: list[int] = []
    for view_index, view_name in enumerate(VIEW_NAMES):
        patches, _ = _segment(_ink(deterministic_views(crop)[view_name]), len(claim))
        for position, patch in enumerate(patches):
            feature_rows.append(digit_patch_feature(patch))
            patch_positions.append(position)
            patch_views.append(view_index)
    matrix = np.vstack(feature_rows).astype(np.float32, copy=False)
    probabilities = predict_patch_probabilities(model, matrix)
    predicted: list[str] = []
    positions: list[dict[str, Any]] = []
    minimum_probability = 1.0
    for position in range(len(claim)):
        mask = np.asarray(patch_positions) == position
        mean_probability = probabilities[mask].mean(axis=0)
        digit = str(int(np.argmax(mean_probability)))
        confidence = float(np.max(mean_probability))
        predicted.append(digit)
        minimum_probability = min(minimum_probability, confidence)
        positions.append(
            {
                "position": position,
                "claim_digit": claim[position],
                "predicted_digit": digit,
                "mean_probability": confidence,
                "claim_probability": float(mean_probability[int(claim[position])]),
            }
        )
    prediction = "".join(predicted)
    return {
        "claim": claim,
        "prediction": prediction,
        "minimum_mean_probability": minimum_probability,
        "threshold": threshold,
        "accepted": bool(
            prediction == claim and minimum_probability >= threshold
        ),
        "positions": positions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = freeze_candidate(args.roots, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
