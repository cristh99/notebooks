from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from unknown_changepoint_compiler import (
    CORRECT_TOTAL_EVALUATIONS,
    FORMER_TOTAL_EVALUATIONS,
    build_certificate as build_private_certificate,
    compile_unknown_change,
    control,
    verify_certificate as verify_private_certificate,
    with_resource_limit,
)

ROOT = Path(__file__).resolve().parent
PRIVATE_HEAD = "c2d1f0ce1b6a94c56ce12412fcf1c19ad7ae0dff"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def audit_private_snapshot() -> dict[str, object]:
    result = compile_unknown_change(control())
    if result["status"] != "SOLVED":
        raise AssertionError(f"control did not solve: {result}")
    if result["detection"] != {
        **result["detection"],
        "candidate": "R1",
        "breakpoint": "b6",
        "detection_batch": "b7",
    }:
        raise AssertionError(f"unexpected detection: {result['detection']}")
    if result["selection_sequence"] != ["global"] * 6 + ["R1"] * 5:
        raise AssertionError("selection sequence changed")

    alpha = result["alpha_hierarchy"]
    if alpha["change_total"] != [1, 100]:
        raise AssertionError("change alpha changed")
    if alpha["candidate_weights"] != {"R1": [1, 2], "R2": [1, 2]}:
        raise AssertionError("candidate hierarchy changed")
    if not Fraction(*alpha["spent_through_horizon"]) < Fraction(1, 100):
        raise AssertionError("alpha hierarchy overspent")
    if not Fraction(*alpha["tail_reserve"]) > 0:
        raise AssertionError("alpha hierarchy lost its tail reserve")

    manifest = result["manifest"]
    expected_manifest = {
        "signature": "PASS",
        "row_merkle_proofs": "PASS",
        "availability_binding": "PASS",
        "rows_per_cluster": 2,
        "cluster_atomicity": "PASS",
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            raise AssertionError(f"manifest gate {key} changed")

    resources = result["resources"]
    expected_resources = {
        "change_detection_evaluations": 38_016,
        "adaptive_monitoring_evaluations": 104_959,
        "baseline_monitoring_evaluations": 230_912,
        "signature_verifications": 1,
        "former_total_evaluations": 289_408,
        "total_evaluations": 373_888,
    }
    for key, expected in expected_resources.items():
        if resources.get(key) != expected:
            raise AssertionError(f"resource {key}: {resources.get(key)} != {expected}")
    if sum(
        expected_resources[key]
        for key in (
            "change_detection_evaluations",
            "adaptive_monitoring_evaluations",
            "baseline_monitoring_evaluations",
            "signature_verifications",
        )
    ) != CORRECT_TOTAL_EVALUATIONS:
        raise AssertionError("independent resource arithmetic failed")

    old_cap = compile_unknown_change(
        with_resource_limit(control(), FORMER_TOTAL_EVALUATIONS)
    )
    exact_cap = compile_unknown_change(
        with_resource_limit(control(), CORRECT_TOTAL_EVALUATIONS)
    )
    if old_cap["status"] != "UNKNOWN_RESOURCE_LIMIT":
        raise AssertionError(f"former cap was accepted: {old_cap}")
    if old_cap["required_evaluations"] != CORRECT_TOTAL_EVALUATIONS:
        raise AssertionError("former-cap obligation changed")
    if exact_cap["status"] != "SOLVED":
        raise AssertionError(f"correct cap did not solve: {exact_cap}")

    no_change = compile_unknown_change(control("no_change"))
    r2_change = compile_unknown_change(control("r2_change"))
    if no_change["status"] != "SOLVED" or no_change["detection"] is not None:
        raise AssertionError("no-change control raised a false alarm")
    if no_change["selection_sequence"] != ["global"] * 11:
        raise AssertionError("no-change learner sequence changed")
    if r2_change["status"] != "SOLVED":
        raise AssertionError("R2 control did not solve")
    if (
        r2_change["detection"]["candidate"],
        r2_change["detection"]["breakpoint"],
        r2_change["detection"]["detection_batch"],
    ) != ("R2", "b6", "b7"):
        raise AssertionError("R2 control selected the wrong alternative")

    expected_negatives = {
        "manifest_tamper": "INVALID_MANIFEST_SIGNATURE",
        "signature_tamper": "INVALID_MANIFEST_SIGNATURE",
        "row_merkle_tamper": "INVALID_ROW_MERKLE_ROOT",
        "cluster_reuse": "INVALID_CLUSTER_DEPENDENCE",
        "row_overcount": "INVALID_CLUSTER_ATOMICITY",
        "current_outcome": "INVALID_PREDICTABILITY",
        "post_hoc_retirement": "INVALID_POST_HOC_SELECTION",
        "off_model": "UNKNOWN_CHANGE_MODEL",
        "resource": "UNKNOWN_RESOURCE_LIMIT",
    }
    negative_results = {
        mode: compile_unknown_change(control(mode))["status"]
        for mode in expected_negatives
    }
    if negative_results != expected_negatives:
        raise AssertionError(f"negative controls changed: {negative_results}")

    adaptive = result["adaptive_final"]
    baseline = result["baseline_final"]
    expected_adaptive = {
        "lower": [50_571, 131_072],
        "upper": [164_015, 262_144],
        "width": [62_873, 262_144],
    }
    expected_baseline = {
        "lower": [6_579, 16_384],
        "upper": [175_259, 262_144],
        "width": [69_995, 262_144],
    }
    for key, expected in expected_adaptive.items():
        if adaptive[key] != expected:
            raise AssertionError(f"adaptive {key} changed: {adaptive[key]}")
    for key, expected in expected_baseline.items():
        if baseline[key] != expected:
            raise AssertionError(f"baseline {key} changed: {baseline[key]}")
    adaptive_width = Fraction(*adaptive["width"])
    baseline_width = Fraction(*baseline["width"])
    if not adaptive_width < baseline_width:
        raise AssertionError("adaptive interval no longer improves the baseline")
    if baseline_width - adaptive_width != Fraction(7_122, 262_144):
        raise AssertionError("width-reduction identity changed")
    if not result["truth_included_at_every_time"]:
        raise AssertionError("truth left the confidence sequence")

    private_certificate = build_private_certificate()
    if verify_private_certificate(private_certificate):
        raise AssertionError("private certificate failed replay")
    tampered_private = deepcopy(private_certificate)
    tampered_private["payload"]["result"]["selection_sequence"] = []
    if verify_private_certificate(tampered_private) != ["payload-hash"]:
        raise AssertionError("private certificate tamper was accepted")

    return {
        "status": "PASS",
        "private_head": PRIVATE_HEAD,
        "detection": result["detection"],
        "selection_sequence": result["selection_sequence"],
        "alpha_hierarchy": result["alpha_hierarchy"],
        "manifest": result["manifest"],
        "resources": expected_resources,
        "former_cap": {
            "limit": FORMER_TOTAL_EVALUATIONS,
            "status": old_cap["status"],
        },
        "correct_cap": {
            "limit": CORRECT_TOTAL_EVALUATIONS,
            "status": exact_cap["status"],
        },
        "no_change": {
            "detection": no_change["detection"],
            "selection_sequence": no_change["selection_sequence"],
        },
        "alternative_change": r2_change["detection"],
        "negative_controls": negative_results,
        "score_count": len(result["scores"]),
        "adaptive_final": adaptive,
        "baseline_final": baseline,
        "absolute_width_reduction": [7_122, 262_144],
        "relative_width_reduction": [7_122, 69_995],
        "truth_included_at_every_time": True,
        "private_certificate_sha256": private_certificate["sha256"],
    }


def build_certificate() -> dict[str, object]:
    payload = {
        "schema": "unknown-changepoint-public-audit/1",
        "audit": audit_private_snapshot(),
        "scientific_boundary": (
            "Public replay of an immutable finite detector with two declared "
            "alternative regimes, finite unknown breakpoint candidates, signed "
            "availability manifests, cluster-atomic evidence and exact rational "
            "monitoring. It is not a universal change-point theorem."
        ),
    }
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    claimed = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["certificate-shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    expected = build_certificate()
    if canonical_json(expected["payload"]) != canonical_json(payload):
        return ["semantic-replay"]
    return []


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public certificate failed self replay")

    tampered = deepcopy(certificate)
    tampered["payload"]["audit"]["resources"]["total_evaluations"] = 289_408
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper was accepted")

    forged = deepcopy(certificate)
    forged["payload"]["audit"]["resources"]["total_evaluations"] = 289_408
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery was accepted")

    report = {
        "schema": "unknown-changepoint-public-report/1",
        **certificate["payload"]["audit"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": certificate["payload"]["scientific_boundary"],
    }
    report["sha256"] = digest(report)
    (ROOT / "UNKNOWN_CHANGEPOINT_PUBLIC_CERTIFICATE.json").write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ROOT / "UNKNOWN_CHANGEPOINT_PUBLIC_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
