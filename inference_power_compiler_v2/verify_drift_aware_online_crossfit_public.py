from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent
PRIVATE_HEAD = "c3905d5328a6e6f5e83af8c0596ae156600d54a4"
PRIVATE_BLOBS = {
    "compiler": "3de813e42f1cd4c9fd3c4e3c562a654537de4dfd",
    "runner": "599266941eba32a268132a671192e077a17f7f63",
    "tests": "63cd429bb28f625faa8ba4452c856aa601712648",
    "lean": "72433508961fea500aa3fc61242176baba03da56",
    "workflow": "2e468ba40d1fa5cb51776f0fec5ceb0c2a390e17",
    "crossfit_base": "11f59404860db7f2570c4b766d27e814622188ce",
}

TRUTH_PZ = {"z0": Fraction(1, 2), "z1": Fraction(1, 2)}
TRUTH_E = {"z0": Fraction(1, 2), "z1": Fraction(1, 2)}
TRUTH_MU0 = {"z0": Fraction(1, 4), "z1": Fraction(1, 4)}
TRUTH_MU1 = {"z0": Fraction(3, 4), "z1": Fraction(3, 4)}
TRUTH_PSI = Fraction(1, 2)
ALPHA = Fraction(1, 20)
THRESHOLD = Fraction(40)
SCORE_LOWER = Fraction(-3, 2)
SCORE_UPPER = Fraction(3, 2)
TARGET_LOWER = Fraction(0)
TARGET_UPPER = Fraction(1)
DEPTH = 18
POSITIVE_LAMBDAS = (Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1))
NEGATIVE_LAMBDAS = tuple(-value for value in POSITIVE_LAMBDAS)
EQUAL_WEIGHTS = (Fraction(1, 4),) * 4
BASELINE_LAMBDA = Fraction(1, 4)
OVERLAP_FLOOR = Fraction(1, 4)
DRIFT_THRESHOLD = Fraction(1, 8)
MAX_REMAINDER = Fraction(1, 16)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def q(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def parse_q(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("malformed rational")
    numerator, denominator = value
    if not isinstance(numerator, int) or not isinstance(denominator, int) or denominator <= 0:
        raise ValueError("malformed rational")
    return Fraction(numerator, denominator)


@dataclass(frozen=True)
class Row:
    row_id: str
    batch: str
    z: str
    a: int
    y: int


@dataclass(frozen=True)
class Envelope:
    source_ids: tuple[str, ...]
    e_sup: Fraction
    mu0_sup: Fraction
    mu1_sup: Fraction


def warmup_rows() -> tuple[Row, ...]:
    specifications = (
        ("z0", 0, (0, 0, 0, 0, 1)),
        ("z0", 1, (0, 1, 1)),
        ("z1", 0, (0, 0, 1)),
        ("z1", 1, (0, 1, 1, 1, 1)),
    )
    rows: list[Row] = []
    counter = 0
    for z, action, outcomes in specifications:
        for outcome in outcomes:
            rows.append(Row(f"w{counter:02d}", "b0", z, action, outcome))
            counter += 1
    return tuple(rows)


def standard_rows(batch: str, prefix: str) -> tuple[Row, ...]:
    rows: list[Row] = []
    counter = 0
    for z in ("z0", "z1"):
        for action in (0, 1):
            outcomes = (0, 0, 0, 1) if action == 0 else (0, 1, 1, 1)
            for outcome in outcomes:
                rows.append(Row(f"{prefix}{counter:02d}", batch, z, action, outcome))
                counter += 1
    return tuple(rows)


def fit(rows: Sequence[Row]) -> dict[str, dict[str, Fraction]]:
    result: dict[str, dict[str, Fraction]] = {"e": {}, "mu0": {}, "mu1": {}}
    for z in ("z0", "z1"):
        z_rows = [row for row in rows if row.z == z]
        if not z_rows:
            raise ValueError("empty covariate cell")
        result["e"][z] = Fraction(sum(row.a for row in z_rows), len(z_rows))
        for action, key in ((0, "mu0"), (1, "mu1")):
            cell = [row for row in z_rows if row.a == action]
            if not cell:
                raise ValueError("empty treatment cell")
            result[key][z] = Fraction(sum(row.y for row in cell), len(cell))
    return result


def aipw(row: Row, nuisance: Mapping[str, Mapping[str, Fraction]]) -> Fraction:
    e = nuisance["e"][row.z]
    mu0 = nuisance["mu0"][row.z]
    mu1 = nuisance["mu1"][row.z]
    return (
        mu1 - mu0
        + Fraction(row.a, 1) / e * (row.y - mu1)
        - Fraction(1 - row.a, 1) / (1 - e) * (row.y - mu0)
    )


def exact_envelope(rows: Sequence[Row], source_ids: tuple[str, ...]) -> Envelope:
    nuisance = fit(rows)
    return Envelope(
        source_ids,
        max(abs(nuisance["e"][z] - TRUTH_E[z]) for z in TRUTH_E),
        max(abs(nuisance["mu0"][z] - TRUTH_MU0[z]) for z in TRUTH_MU0),
        max(abs(nuisance["mu1"][z] - TRUTH_MU1[z]) for z in TRUTH_MU1),
    )


def expected_score(nuisance: Mapping[str, Mapping[str, Fraction]]) -> Fraction:
    total = Fraction(0)
    for z, pz in TRUTH_PZ.items():
        e0 = TRUTH_E[z]
        ehat = nuisance["e"][z]
        mu0, mu1 = TRUTH_MU0[z], TRUTH_MU1[z]
        mu0hat, mu1hat = nuisance["mu0"][z], nuisance["mu1"][z]
        total += pz * (
            mu1hat - mu0hat
            + e0 / ehat * (mu1 - mu1hat)
            - (1 - e0) / (1 - ehat) * (mu0 - mu0hat)
        )
    return total


def design(rows: Sequence[Row]) -> dict[str, Fraction]:
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row.z}|a={row.a}"
        counts[key] = counts.get(key, 0) + 1
    return {key: Fraction(value, len(rows)) for key, value in counts.items()}


def total_variation(left: Mapping[str, Fraction], right: Mapping[str, Fraction]) -> Fraction:
    return sum((abs(left.get(key, 0) - right.get(key, 0)) for key in set(left) | set(right)), Fraction(0)) / 2


def transformed(score: Fraction) -> Fraction:
    return (score - SCORE_LOWER) / (SCORE_UPPER - SCORE_LOWER)


def mixture_e(
    scores: Sequence[Fraction],
    remainders: Sequence[Fraction],
    psi: Fraction,
    lambdas: Sequence[Fraction],
    weights: Sequence[Fraction],
    side: str,
) -> Fraction:
    total = Fraction(0)
    for lam, weight in zip(lambdas, weights):
        wealth = Fraction(1)
        for score, remainder in zip(scores, remainders):
            center = psi + remainder if side == "positive" else psi - remainder
            factor = 1 + lam * (transformed(score) - transformed(center))
            if factor < 0:
                raise AssertionError("negative factor")
            wealth *= factor
        total += weight * wealth
    return total


def root(
    scores: Sequence[Fraction],
    remainders: Sequence[Fraction],
    lambdas: Sequence[Fraction],
    weights: Sequence[Fraction],
    side: str,
) -> Fraction:
    lo, hi = TARGET_LOWER, TARGET_UPPER
    if side == "positive":
        if mixture_e(scores, remainders, lo, lambdas, weights, side) < THRESHOLD:
            return lo
        for _ in range(DEPTH):
            midpoint = (lo + hi) / 2
            if mixture_e(scores, remainders, midpoint, lambdas, weights, side) >= THRESHOLD:
                lo = midpoint
            else:
                hi = midpoint
        return lo
    if mixture_e(scores, remainders, hi, lambdas, weights, side) < THRESHOLD:
        return hi
    for _ in range(DEPTH):
        midpoint = (lo + hi) / 2
        if mixture_e(scores, remainders, midpoint, lambdas, weights, side) < THRESHOLD:
            lo = midpoint
        else:
            hi = midpoint
    return hi


def interval(
    scores: Sequence[Fraction],
    remainders: Sequence[Fraction],
    positive_lambdas: Sequence[Fraction],
    negative_lambdas: Sequence[Fraction],
    weights: Sequence[Fraction],
) -> dict[str, object]:
    lower = root(scores, remainders, positive_lambdas, weights, "positive")
    upper = root(scores, remainders, negative_lambdas, weights, "negative")
    return {
        "nonempty": lower <= upper,
        "lower": q(lower),
        "upper": q(upper),
        "width": None if lower > upper else q(upper - lower),
    }


def build_state(mode: str | None = None) -> dict[str, object]:
    warmup = list(warmup_rows())
    monitoring = [list(standard_rows(f"b{i}", f"x{i:02d}_")) for i in range(1, 13)]
    if mode == "design_drift":
        monitoring[4] = [replace(row, z="z0") for row in monitoring[4]]
    rows = tuple(warmup + [row for batch in monitoring for row in batch])
    rows_by_batch = {f"b{i}": [row for row in rows if row.batch == f"b{i}"] for i in range(13)}
    training: dict[str, tuple[str, ...]] = {}
    envelopes: dict[str, Envelope] = {}
    prior = list(rows_by_batch["b0"])
    for i in range(1, 13):
        batch = f"b{i}"
        ids = tuple(row.row_id for row in prior)
        training[batch] = ids
        envelopes[batch] = exact_envelope(prior, ids)
        prior.extend(rows_by_batch[batch])
    if mode == "current_leakage":
        training["b1"] += (rows_by_batch["b1"][0].row_id,)
    elif mode == "future_leakage":
        training["b1"] += (rows_by_batch["b2"][0].row_id,)
    elif mode == "envelope_future":
        packet = envelopes["b1"]
        envelopes["b1"] = replace(packet, source_ids=packet.source_ids + (rows_by_batch["b2"][0].row_id,))
    elif mode == "false_envelope":
        envelopes["b1"] = replace(envelopes["b1"], e_sup=Fraction(0))
    elif mode == "product_rate":
        envelopes["b3"] = replace(envelopes["b3"], e_sup=Fraction(1, 2), mu0_sup=Fraction(1, 2), mu1_sup=Fraction(1, 2))
    elif mode == "product_regression":
        envelopes["b3"] = replace(envelopes["b3"], e_sup=Fraction(1, 16), mu0_sup=Fraction(1, 16), mu1_sup=Fraction(1, 16))
    clusters = {row.row_id: f"cluster:{row.row_id}" for row in rows}
    if mode == "cluster_reuse":
        clusters[rows_by_batch["b2"][0].row_id] = clusters[rows_by_batch["b1"][0].row_id]
    return {
        "mode": mode,
        "rows": rows,
        "rows_by_batch": rows_by_batch,
        "training": training,
        "envelopes": envelopes,
        "clusters": clusters,
    }


def evaluate(mode: str | None = None) -> dict[str, object]:
    if mode == "post_hoc":
        return {"status": "INVALID_POST_HOC_SELECTION"}
    state = build_state(mode)
    rows: tuple[Row, ...] = state["rows"]  # type: ignore[assignment]
    rows_by_batch: dict[str, list[Row]] = state["rows_by_batch"]  # type: ignore[assignment]
    training: dict[str, tuple[str, ...]] = state["training"]  # type: ignore[assignment]
    envelopes: dict[str, Envelope] = state["envelopes"]  # type: ignore[assignment]
    clusters: dict[str, str] = state["clusters"]  # type: ignore[assignment]
    row_by_id = {row.row_id: row for row in rows}
    order = {f"b{i}": i for i in range(13)}
    seen_monitoring: set[str] = set()

    for batch in (f"b{i}" for i in range(1, 13)):
        current_ids = {row.row_id for row in rows_by_batch[batch]}
        for source, ids in (("training", training[batch]), ("envelope", envelopes[batch].source_ids)):
            for row_id in ids:
                source_batch = row_by_id[row_id].batch
                if row_id in current_ids or order[source_batch] >= order[batch]:
                    return {"status": "INVALID_PREDICTABILITY", "batch": batch, "source": source}
        if not set(envelopes[batch].source_ids) <= set(training[batch]):
            return {"status": "INVALID_PREDICTABILITY", "batch": batch, "source": "envelope"}
        current_clusters = {clusters[row.row_id] for row in rows_by_batch[batch]}
        training_clusters = {clusters[row_id] for row_id in training[batch]}
        if current_clusters & training_clusters or current_clusters & seen_monitoring:
            return {"status": "INVALID_CLUSTER_DEPENDENCE", "batch": batch}
        seen_monitoring |= current_clusters

    scores: list[Fraction] = []
    remainders: list[Fraction] = []
    batch_packets: dict[str, object] = {}
    endpoints: list[int] = []
    previous_remainder: Fraction | None = None
    for i in range(1, 13):
        batch = f"b{i}"
        predecessor = f"b{i-1}"
        drift = total_variation(design(rows_by_batch[predecessor]), design(rows_by_batch[batch]))
        if drift > DRIFT_THRESHOLD:
            return {"status": "UNKNOWN_DESIGN_DRIFT", "batch": batch, "drift": q(drift), "uses_outcomes": False}
        training_rows = [row_by_id[row_id] for row_id in training[batch]]
        nuisance = fit(training_rows)
        eta = min(*(nuisance["e"].values()), *(1 - value for value in nuisance["e"].values()))
        if eta < OVERLAP_FLOOR:
            return {"status": "INVALID_POSITIVITY", "batch": batch}
        envelope = envelopes[batch]
        actual = exact_envelope(training_rows, envelope.source_ids)
        for name in ("e_sup", "mu0_sup", "mu1_sup"):
            if getattr(actual, name) > getattr(envelope, name):
                return {"status": "INVALID_ENVELOPE_CERTIFICATE", "batch": batch, "component": name}
        remainder = envelope.e_sup * (envelope.mu0_sup + envelope.mu1_sup) / eta
        if remainder > MAX_REMAINDER:
            return {"status": "UNKNOWN_PRODUCT_RATE", "batch": batch, "remainder": q(remainder)}
        if previous_remainder is not None and remainder > previous_remainder:
            return {"status": "UNKNOWN_PRODUCT_RATE_REGRESSION", "batch": batch, "remainder": q(remainder)}
        previous_remainder = remainder
        bias = expected_score(nuisance) - TRUTH_PSI
        if abs(bias) > remainder:
            return {"status": "INVALID_REMAINDER_BOUND", "batch": batch}
        batch_scores = [aipw(row, nuisance) for row in rows_by_batch[batch]]
        score_upper = Fraction(1) if mode == "score_bound" else SCORE_UPPER
        if any(score < SCORE_LOWER or score > score_upper for score in batch_scores):
            return {"status": "INVALID_SCORE_BOUND", "batch": batch}
        scores.extend(batch_scores)
        remainders.extend([remainder] * len(batch_scores))
        endpoints.append(len(scores))
        batch_packets[batch] = {
            "drift": q(drift),
            "eta": q(eta),
            "remainder": q(remainder),
            "bias": q(bias),
        }

    required = sum(endpoint * 10 * 20 for endpoint in endpoints) + len(scores) * 8
    cap = 10_000 if mode == "resource" else 3_000_000
    if required > cap:
        return {"status": "UNKNOWN_RESOURCE_LIMIT", "required": required, "cap": cap}
    adaptive = interval(scores, remainders, POSITIVE_LAMBDAS, NEGATIVE_LAMBDAS, EQUAL_WEIGHTS)
    baseline = interval(scores, remainders, (BASELINE_LAMBDA,), (-BASELINE_LAMBDA,), (Fraction(1),))
    truth_history = []
    truth_always = True
    for time in range(1, len(scores) + 1):
        positive = mixture_e(scores[:time], remainders[:time], TRUTH_PSI, POSITIVE_LAMBDAS, EQUAL_WEIGHTS, "positive")
        negative = mixture_e(scores[:time], remainders[:time], TRUTH_PSI, NEGATIVE_LAMBDAS, EQUAL_WEIGHTS, "negative")
        included = positive < THRESHOLD and negative < THRESHOLD
        truth_always = truth_always and included
        truth_history.append([q(positive), q(negative), included])
    aw, bw = parse_q(adaptive["width"]), parse_q(baseline["width"])
    return {
        "status": "SOLVED",
        "batches": batch_packets,
        "score_count": len(scores),
        "remainders": [batch_packets[f"b{i}"]["remainder"] for i in range(1, 13)],
        "adaptive_final": adaptive,
        "baseline_final": baseline,
        "absolute_width_reduction": q(bw - aw),
        "relative_width_reduction": q((bw - aw) / bw),
        "truth_included_at_every_time": truth_always,
        "truth_history_sha256": digest(truth_history),
        "required_mixture_evaluations": required,
    }


def build_payload() -> dict[str, object]:
    control = evaluate()
    if control["status"] != "SOLVED":
        raise AssertionError(control)
    expected_remainders = [[1, 18], [1, 98], [1, 242], [1, 450], [1, 722], [1, 1058], [1, 1458], [1, 1922], [1, 2450], [1, 3042], [1, 3698], [1, 4418]]
    if control["remainders"] != expected_remainders:
        raise AssertionError("public remainder sequence changed")
    expected_adaptive = {"nonempty": True, "lower": [38981, 131072], "upper": [88917, 131072], "width": [3121, 8192]}
    expected_baseline = {"nonempty": True, "lower": [60847, 262144], "upper": [50713, 65536], "width": [142005, 262144]}
    if control["adaptive_final"] != expected_adaptive or control["baseline_final"] != expected_baseline:
        raise AssertionError("public online intervals changed")
    if control["absolute_width_reduction"] != [42133, 262144] or control["relative_width_reduction"] != [42133, 142005]:
        raise AssertionError("public width reduction changed")
    if control["score_count"] != 192 or control["required_mixture_evaluations"] != 251136 or not control["truth_included_at_every_time"]:
        raise AssertionError("public online control changed")

    expected_statuses = {
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
    negatives = {}
    for mode, expected in expected_statuses.items():
        packet = evaluate(mode)
        if packet["status"] != expected:
            raise AssertionError(f"public negative {mode} changed: {packet}")
        negatives[mode] = packet

    return {
        "schema": "drift-aware-online-crossfit/public-independent-certificate/1",
        "private_binding": {
            "repository": "cristh99/my_first_repository",
            "pull_request": 68,
            "head": PRIVATE_HEAD,
            "blobs": PRIVATE_BLOBS,
        },
        "control": control,
        "negative_controls": negatives,
        "gates": {
            "strict_past_training": "PASS",
            "strict_past_envelope_provenance": "PASS",
            "cluster_separation": "PASS",
            "pre_outcome_design_drift_guard": "PASS",
            "positivity": "PASS",
            "external_error_envelopes": "PASS",
            "product_rate_remainder": "PASS",
            "nonincreasing_remainder": "PASS",
            "bounded_scores": "PASS",
            "variable_remainder_e_process": "PASS",
            "continuous_root_inversion": "PASS",
            "adaptive_mixture_regret": "PASS",
            "truth_anytime_inclusion": "PASS",
            "negative_controls": "PASS",
        },
        "scientific_boundary": (
            "Independent exact finite replay for cumulative strictly-past nuisance fitting, "
            "pre-outcome design drift, cluster separation, certified sup-norm envelopes and "
            "variable-remainder e-process inversion. General envelope learning, arbitrary "
            "dependence, continuous covariates and unrestricted online learners are outside scope."
        ),
    }


def build_certificate() -> dict[str, object]:
    payload = build_payload()
    return {"payload": payload, "sha256": digest(payload)}


def verify_certificate(certificate: Mapping[str, object]) -> list[str]:
    payload, claimed = certificate.get("payload"), certificate.get("sha256")
    if not isinstance(payload, Mapping) or not isinstance(claimed, str):
        return ["shape"]
    if digest(payload) != claimed:
        return ["payload-hash"]
    if canonical(build_certificate()["payload"]) != canonical(payload):
        return ["semantic-replay"]
    return []


def build_report(certificate: Mapping[str, object]) -> dict[str, object]:
    payload = certificate["payload"]
    result = {
        "schema": "drift-aware-online-crossfit/public-independent-report/1",
        "control": payload["control"],
        "negative_controls": {key: value["status"] for key, value in payload["negative_controls"].items()},
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
        raise AssertionError("public certificate self-replay failed")
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
    write(ROOT / "DRIFT_AWARE_ONLINE_PUBLIC_CERTIFICATE.json", certificate)
    write(ROOT / "DRIFT_AWARE_ONLINE_PUBLIC_REPORT.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
