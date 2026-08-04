import crypto from "node:crypto";

import {
  BEFORE,
  PASS_DELTA,
  POLICY_ID,
  SCHEMA,
  canonical,
  fileSha256,
  rowFromInstance,
  stripPredictionHash,
} from "./node_policy.mjs";
import {
  directProvenance,
  metrics,
  permutationControl,
} from "./node_metrics.mjs";

export function verify(
  report,
  casesPath,
  cases,
  instances,
  exactRows,
  roundedRows,
) {
  const payload = report.payload ?? {};
  const recomputedExact = instances.map(
    (instance) =>
      rowFromInstance(instance, false),
  );
  const recomputedRounded = instances.map(
    (instance) =>
      rowFromInstance(instance, true),
  );
  const exact = metrics(recomputedExact);
  const rounded = metrics(recomputedRounded);
  const permutation = permutationControl(
    recomputedExact,
  );
  const relationCounts = cases.map(
    (caseValue) =>
      caseValue.enabled_relation_ids?.length
      ?? 0,
  );
  const sics = new Set(
    cases
      .map(
        (caseValue) =>
          String(caseValue.sic ?? ""),
      )
      .filter(Boolean),
  );
  const expectedChecks = {
    frozen_universe_50:
      payload.protocol?.universe_size === 50,
    official_sec_only: cases.every(
      (caseValue) =>
        String(
          caseValue.source_url ?? "",
        ).startsWith(
          "https://data.sec.gov/",
        ),
    ),
    all_values_directly_reported:
      cases.every(directProvenance),
    same_accession_per_case:
      cases.every((caseValue) =>
        Object.values(
          caseValue.provenance ?? {},
        ).every(
          (source) =>
            source.accn
            === caseValue.accession,
        ),
      ),
    eligible_companies_at_least_40:
      cases.length >= 40,
    companies_with_two_relations_at_least_25:
      relationCounts.filter(
        (count) => count >= 2,
      ).length >= 25,
    total_relations_at_least_80:
      relationCounts.reduce(
        (sum, count) => sum + count,
        0,
      ) >= 80,
    sic_breadth_at_least_20:
      sics.size >= 20,
    exact_zero_fpr:
      exact.false_positive_rate === 0,
    exact_precision_one:
      exact.precision === 1,
    exact_recall_at_least_90pct:
      (exact.recall ?? 0) >= 0.90,
    exact_full_coverage:
      exact.coverage === 1,
    rounded_zero_fpr:
      rounded.false_positive_rate === 0,
    rounded_recall_at_least_85pct:
      (rounded.recall ?? 0) >= 0.85,
    permutation_worse:
      (
        permutation.metrics
          .false_positive_rate
        ?? 0
      )
        > (
          exact.false_positive_rate
          ?? 0
        )
      || (
        permutation.metrics.recall
        ?? 0
      )
        < (exact.recall ?? 0),
  };
  const passed = Object.values(
    expectedChecks,
  ).every(Boolean);
  const expectedScore =
    BEFORE + (passed ? PASS_DELTA : 0);

  const gates = {
    report_hash:
      typeof report.payload_canonical
        === "string"
      && crypto
        .createHash("sha256")
        .update(
          report.payload_canonical,
          "utf8",
        )
        .digest("hex")
        === report.sha256,
    payload_matches_canonical:
      typeof report.payload_canonical
        === "string"
      && canonical(
        JSON.parse(
          report.payload_canonical,
        ),
      )
        === canonical(payload),
    schema: payload.schema === SCHEMA,
    policy:
      payload.policy_id === POLICY_ID,
    cases_hash:
      payload.cohort
        ?.cases_file_sha256
      === fileSha256(casesPath),
    exact_rows_reimplemented:
      canonical(
        recomputedExact.map(
          stripPredictionHash,
        ),
      )
      === canonical(
        exactRows.map(
          stripPredictionHash,
        ),
      ),
    rounded_rows_reimplemented:
      canonical(
        recomputedRounded.map(
          stripPredictionHash,
        ),
      )
      === canonical(
        roundedRows.map(
          stripPredictionHash,
        ),
      ),
    exact_metrics:
      canonical(exact)
      === canonical(
        payload.exact_metrics,
      ),
    rounded_metrics:
      canonical(rounded)
      === canonical(
        payload.rounded_metrics,
      ),
    permutation:
      canonical(permutation)
      === canonical(
        payload.permutation_control,
      ),
    gate_checks:
      canonical(expectedChecks)
      === canonical(
        payload.gate_checks,
      ),
    status:
      payload.status
      === (
        passed
          ? "PASS_SEC_DIRECT_BREADTH"
          : "OPEN_SEC_DIRECT_BREADTH"
      ),
    score:
      payload.absolute_score?.before
        === BEFORE
      && payload.absolute_score?.after
        === expectedScore
      && payload.absolute_score?.delta
        === expectedScore - BEFORE,
    boundary:
      String(
        payload.boundary ?? "",
      ).includes("does not")
      && String(
        payload.absolute_score
          ?.boundary
          ?? "",
      ).includes("no world-SOTA"),
  };
  const valid = Object.values(
    gates,
  ).every(Boolean);
  const totalRelations =
    relationCounts.reduce(
      (sum, count) => sum + count,
      0,
    );
  const receiptPayload = {
    schema:
      "fin-abs-001b/node-receipt/1",
    valid,
    failed_gates: Object.entries(
      gates,
    )
      .filter(([, value]) => !value)
      .map(([key]) => key),
    report_sha256: report.sha256,
    exact_metrics: exact,
    rounded_metrics: rounded,
    permutation_control: permutation,
    cohort: {
      eligible_companies: cases.length,
      companies_with_two_relations:
        relationCounts.filter(
          (count) => count >= 2,
        ).length,
      total_relations: totalRelations,
      sic_count: sics.size,
      cases_file_sha256:
        fileSha256(casesPath),
    },
    gate_checks: expectedChecks,
    absolute_score: expectedScore,
  };
  const receiptCanonical = canonical(
    receiptPayload,
  );
  return {
    payload: receiptPayload,
    sha256: crypto
      .createHash("sha256")
      .update(
        receiptCanonical,
        "utf8",
      )
      .digest("hex"),
  };
}
