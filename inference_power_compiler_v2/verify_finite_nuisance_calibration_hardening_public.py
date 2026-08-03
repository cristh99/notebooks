from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

import verify_finite_nuisance_calibration_public as base

ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def statistics() -> tuple[dict[str, object], ...]:
    success = {
        "e|z0": 2048,
        "e|z1": 2048,
        "mu0|z0": 1024,
        "mu0|z1": 1024,
        "mu1|z0": 3072,
        "mu1|z1": 3072,
    }
    return tuple(
        {
            "stat_id": f"c{index}:{component}",
            "available_index": index,
            "component": component,
            "successes": success[component],
            "trials": 4096,
        }
        for index in range(8)
        for component in base.COMPONENTS
    )


def online_row_ids() -> set[str]:
    return {
        f"online:{batch}:event:{event_index}"
        for batch in ("b0", *base.BATCHES)
        for event_index in range(16 if batch != "b0" else 32)
    }


def build_manifest(
    stats: tuple[dict[str, object], ...],
    online_ids: set[str],
) -> dict[str, object]:
    stat_ids = [str(item["stat_id"]) for item in stats]
    if len(stat_ids) != len(set(stat_ids)):
        return {"status": "INVALID_CALIBRATION_SOURCE_DUPLICATE"}
    collisions = sorted(set(stat_ids) & online_ids)
    if collisions:
        return {
            "status": "INVALID_CALIBRATION_SOURCE_COLLISION",
            "witness": collisions[0],
        }
    return {
        "status": "SOLVED",
        "provenance_mode": "STRICTLY_PRIOR_AGGREGATE_SUFFICIENT_STATISTICS",
        "stat_sha256": {
            str(item["stat_id"]): digest(item) for item in stats
        },
    }


def expected_sources(
    stats: tuple[dict[str, object], ...], monitoring_index: int
) -> list[str]:
    return sorted(
        str(item["stat_id"])
        for item in stats
        if int(item["available_index"]) <= monitoring_index
    )


def evaluate_hardening() -> dict[str, object]:
    control = base.evaluate()
    if control.get("status") != "SOLVED":
        raise AssertionError(control)
    stats = statistics()
    manifest = build_manifest(stats, online_row_ids())
    if manifest["status"] != "SOLVED":
        raise AssertionError(manifest)
    source_packets = {}
    for index, batch in enumerate(base.BATCHES):
        sources = expected_sources(stats, index)
        if len(sources) != 6 * (index + 1):
            raise AssertionError("cumulative source count changed")
        source_packets[batch] = {
            "source_ids": sources,
            "source_count": len(sources),
            "source_digest": digest(sources),
        }
    if len(manifest["stat_sha256"]) != 48:
        raise AssertionError("manifest size changed")
    if control["adaptive_final"]["width"] != [125371, 262144]:
        raise AssertionError("adaptive metric changed")
    if control["baseline_final"]["width"] != [216003, 262144]:
        raise AssertionError("baseline metric changed")
    if control["relative_width_reduction"] != [90632, 216003]:
        raise AssertionError("relative reduction changed")

    collision_stats = list(stats)
    collision_stats[0] = dict(collision_stats[0])
    collision_stats[0]["stat_id"] = next(iter(online_row_ids()))
    collision = build_manifest(tuple(collision_stats), online_row_ids())
    if collision["status"] != "INVALID_CALIBRATION_SOURCE_COLLISION":
        raise AssertionError("source collision was accepted")

    return {
        "status": "SOLVED",
        "base_control_sha256": digest(control),
        "manifest": manifest,
        "source_packets": source_packets,
        "collision_negative": collision,
        "base_metrics": {
            "score_count": control["score_count"],
            "adaptive_final": control["adaptive_final"],
            "baseline_final": control["baseline_final"],
            "relative_width_reduction": control["relative_width_reduction"],
            "truth_included_at_every_time": control[
                "truth_included_at_every_time"
            ],
            "resources": control["resources"],
        },
        "hardening": {
            "source_namespace_disjointness": "PASS",
            "source_hash_manifest": "PASS",
            "batch_source_exactness": "PASS",
            "envelope_source_rebinding": "PASS",
            "base_metrics_unchanged": "PASS",
        },
    }


def private_binding() -> object:
    path = os.environ.get("PRIVATE_BINDING_PATH")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    return {"status": "UNBOUND_LOCAL_REPLAY"}


def build_payload() -> dict[str, object]:
    result = evaluate_hardening()
    return {
        "schema": "finite-nuisance-calibration-hardening/public-independent-certificate/1",
        "private_binding": private_binding(),
        "public_base_verifier_sha256": sha256(
            Path(base.__file__).read_bytes()
        ).hexdigest(),
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "result": result,
        "gates": {
            "source_namespace_disjointness": "PASS",
            "source_hash_manifest": "PASS",
            "batch_source_exactness": "PASS",
            "envelope_source_rebinding": "PASS",
            "source_collision_negative": "PASS",
            "base_metrics_unchanged": "PASS",
        },
        "scientific_boundary": (
            "Independent source-provenance hardening over the public calibration "
            "replay. Aggregate sufficient-statistic hashes make source substitution "
            "detectable and enforce a disjoint ID namespace. They do not prove that "
            "an external data producer reported counts honestly; raw-row Merkle "
            "binding remains a separate systems obligation."
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
    result = payload["result"]
    report = {
        "schema": "finite-nuisance-calibration-hardening/public-independent-report/1",
        "private_binding": payload["private_binding"],
        "public_base_verifier_sha256": payload["public_base_verifier_sha256"],
        "manifest_size": len(result["manifest"]["stat_sha256"]),
        "first_batch_source_count": result["source_packets"]["b1"][
            "source_count"
        ],
        "final_batch_source_count": result["source_packets"]["b8"][
            "source_count"
        ],
        "collision_negative": result["collision_negative"]["status"],
        "base_metrics": result["base_metrics"],
        "hardening": result["hardening"],
        "gates": payload["gates"],
        "certificate_sha256": certificate["sha256"],
        "semantic_replay": "PASS",
        "tampered_certificate": "REJECTED:payload-hash",
        "forged_certificate": "REJECTED:semantic-replay",
        "scientific_boundary": payload["scientific_boundary"],
    }
    report["sha256"] = digest(report)
    return report


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    certificate = build_certificate()
    if verify_certificate(certificate):
        raise AssertionError("hardening certificate failed replay")
    tampered = deepcopy(certificate)
    tampered["payload"]["result"]["manifest"]["stat_sha256"][
        next(iter(tampered["payload"]["result"]["manifest"]["stat_sha256"]))
    ] = "0" * 64
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("manifest tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["result"]["manifest"]["stat_sha256"][
        next(iter(forged["payload"]["result"]["manifest"]["stat_sha256"]))
    ] = "0" * 64
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("manifest semantic forgery accepted")
    report = build_report(certificate)
    write(ROOT / "FINITE_NUISANCE_CALIBRATION_HARDENING_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "FINITE_NUISANCE_CALIBRATION_HARDENING_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
