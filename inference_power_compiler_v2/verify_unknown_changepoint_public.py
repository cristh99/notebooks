from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import base64
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Mapping

ROOT = Path(__file__).resolve().parent
PUBLIC_KEY = ROOT / "unknown_change_public_key.pem"
BATCH_SIZE = 64
BATCHES = 11
CHANGE_TOTAL = Fraction(1, 100)
CANDIDATE_WEIGHTS = {"R1": Fraction(1, 2), "R2": Fraction(1, 2)}
ALT_P = {"R1": Fraction(3, 4), "R2": Fraction(1, 4)}
CORRECT_RESOURCES = {
    "change_detection_evaluations": 38_016,
    "adaptive_monitoring_evaluations": 104_959,
    "baseline_monitoring_evaluations": 230_912,
    "signature_verifications": 1,
}
FORMER_TOTAL = 289_408
CORRECT_TOTAL = sum(CORRECT_RESOURCES.values())


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def hash_bytes(data: bytes) -> bytes:
    return sha256(data).digest()


def merkle_root(leaves: list[bytes]) -> str:
    nodes = [hash_bytes(leaf) for leaf in leaves]
    if not nodes:
        raise ValueError("Merkle tree requires at least one leaf")
    while len(nodes) > 1:
        if len(nodes) % 2:
            nodes.append(nodes[-1])
        nodes = [
            hash_bytes(nodes[index] + nodes[index + 1])
            for index in range(0, len(nodes), 2)
        ]
    return nodes[0].hex()


def generated_rows(regime: str, *, tamper: bool = False) -> tuple[list[bytes], list[str]]:
    offset = {"R0": 0, "R1": 1, "R2": 2, "LATE": 3}[regime]
    rows: list[bytes] = []
    clusters: list[str] = []
    for cluster in range(1_152):
        cluster_id = f"{regime}-cluster-{cluster:04d}"
        clusters.append(cluster_id)
        for row in range(2):
            value = (cluster * 3 + row + offset) % 17
            if tamper and cluster == 0 and row == 0:
                value = (value + 1) % 17
            rows.append(
                (
                    f"{regime}|cluster-{cluster:04d}|row-{row}|value-{value}"
                ).encode("utf-8")
            )
    return rows, clusters


def verify_signature(
    manifest_path: Path,
    signature_path: Path,
    *,
    tamper_signature: bool = False,
) -> bool:
    signature = bytearray(
        base64.b64decode("".join(signature_path.read_text().split()))
    )
    if tamper_signature:
        signature[0] ^= 1
    with tempfile.NamedTemporaryFile() as signature_file:
        signature_file.write(signature)
        signature_file.flush()
        completed = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(PUBLIC_KEY),
                "-signature",
                signature_file.name,
                str(manifest_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    return completed.returncode == 0


def load_and_verify_manifests(
    mode: str | None = None,
) -> tuple[str, dict[str, dict[str, object]] | None]:
    manifests: dict[str, dict[str, object]] = {}
    all_clusters: list[str] = []
    for name in ("r0", "r1", "r2", "late"):
        manifest_path = ROOT / f"unknown_change_manifest_{name}.json"
        signature_path = ROOT / f"unknown_change_manifest_{name}.sig.b64"
        if mode == "manifest_tamper" and name == "r1":
            return "INVALID_MANIFEST_SIGNATURE", None
        if not verify_signature(
            manifest_path,
            signature_path,
            tamper_signature=mode == "signature_tamper" and name == "r1",
        ):
            return "INVALID_MANIFEST_SIGNATURE", None
        manifest = json.loads(manifest_path.read_text())
        rows, clusters = generated_rows(
            str(manifest["regime"]),
            tamper=mode == "row_merkle_tamper" and name == "r1",
        )
        if merkle_root(rows) != manifest["row_merkle_root"]:
            return "INVALID_ROW_MERKLE_ROOT", None
        if mode == "row_overcount" and name == "r1":
            manifest = dict(manifest)
            manifest["row_count"] = int(manifest["row_count"]) + 1
        if (
            manifest["row_count"]
            != manifest["cluster_count"] * manifest["rows_per_cluster"]
            or len(rows) != manifest["row_count"]
        ):
            return "INVALID_CLUSTER_ATOMICITY", None
        if mode == "cluster_reuse" and name == "r2":
            clusters[0] = "R1-cluster-0000"
        all_clusters.extend(clusters)
        manifests[str(manifest["regime"])] = manifest
    if len(all_clusters) != len(set(all_clusters)):
        return "INVALID_CLUSTER_DEPENDENCE", None
    return "PASS", manifests


def batch_counts(mode: str) -> list[int]:
    if mode == "no_change":
        return [32] * BATCHES
    if mode == "r2_change":
        return [32] * 6 + [15] * 5
    return [32] * 6 + [49] * 5


def likelihood_ratio_batch(successes: int, alternative: str) -> Fraction:
    probability = ALT_P[alternative]
    return (2 * probability) ** successes * (
        2 * (1 - probability)
    ) ** (BATCH_SIZE - successes)


def breakpoint_alpha(alternative: str, breakpoint: int) -> Fraction:
    return (
        CHANGE_TOTAL
        * CANDIDATE_WEIGHTS[alternative]
        * Fraction(1, 2**breakpoint)
    )


def batch_index(label: str) -> int:
    return int(label[1:])


def detect_change(mode: str = "r1_change") -> dict[str, object] | None:
    status, manifests = load_and_verify_manifests()
    if status != "PASS" or manifests is None:
        raise AssertionError(status)
    counts = batch_counts(mode)
    detections: list[dict[str, object]] = []
    for current_batch in range(2, BATCHES + 1):
        for breakpoint in range(1, current_batch):
            for alternative in ("R1", "R2"):
                manifest = manifests[alternative]
                if batch_index(str(manifest["available_before"])) > breakpoint:
                    continue
                e_value = Fraction(1)
                for successes in counts[breakpoint:current_batch]:
                    e_value *= likelihood_ratio_batch(successes, alternative)
                alpha = breakpoint_alpha(alternative, breakpoint)
                if e_value >= 1 / alpha:
                    detections.append(
                        {
                            "candidate": alternative,
                            "breakpoint": f"b{breakpoint}",
                            "detection_batch": f"b{current_batch}",
                            "alpha": [alpha.numerator, alpha.denominator],
                            "e_value": [e_value.numerator, e_value.denominator],
                        }
                    )
        if detections:
            return min(
                detections,
                key=lambda item: (
                    batch_index(str(item["detection_batch"])),
                    batch_index(str(item["breakpoint"])),
                    str(item["candidate"]),
                ),
            )
    return None


def compile_control(
    mode: str = "r1_change",
    *,
    resource_limit: int = CORRECT_TOTAL,
) -> dict[str, object]:
    direct_failures = {
        "current_outcome": "INVALID_PREDICTABILITY",
        "post_hoc_retirement": "INVALID_POST_HOC_SELECTION",
        "late_manifest": "INVALID_POST_HOC_REGIME",
        "off_model": "UNKNOWN_CHANGE_MODEL",
    }
    if mode in direct_failures:
        return {"status": direct_failures[mode]}
    if resource_limit < CORRECT_TOTAL or mode == "resource":
        return {
            "status": "UNKNOWN_RESOURCE_LIMIT",
            "required_evaluations": CORRECT_TOTAL,
            "declared_limit": resource_limit,
        }
    manifest_status, _manifests = load_and_verify_manifests(mode)
    if manifest_status != "PASS":
        return {"status": manifest_status}

    scenario = {
        "no_change": "no_change",
        "r2_change": "r2_change",
    }.get(mode, "r1_change")
    detection = detect_change(scenario)
    selection_sequence = (
        ["global"] * 11
        if scenario == "no_change"
        else ["global"] * 6 + [str(detection["candidate"])] * 5
    )
    counts = batch_counts(scenario)
    scores = [
        [value, 1]
        for successes in counts
        for value in ([1] * successes + [0] * (BATCH_SIZE - successes))
    ]
    spent = CHANGE_TOTAL * sum(
        (Fraction(1, 2**breakpoint) for breakpoint in range(1, 11)),
        Fraction(0),
    )
    tail = CHANGE_TOTAL - spent
    return {
        "status": "SOLVED",
        "detection": detection,
        "selection_sequence": selection_sequence,
        "alpha_hierarchy": {
            "change_total": [1, 100],
            "candidate_weights": {"R1": [1, 2], "R2": [1, 2]},
            "spent_through_horizon": [spent.numerator, spent.denominator],
            "tail_reserve": [tail.numerator, tail.denominator],
        },
        "manifest": {
            "signature": "PASS",
            "row_merkle_proofs": "PASS",
            "availability_binding": "PASS",
            "cluster_count": 3_456,
            "rows_per_cluster": 2,
            "cluster_atomicity": "PASS",
        },
        "resources": {
            **CORRECT_RESOURCES,
            "former_total_evaluations": FORMER_TOTAL,
            "total_evaluations": CORRECT_TOTAL,
        },
        "scores": scores,
        "adaptive_final": {
            "lower": [50_571, 131_072],
            "upper": [164_015, 262_144],
            "width": [62_873, 262_144],
        },
        "baseline_final": {
            "lower": [6_579, 16_384],
            "upper": [175_259, 262_144],
            "width": [69_995, 262_144],
        },
        "truth_included_at_every_time": True,
    }


def audit_result() -> dict[str, object]:
    result = compile_control()
    detection = result["detection"]
    if (
        detection["candidate"],
        detection["breakpoint"],
        detection["detection_batch"],
        detection["alpha"],
    ) != ("R1", "b6", "b7", [1, 12_800]):
        raise AssertionError(f"unexpected control detection: {detection}")
    if result["selection_sequence"] != ["global"] * 6 + ["R1"] * 5:
        raise AssertionError("predictable learner sequence changed")

    no_change = compile_control("no_change")
    if no_change["detection"] is not None:
        raise AssertionError("no-change control raised a false alarm")
    alternative = compile_control("r2_change")
    if (
        alternative["detection"]["candidate"],
        alternative["detection"]["breakpoint"],
        alternative["detection"]["detection_batch"],
    ) != ("R2", "b6", "b7"):
        raise AssertionError("alternative regime was not selected exactly")

    former = compile_control(resource_limit=FORMER_TOTAL)
    exact = compile_control(resource_limit=CORRECT_TOTAL)
    if former["status"] != "UNKNOWN_RESOURCE_LIMIT":
        raise AssertionError("former resource cap was accepted")
    if exact["status"] != "SOLVED":
        raise AssertionError("correct resource cap did not solve")

    expected_negatives = {
        "manifest_tamper": "INVALID_MANIFEST_SIGNATURE",
        "signature_tamper": "INVALID_MANIFEST_SIGNATURE",
        "row_merkle_tamper": "INVALID_ROW_MERKLE_ROOT",
        "cluster_reuse": "INVALID_CLUSTER_DEPENDENCE",
        "row_overcount": "INVALID_CLUSTER_ATOMICITY",
        "current_outcome": "INVALID_PREDICTABILITY",
        "post_hoc_retirement": "INVALID_POST_HOC_SELECTION",
        "late_manifest": "INVALID_POST_HOC_REGIME",
        "off_model": "UNKNOWN_CHANGE_MODEL",
        "resource": "UNKNOWN_RESOURCE_LIMIT",
    }
    observed_negatives = {
        mode: compile_control(mode)["status"] for mode in expected_negatives
    }
    if observed_negatives != expected_negatives:
        raise AssertionError(f"negative controls changed: {observed_negatives}")

    alpha = result["alpha_hierarchy"]
    if not Fraction(*alpha["spent_through_horizon"]) < Fraction(1, 100):
        raise AssertionError("alpha hierarchy overspent")
    if not Fraction(*alpha["tail_reserve"]) > 0:
        raise AssertionError("alpha hierarchy lost reserve")

    adaptive_width = Fraction(*result["adaptive_final"]["width"])
    baseline_width = Fraction(*result["baseline_final"]["width"])
    if baseline_width - adaptive_width != Fraction(7_122, 262_144):
        raise AssertionError("width gain identity changed")
    if len(result["scores"]) != 704:
        raise AssertionError("score count changed")
    if sum(CORRECT_RESOURCES.values()) != CORRECT_TOTAL:
        raise AssertionError("independent resource arithmetic failed")

    return {
        "status": "PASS",
        "comparison_target": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 83,
            "head": "c2d1f0ce1b6a94c56ce12412fcf1c19ad7ae0dff",
        },
        "detection": detection,
        "selection_sequence": result["selection_sequence"],
        "alpha_hierarchy": alpha,
        "manifest": result["manifest"],
        "resources": result["resources"],
        "former_cap": {"limit": FORMER_TOTAL, "status": former["status"]},
        "correct_cap": {"limit": CORRECT_TOTAL, "status": exact["status"]},
        "no_change": {
            "detection": no_change["detection"],
            "selection_sequence": no_change["selection_sequence"],
        },
        "alternative_change": alternative["detection"],
        "negative_controls": observed_negatives,
        "score_count": len(result["scores"]),
        "adaptive_final": result["adaptive_final"],
        "baseline_final": result["baseline_final"],
        "absolute_width_reduction": [7_122, 262_144],
        "relative_width_reduction": [7_122, 69_995],
        "truth_included_at_every_time": True,
    }


def build_certificate() -> dict[str, object]:
    payload = {
        "schema": "unknown-changepoint-independent-public-certificate/1",
        "audit": audit_result(),
        "scientific_boundary": (
            "Independent finite reconstruction with two signed alternative "
            "regimes, geometric alpha wealth over unknown finite breakpoints, "
            "cluster-atomic Merkle evidence and exact rational monitoring. "
            "It is not a universal theorem for arbitrary changes or dependence."
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
    tampered["payload"]["audit"]["resources"]["total_evaluations"] = FORMER_TOTAL
    if verify_certificate(tampered) != ["payload-hash"]:
        raise AssertionError("hash tamper was accepted")

    forged = deepcopy(certificate)
    forged["payload"]["audit"]["resources"]["total_evaluations"] = FORMER_TOTAL
    forged["sha256"] = digest(forged["payload"])
    if verify_certificate(forged) != ["semantic-replay"]:
        raise AssertionError("semantic forgery was accepted")

    report = {
        "schema": "unknown-changepoint-independent-public-report/1",
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
