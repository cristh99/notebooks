"""Independent structural and statistical replay of OCR holdout artifacts."""
from __future__ import annotations

import argparse
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import absolute_risk_gate, canonical_json, risk_gate, sha256_bytes, verify_manifest_hash


def semantic_equal(left: Any, right: Any, *, tolerance: float = 1e-12) -> bool:
    """Compare replayed JSON semantically, ignoring int/float spelling only."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, Real) and isinstance(right, Real):
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            semantic_equal(left[key], right[key], tolerance=tolerance) for key in left
        )
    if (
        isinstance(left, Sequence)
        and isinstance(right, Sequence)
        and not isinstance(left, (str, bytes))
        and not isinstance(right, (str, bytes))
    ):
        return len(left) == len(right) and all(
            semantic_equal(a, b, tolerance=tolerance)
            for a, b in zip(left, right, strict=True)
        )
    return left == right


def rebuild_fold_gate(rows: Sequence[Mapping[str, Any]], *, declared: Mapping[str, Any], reference_minimum_accepted: int, full_eligible: int) -> dict[str, Any]:
    eligible = [row for row in rows if row["tesseract"]["eligible"]]
    accepted = [row for row in eligible if row["verifier"]["accept"]]
    scaled_minimum = max(1, math.floor(reference_minimum_accepted * (len(eligible) / max(full_eligible, 1)) * 0.75))
    return risk_gate(
        baseline_false=sum(not row["tesseract"]["claim_correct"] for row in eligible),
        baseline_total=len(eligible),
        candidate_false=sum(row["verifier"]["false_accept"] for row in accepted),
        candidate_total=len(accepted),
        eligible_total=max(len(eligible), 1),
        factor=float(declared["target_reduction_factor"]),
        alpha=float(declared["alpha_one_sided"]),
        minimum_accepted=scaled_minimum,
        minimum_coverage=float(declared["minimum_coverage"]),
    )


def verify(manifest: dict[str, Any], report: dict[str, Any], *, artifact_root: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if not verify_manifest_hash(manifest): errors.append("manifest hash mismatch")
    if report.get("source", {}).get("manifest_sha256") != manifest.get("manifest_sha256"): errors.append("report is not bound to manifest")

    manifest_crops = manifest.get("crops") or []
    observations = report.get("observations") or []
    manifest_ids = [str(row.get("crop_id")) for row in manifest_crops]
    observation_ids = [str(row.get("crop_id")) for row in observations]
    if len(manifest_ids) != len(set(manifest_ids)): errors.append("duplicate manifest crop identities")
    if len(observation_ids) != len(set(observation_ids)): errors.append("duplicate observation crop identities")
    if sorted(manifest_ids) != sorted(observation_ids): errors.append("observation crop set differs from sealed manifest")
    unit_ids = [str(row.get("unit_id")) for row in observations]
    if len(unit_ids) != len(set(unit_ids)): errors.append("more than one observation from a procurement unit")

    if artifact_root is not None:
        for row in observations:
            relative = row.get("crop_file")
            if not relative:
                errors.append(f"crop file missing from observation {row.get('crop_id')}")
                continue
            path = artifact_root / str(relative)
            if not path.exists():
                errors.append(f"crop artifact missing: {relative}")
                continue
            if sha256_bytes(path.read_bytes()) != row.get("crop_png_sha256"):
                errors.append(f"crop artifact hash mismatch: {relative}")

    eligible = [row for row in observations if row.get("tesseract", {}).get("eligible")]
    accepted = [row for row in eligible if row.get("verifier", {}).get("accept")]
    declared_gate = report.get("risk_gate") or {}
    rebuilt_gate = risk_gate(
        baseline_false=sum(not row["tesseract"]["claim_correct"] for row in eligible),
        baseline_total=len(eligible),
        candidate_false=sum(row["verifier"]["false_accept"] for row in accepted),
        candidate_total=len(accepted),
        eligible_total=max(len(eligible), 1),
        factor=float(declared_gate.get("target_reduction_factor", 10.0)),
        alpha=float(declared_gate.get("alpha_one_sided", 0.05)),
        minimum_accepted=int(declared_gate.get("minimum_accepted", 200)),
        minimum_coverage=float(declared_gate.get("minimum_coverage", 0.30)),
    )
    if not semantic_equal(rebuilt_gate, declared_gate): errors.append("main risk gate does not replay")

    declared_stability = report.get("institution_stability") or {}
    institutions = sorted({str(row["institution"]) for row in observations})
    rebuilt_folds: list[dict[str, Any]] = []
    for institution in institutions:
        subset = [row for row in observations if row["institution"] != institution]
        rebuilt_folds.append({
            "held_out_institution": institution,
            "remaining_crops": len(subset),
            "gate": rebuild_fold_gate(
                subset,
                declared=declared_gate,
                reference_minimum_accepted=int(declared_gate["minimum_accepted"]),
                full_eligible=len(eligible),
            ),
        })
    fold_passes = sum(bool(row["gate"]["pass"]) for row in rebuilt_folds)
    fold_fraction = fold_passes / len(rebuilt_folds) if rebuilt_folds else 0.0
    rebuilt_stability = {
        "folds": rebuilt_folds,
        "fold_count": len(rebuilt_folds),
        "passes": fold_passes,
        "pass_fraction": fold_fraction,
        "minimum_required_pass_fraction": float(declared_stability.get("minimum_required_pass_fraction", 0.80)),
        "pass": bool(rebuilt_folds and fold_fraction >= float(declared_stability.get("minimum_required_pass_fraction", 0.80))),
    }
    if not semantic_equal(rebuilt_stability, declared_stability): errors.append("institution stability replay differs")

    declared_counterfactual = report.get("counterfactual_gate") or {}
    rebuilt_counterfactual = absolute_risk_gate(
        false_accepts=sum(row["counterfactual"]["false_accept"] for row in observations),
        total=len(observations),
        maximum_upper_risk=float(declared_counterfactual.get("maximum_upper_risk", 0.03)),
        minimum_total=int(declared_counterfactual.get("minimum_total", 100)),
        alpha=float(declared_counterfactual.get("alpha_one_sided", 0.05)),
    )
    if not semantic_equal(rebuilt_counterfactual, declared_counterfactual): errors.append("counterfactual risk gate does not replay")

    if not rebuilt_gate["pass"]: rebuilt_verdict = rebuilt_gate["reason"]
    elif not rebuilt_stability["pass"]: rebuilt_verdict = "INSTITUTION_STABILITY_GATE_FAILED"
    elif not rebuilt_counterfactual["pass"]: rebuilt_verdict = "COUNTERFACTUAL_RISK_GATE_FAILED"
    else: rebuilt_verdict = "PASS_HN_NUMERIC_SUBSTITUTION_RISK_10X"
    if rebuilt_verdict != report.get("decision", {}).get("verdict"): errors.append("decision verdict does not replay")

    stable = dict(report)
    observed_hash = str(stable.pop("stable_payload_sha256", ""))
    rebuilt_hash = sha256_bytes(canonical_json(stable).encode("utf-8"))
    if observed_hash != rebuilt_hash: errors.append("stable payload hash mismatch")

    return {
        "valid": not errors,
        "errors": errors,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "observed_stable_payload_sha256": observed_hash,
        "rebuilt_stable_payload_sha256": rebuilt_hash,
        "replayed_risk_gate": rebuilt_gate,
        "replayed_institution_stability": {key: rebuilt_stability[key] for key in ("fold_count", "passes", "pass_fraction", "pass")},
        "replayed_counterfactual_gate": rebuilt_counterfactual,
        "replayed_verdict": rebuilt_verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    artifact_root = args.artifact_root or args.report.parent
    result = verify(
        json.loads(args.manifest.read_text(encoding="utf-8")),
        json.loads(args.report.read_text(encoding="utf-8")),
        artifact_root=artifact_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__": raise SystemExit(main())
