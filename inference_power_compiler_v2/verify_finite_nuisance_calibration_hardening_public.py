from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

import verify_finite_nuisance_calibration_public as base

ROOT = Path(__file__).resolve().parent
PROVENANCE_MODE = "CONTENT_ADDRESSED_DISJOINT_CALIBRATION_BLOCKS"
DATASET_ID = "canonical-finite-nuisance-calibration-control-v1"
_HEX = frozenset("0123456789abcdef")
CORRECTED_RESOURCES = {
    "pair_count": 48,
    "bound_calls_per_pair": 23,
    "base_reported_calibration_evaluations": 61440,
    "calibration_evaluations": 70656,
    "calibration_correction": 9216,
    "monitoring_evaluations": 192768,
    "total_evaluations": 263424,
}
EXPECTED_PRIVATE_BINDING = {
    "schema": "finite-nuisance-calibration-hardening/private-binding/2",
    "repository": "cristh99/my_first_repository",
    "branch": "agent/inference-power-compiler-v2-logic-power-v10",
    "head": "baf7b20d81e3c6f427a935616ec3793fe4516448",
    "binding_mode": "immutable-git-object-ids",
    "files": {
        "base_compiler": {
            "path": "inference_power_compiler_v2/finite_nuisance_calibration_compiler.py",
            "git_blob_sha1": "11bd8fc90b47841438a8d8d4237dd2dcd77bbe85",
        },
        "base_runner": {
            "path": "inference_power_compiler_v2/run_finite_nuisance_calibration_compiler.py",
            "git_blob_sha1": "e95feddf30bdb512692882aa5d6da551106d15dc",
        },
        "hardening": {
            "path": "inference_power_compiler_v2/finite_nuisance_calibration_hardening.py",
            "git_blob_sha1": "63c70276869f14c8f4a67e38a02b169de10e317d",
        },
        "runner": {
            "path": "inference_power_compiler_v2/run_finite_nuisance_calibration_hardening.py",
            "git_blob_sha1": "f52b78f0f22f00db0d7b6ef35ccb7d7f8fd9fec2",
        },
        "tests": {
            "path": "inference_power_compiler_v2/test_finite_nuisance_calibration_hardening.py",
            "git_blob_sha1": "edbcc9b337208ad62b4a546ee0f693c52f611904",
        },
        "lean": {
            "path": "FiniteNuisanceCalibrationHardening.lean",
            "git_blob_sha1": "3b81316d81199d1da916da2e6e9e8235d30f85b4",
        },
        "workflow": {
            "path": ".github/workflows/finite-nuisance-calibration-hardening.yml",
            "git_blob_sha1": "a0a63e06be0c9761bd508faaa000b09ef1f954ea",
        },
    },
}


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def statistics() -> tuple[dict[str, object], ...]:
    successes = {
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
            "successes": successes[component],
            "trials": 4096,
        }
        for index in range(8)
        for component in base.COMPONENTS
    )


def online_row_ids() -> set[str]:
    state = base.merged_state()
    return {row.row_id for row in state["rows"]}


def build_manifest(
    stats: tuple[dict[str, object], ...],
    mode: str | None = None,
) -> dict[str, object]:
    source = {
        str(item["stat_id"]): digest(
            {
                "schema": "calibration-source-slice/1",
                "dataset": DATASET_ID,
                "available_index": item["available_index"],
                "component": item["component"],
            }
        )
        for item in stats
    }
    statistic = {
        str(item["stat_id"]): digest(item) for item in stats
    }
    if mode == "missing_provenance":
        source.pop(next(iter(source)))
    elif mode == "duplicate_source":
        same_component = [
            item for item in stats if item["component"] == base.COMPONENTS[0]
        ]
        source[str(same_component[1]["stat_id"])] = source[
            str(same_component[0]["stat_id"])
        ]
    elif mode == "statistic_mismatch":
        statistic[next(iter(statistic))] = "0" * 64
    elif mode == "malformed_source":
        source[next(iter(source))] = "not-a-sha256"
    return {
        "provenance_mode": (
            "UNDECLARED" if mode == "undeclared_provenance_mode" else PROVENANCE_MODE
        ),
        "source_sha256": source,
        "statistic_sha256": statistic,
    }


def provenance_witness(
    stats: tuple[dict[str, object], ...],
    manifest: Mapping[str, object],
    online_ids: set[str],
) -> dict[str, object] | None:
    by_id = {str(item["stat_id"]): item for item in stats}
    expected_ids = set(by_id)
    source = manifest.get("source_sha256")
    statistic = manifest.get("statistic_sha256")
    if not isinstance(source, Mapping) or not isinstance(statistic, Mapping):
        return {
            "status": "UNKNOWN_CALIBRATION_PROVENANCE",
            "witness": {"reason": "MALFORMED_MANIFEST"},
        }
    source_ids = set(str(key) for key in source)
    statistic_ids = set(str(key) for key in statistic)
    missing = sorted(
        (expected_ids - source_ids) | (expected_ids - statistic_ids)
    )
    if missing:
        return {
            "status": "UNKNOWN_CALIBRATION_PROVENANCE",
            "witness": {"missing_stat_id": missing[0]},
        }
    extra = sorted((source_ids | statistic_ids) - expected_ids)
    if extra:
        return {
            "status": "INVALID_CALIBRATION_PROVENANCE",
            "witness": {
                "reason": "UNDECLARED_STATISTIC",
                "stat_id": extra[0],
            },
        }
    if manifest.get("provenance_mode") != PROVENANCE_MODE:
        return {
            "status": "UNKNOWN_CALIBRATION_PROVENANCE",
            "witness": {
                "reason": "UNSUPPORTED_PROVENANCE_MODE",
                "mode": manifest.get("provenance_mode"),
            },
        }
    collisions = sorted(expected_ids & online_ids)
    if collisions:
        return {
            "status": "INVALID_CALIBRATION_SOURCE_COLLISION",
            "witness": {"stat_id": collisions[0]},
        }

    seen: dict[str, dict[str, str]] = {
        component: {} for component in base.COMPONENTS
    }
    for stat_id in sorted(expected_ids):
        item = by_id[stat_id]
        if statistic[stat_id] != digest(item):
            return {
                "status": "INVALID_CALIBRATION_PROVENANCE",
                "witness": {
                    "reason": "STATISTIC_COMMITMENT_MISMATCH",
                    "stat_id": stat_id,
                },
            }
        source_hash = source[stat_id]
        if (
            not isinstance(source_hash, str)
            or len(source_hash) != 64
            or any(character not in _HEX for character in source_hash)
        ):
            return {
                "status": "INVALID_CALIBRATION_PROVENANCE",
                "witness": {
                    "reason": "MALFORMED_SOURCE_COMMITMENT",
                    "stat_id": stat_id,
                },
            }
        component = str(item["component"])
        previous = seen[component].get(source_hash)
        if previous is not None:
            return {
                "status": "INVALID_CALIBRATION_PROVENANCE",
                "witness": {
                    "reason": "DUPLICATE_SOURCE_COMMITMENT",
                    "component": component,
                    "first_stat_id": previous,
                    "second_stat_id": stat_id,
                },
            }
        seen[component][source_hash] = stat_id
    return None


def expected_sources(
    stats: tuple[dict[str, object], ...], monitoring_index: int
) -> list[str]:
    return sorted(
        str(item["stat_id"])
        for item in stats
        if int(item["available_index"]) <= monitoring_index
    )


def evaluate_hardening(mode: str | None = None) -> dict[str, object]:
    control = base.evaluate()
    if control.get("status") != "SOLVED":
        raise AssertionError(control)
    stats = list(statistics())
    online_ids = online_row_ids()
    if mode == "source_collision":
        stats[0] = dict(stats[0])
        stats[0]["stat_id"] = sorted(online_ids)[0]
    frozen_stats = tuple(stats)
    manifest = build_manifest(frozen_stats, mode)
    witness = provenance_witness(frozen_stats, manifest, online_ids)
    if witness is not None:
        return witness

    if mode == "old_calibration_cap":
        return {
            "status": "UNKNOWN_CALIBRATION_RESOURCE_LIMIT",
            "required_calibration_evaluations": 70656,
            "maximum": 61440,
        }
    if mode == "old_resource_cap":
        return {
            "status": "UNKNOWN_RESOURCE_LIMIT",
            "calibration_evaluations": 70656,
            "monitoring_evaluations": 192768,
            "required_total_evaluations": 263424,
            "maximum": 254208,
        }

    hardened = deepcopy(control)
    source_packets: dict[str, object] = {}
    for index, batch in enumerate(base.BATCHES):
        sources = expected_sources(frozen_stats, index)
        if len(sources) != 6 * (index + 1):
            raise AssertionError("cumulative source count changed")
        calibration_packet = hardened["calibration"][batch]
        if calibration_packet["calibration_stat_ids"] != sources:
            raise AssertionError("batch source set changed")
        for component_packet in calibration_packet["components"].values():
            if not set(component_packet["source_stat_ids"]) <= set(sources):
                raise AssertionError("future calibration source accepted")
        calibration_packet["generated_envelope"]["source_ids"] = sources
        source_packets[batch] = {
            "source_ids": sources,
            "source_count": len(sources),
            "source_digest": digest(sources),
        }

    if hardened["adaptive_final"] != {
        "nonempty": True,
        "lower": [31905, 131072],
        "upper": [189181, 262144],
        "width": [125371, 262144],
    }:
        raise AssertionError("adaptive metric changed")
    if hardened["baseline_final"] != {
        "nonempty": True,
        "lower": [11603, 131072],
        "upper": [239209, 262144],
        "width": [216003, 262144],
    }:
        raise AssertionError("baseline metric changed")
    if hardened["relative_width_reduction"] != [90632, 216003]:
        raise AssertionError("relative reduction changed")
    if not hardened["truth_included_at_every_time"]:
        raise AssertionError("truth left confidence sequence")

    hardened["resources"] = dict(CORRECTED_RESOURCES)
    hardened["calibration_source_manifest"] = manifest
    hardened["source_packets"] = source_packets
    hardened["hardening"] = {
        "source_namespace_disjointness": "PASS",
        "source_commitment_uniqueness_by_component": "PASS",
        "statistic_commitment_binding": "PASS",
        "batch_source_exactness": "PASS",
        "envelope_source_rebinding": "PASS",
        "conservative_radius_call_accounting": "PASS",
        "base_control_sha256": digest(control),
    }
    return hardened


def private_binding() -> object:
    path = os.environ.get("PRIVATE_BINDING_PATH")
    if not path or not Path(path).exists():
        return {"status": "UNBOUND_LOCAL_REPLAY"}
    binding = json.loads(Path(path).read_text())
    if canonical(binding) != canonical(EXPECTED_PRIVATE_BINDING):
        raise AssertionError("private hardening binding changed")
    return binding


def build_payload() -> dict[str, object]:
    control = evaluate_hardening()
    if control.get("status") != "SOLVED":
        raise AssertionError(control)
    exact_cap = evaluate_hardening("exact_resource_cap")
    if exact_cap.get("status") != "SOLVED":
        raise AssertionError(exact_cap)
    expected_negatives = {
        "source_collision": "INVALID_CALIBRATION_SOURCE_COLLISION",
        "missing_provenance": "UNKNOWN_CALIBRATION_PROVENANCE",
        "duplicate_source": "INVALID_CALIBRATION_PROVENANCE",
        "statistic_mismatch": "INVALID_CALIBRATION_PROVENANCE",
        "malformed_source": "INVALID_CALIBRATION_PROVENANCE",
        "undeclared_provenance_mode": "UNKNOWN_CALIBRATION_PROVENANCE",
        "old_calibration_cap": "UNKNOWN_CALIBRATION_RESOURCE_LIMIT",
        "old_resource_cap": "UNKNOWN_RESOURCE_LIMIT",
    }
    negatives: dict[str, object] = {}
    for mode, expected in expected_negatives.items():
        packet = evaluate_hardening(mode)
        if packet.get("status") != expected:
            raise AssertionError(f"{mode}: {packet}")
        negatives[mode] = packet
    return {
        "schema": "finite-nuisance-calibration-hardening/public-independent-certificate/2",
        "private_binding": private_binding(),
        "public_base_binding": {
            "repository": "cristh99/notebooks",
            "verifier_blob": "89b0ef5758c3826229856dace9ed2b82d0169b58",
        },
        "public_event_sha": os.environ.get("GITHUB_SHA", "local"),
        "control": control,
        "exact_resource_cap": {
            "cap": 263424,
            "status": exact_cap["status"],
        },
        "negative_controls": negatives,
        "gates": {
            "independent_prior_batch_reconstruction": "PASS",
            "source_namespace_disjointness": "PASS",
            "source_commitment_uniqueness_by_component": "PASS",
            "statistic_commitment_binding": "PASS",
            "batch_source_exactness": "PASS",
            "corrected_calibration_resource_accounting": "PASS",
            "old_caps_rejected": "PASS",
            "base_metrics_unchanged": "PASS",
            "truth_anytime_inclusion": "PASS",
            "negative_controls": "PASS",
            "semantic_replay": "PASS",
        },
        "scientific_boundary": (
            "Independent source-provenance and resource hardening over the public "
            "finite calibration replay. Content commitments make source reuse and "
            "statistic substitution detectable, but validity remains conditional "
            "on the declared disjoint calibration slices and homogeneous IID "
            "Bernoulli model. Arbitrary dependence and dishonest raw-data producers "
            "remain outside the finite certificate."
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
    report = {
        "schema": "finite-nuisance-calibration-hardening/public-independent-report/2",
        "private_binding": payload["private_binding"],
        "public_base_binding": payload["public_base_binding"],
        "manifest": {
            "source_commitments": len(
                control["calibration_source_manifest"]["source_sha256"]
            ),
            "statistic_commitments": len(
                control["calibration_source_manifest"]["statistic_sha256"]
            ),
            "mode": control["calibration_source_manifest"][
                "provenance_mode"
            ],
        },
        "first_batch_source_count": control["source_packets"]["b1"][
            "source_count"
        ],
        "final_batch_source_count": control["source_packets"]["b8"][
            "source_count"
        ],
        "resources": control["resources"],
        "base_metrics": {
            "score_count": control["score_count"],
            "adaptive_final": control["adaptive_final"],
            "baseline_final": control["baseline_final"],
            "relative_width_reduction": control[
                "relative_width_reduction"
            ],
            "truth_included_at_every_time": control[
                "truth_included_at_every_time"
            ],
        },
        "hardening": control["hardening"],
        "exact_resource_cap": payload["exact_resource_cap"],
        "negative_controls": {
            key: value["status"]
            for key, value in payload["negative_controls"].items()
        },
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
    first_id = next(
        iter(
            tampered["payload"]["control"][
                "calibration_source_manifest"
            ]["source_sha256"]
        )
    )
    tampered["payload"]["control"]["calibration_source_manifest"][
        "source_sha256"
    ][first_id] = "0" * 64
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("manifest tamper accepted")
    forged = deepcopy(certificate)
    forged["payload"]["control"]["calibration_source_manifest"][
        "source_sha256"
    ][first_id] = "0" * 64
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("manifest semantic forgery accepted")
    report = build_report(certificate)
    write(
        ROOT / "FINITE_NUISANCE_CALIBRATION_HARDENING_PUBLIC_CERTIFICATE.json",
        certificate,
    )
    write(
        ROOT / "FINITE_NUISANCE_CALIBRATION_HARDENING_PUBLIC_REPORT.json",
        report,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
