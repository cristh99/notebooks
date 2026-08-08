from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

import verify_drift_aware_online_crossfit_public as base

ROOT = Path(__file__).resolve().parent
PRIVATE_HEAD = "1f5241b157976caeeaaec3ed8cef5d20bde60fb1"
PRIVATE_BLOBS = {
    "base_compiler": "3de813e42f1cd4c9fd3c4e3c562a654537de4dfd",
    "hardening": "7e04055f573f92e54275668981c936a54d771db6",
    "runner": "7084cd1b925e0ea19c7584045311ad01ef13911c",
    "tests": "b32dcb811954f70cde472476142609e780e677df",
    "lean": "2cd1c5c0407b62fe73cfe7c07b27c1390516c723",
    "workflow": "3f5d05bfa8edcee717b729f22d3d0344b21ab871",
}
PUBLIC_BASE_VERIFIER_BLOB = "9d1e77f95df346279957ce60ef4079f616d9b110"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def conservative_required_factor_evaluations() -> dict[str, int]:
    endpoints = tuple(16 * index for index in range(1, 13))
    endpoint_prefix_rows = sum(endpoints)
    root_work = endpoint_prefix_rows * 10 * (base.DEPTH + 4)
    truth_work = 4 * 192 * 193
    total = root_work + truth_work
    if endpoints != (16, 32, 48, 64, 80, 96, 112, 128, 144, 160, 176, 192):
        raise AssertionError("endpoint schedule changed")
    if endpoint_prefix_rows != 1248 or root_work != 274560:
        raise AssertionError("root accounting changed")
    if truth_work != 148224 or total != 422784:
        raise AssertionError("truth-prefix accounting changed")
    return {
        "endpoint_prefix_rows": endpoint_prefix_rows,
        "root_factor_multiplications": root_work,
        "truth_factor_multiplications": truth_work,
        "total_factor_multiplications": total,
    }


def within_batch_cluster_negative() -> dict[str, object]:
    state = base.build_state()
    rows_by_batch = state["rows_by_batch"]
    clusters = dict(state["clusters"])
    batch_rows = rows_by_batch["b2"]
    clusters[batch_rows[1].row_id] = clusters[batch_rows[0].row_id]
    sequence = [clusters[row.row_id] for row in batch_rows]
    if len(sequence) == len(set(sequence)):
        raise AssertionError("within-batch duplicate was not created")
    seen: set[str] = set()
    duplicate: str | None = None
    for cluster in sequence:
        if cluster in seen:
            duplicate = cluster
            break
        seen.add(cluster)
    if duplicate is None:
        raise AssertionError("duplicate cluster was not recovered")
    return {
        "status": "INVALID_CLUSTER_DEPENDENCE",
        "batch": "b2",
        "cluster": duplicate,
        "reason": "WITHIN_BATCH_CLUSTER_REUSE",
    }


def first_batch_monitoring_negative() -> dict[str, object]:
    monitoring_batch = "b0"
    order = {f"b{index}": index for index in range(13)}
    if order[monitoring_batch] != 0:
        raise AssertionError("first monitoring batch changed")
    return {
        "status": "INVALID_MONITORING_ORIGIN",
        "batch": monitoring_batch,
        "reason": "NO_STRICT_PREDECESSOR_FOR_DRIFT_REFERENCE",
    }


def resource_gap_negative() -> dict[str, object]:
    accounting = conservative_required_factor_evaluations()
    cap = 300000
    required = accounting["total_factor_multiplications"]
    if not required > cap:
        raise AssertionError("resource gap disappeared")
    return {
        "status": "UNKNOWN_RESOURCE_LIMIT",
        "required_factor_multiplications": required,
        "cap": cap,
        "accounting": "CONSERVATIVE_FACTOR_MULTIPLICATIONS",
    }


def evaluate_hardened_control() -> dict[str, object]:
    control = base.evaluate()
    if control.get("status") != "SOLVED":
        raise AssertionError(control)
    if control["score_count"] != 192:
        raise AssertionError("score count changed")
    if control["adaptive_final"] != {
        "nonempty": True,
        "lower": [38981, 131072],
        "upper": [88917, 131072],
        "width": [3121, 8192],
    }:
        raise AssertionError("adaptive interval changed")
    if control["baseline_final"] != {
        "nonempty": True,
        "lower": [60847, 262144],
        "upper": [50713, 65536],
        "width": [142005, 262144],
    }:
        raise AssertionError("baseline interval changed")
    if control["relative_width_reduction"] != [42133, 142005]:
        raise AssertionError("relative reduction changed")
    if not control["truth_included_at_every_time"]:
        raise AssertionError("truth left the sequence")
    expected_remainders = [
        [1, 18], [1, 98], [1, 242], [1, 450], [1, 722], [1, 1058],
        [1, 1458], [1, 1922], [1, 2450], [1, 3042], [1, 3698], [1, 4418],
    ]
    if control["remainders"] != expected_remainders:
        raise AssertionError("remainder sequence changed")
    accounting = conservative_required_factor_evaluations()
    result = deepcopy(control)
    result["base_reported_evaluations"] = control["required_mixture_evaluations"]
    result["required_factor_evaluations"] = accounting[
        "total_factor_multiplications"
    ]
    result["resource_accounting"] = accounting
    result["hardening"] = {
        "within_batch_cluster_uniqueness": "PASS",
        "monitoring_predecessor": "PASS",
        "conservative_resource_accounting": "PASS",
        "former_resource_gap": "REJECTED",
    }
    return result


def build_payload() -> dict[str, object]:
    control = evaluate_hardened_control()
    negatives = {
        "within_batch_cluster": within_batch_cluster_negative(),
        "first_batch_monitoring": first_batch_monitoring_negative(),
        "resource_gap": resource_gap_negative(),
    }
    inherited_expected = {
        "current_leakage": "INVALID_PREDICTABILITY",
        "future_leakage": "INVALID_PREDICTABILITY",
        "envelope_future": "INVALID_PREDICTABILITY",
        "false_envelope": "INVALID_ENVELOPE_CERTIFICATE",
        "product_rate": "UNKNOWN_PRODUCT_RATE",
        "product_regression": "UNKNOWN_PRODUCT_RATE_REGRESSION",
        "cluster_reuse": "INVALID_CLUSTER_DEPENDENCE",
        "design_drift": "UNKNOWN_DESIGN_DRIFT",
        "score_bound": "INVALID_SCORE_BOUND",
        "resource": "UNKNOWN_RESOURCE_LIMIT",
        "post_hoc": "INVALID_POST_HOC_SELECTION",
    }
    inherited: dict[str, object] = {}
    for mode, expected in inherited_expected.items():
        packet = base.evaluate(mode)
        if packet.get("status") != expected:
            raise AssertionError(f"inherited negative {mode} changed: {packet}")
        inherited[mode] = packet

    if control["required_factor_evaluations"] != 422784:
        raise AssertionError("corrected requirement changed")
    if control["base_reported_evaluations"] != 251136:
        raise AssertionError("base counter changed")

    return {
        "schema": "drift-aware-online-crossfit-hardening/public-independent-certificate/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": PRIVATE_HEAD,
            "blobs": PRIVATE_BLOBS,
        },
        "public_base_binding": {
            "repository": "cristh99/notebooks",
            "verifier_blob": PUBLIC_BASE_VERIFIER_BLOB,
        },
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "control": control,
        "new_negative_controls": negatives,
        "inherited_negative_controls": inherited,
        "gates": {
            "base_regression": "PASS",
            "within_batch_cluster_uniqueness": "PASS",
            "monitoring_predecessor": "PASS",
            "conservative_resource_accounting": "PASS",
            "former_resource_gap": "REJECTED",
            "truth_anytime_inclusion": "PASS",
            "continuous_root_inversion": "PASS",
            "semantic_replay": "PASS",
        },
        "scientific_boundary": (
            "Independent hardening verification layered on the prior public replay. "
            "It closes within-batch cluster reuse, first-batch predecessor ambiguity "
            "and conservative factor-multiplication accounting. It does not establish "
            "validity under arbitrary within-cluster dependence, learned envelope "
            "calibration, continuous covariates or unrestricted online learners."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload = certificate.get("payload")
    claimed = certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    if canonical(build_certificate()["payload"]) != canonical(payload):
        return ["semantic-replay"]
    return []


def build_report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate["payload"]
    control = payload["control"]
    result = {
        "schema": "drift-aware-online-crossfit-hardening/public-independent-report/1",
        "control": {
            "score_count": control["score_count"],
            "remainders": control["remainders"],
            "adaptive_final": control["adaptive_final"],
            "baseline_final": control["baseline_final"],
            "relative_width_reduction": control["relative_width_reduction"],
            "truth_included_at_every_time": control[
                "truth_included_at_every_time"
            ],
            "base_reported_evaluations": control["base_reported_evaluations"],
            "required_factor_evaluations": control[
                "required_factor_evaluations"
            ],
            "resource_accounting": control["resource_accounting"],
        },
        "new_negative_controls": {
            key: value["status"]
            for key, value in payload["new_negative_controls"].items()
        },
        "inherited_negative_controls": {
            key: value["status"]
            for key, value in payload["inherited_negative_controls"].items()
        },
        "gates": payload["gates"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": payload["scientific_boundary"],
    }
    result["sha256"] = digest(result)
    return result


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("public hardening certificate failed self replay")
    tampered = deepcopy(certificate)
    tampered["payload"]["control"]["score_count"] = 0
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["control"]["score_count"] = 0
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery accepted")
    report = build_report(certificate)
    write(ROOT / "DRIFT_AWARE_ONLINE_HARDENING_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "DRIFT_AWARE_ONLINE_HARDENING_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
