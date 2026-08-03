import {
  PERMUTATION_SEED,
  digest,
} from "./node_policy.mjs";

function safeDiv(a, b) {
  return b ? a / b : null;
}

export function metrics(rows) {
  const eligible = rows.filter(
    (row) => row.observable,
  );
  const clean = eligible.filter(
    (row) => !row.gold_error,
  );
  const errors = eligible.filter(
    (row) => row.gold_error,
  );
  const tp = errors.filter(
    (row) => row.decision === "ERROR",
  ).length;
  const fn = errors.length - tp;
  const tn = clean.filter(
    (row) => row.decision === "CLEAN",
  ).length;
  const fp = clean.filter(
    (row) => row.decision === "ERROR",
  ).length;
  const abstainClean = clean.filter(
    (row) => row.decision === "ABSTAIN",
  ).length;
  const abstainError = errors.filter(
    (row) => row.decision === "ABSTAIN",
  ).length;
  const precision = safeDiv(
    tp,
    tp + fp,
  );
  const recall = safeDiv(
    tp,
    tp + fn,
  );
  const specificity = safeDiv(
    tn,
    tn + fp,
  );
  const fpr = safeDiv(
    fp,
    fp + tn,
  );
  const f1 =
    precision !== null
    && recall !== null
    && precision + recall
      ? (
        2 * precision * recall
        / (precision + recall)
      )
      : null;

  const familyTotal = new Map();
  const familyHit = new Map();
  for (const row of errors) {
    const family = String(
      row.family ?? "",
    );
    familyTotal.set(
      family,
      (familyTotal.get(family) ?? 0) + 1,
    );
    if (row.decision === "ERROR") {
      familyHit.set(
        family,
        (familyHit.get(family) ?? 0) + 1,
      );
    }
  }
  const familyRecall = {};
  for (
    const family
    of [...familyTotal.keys()].sort()
  ) {
    familyRecall[family] = safeDiv(
      familyHit.get(family) ?? 0,
      familyTotal.get(family),
    );
  }
  return {
    eligible_rows: eligible.length,
    clean_rows: clean.length,
    error_rows: errors.length,
    true_positive: tp,
    false_negative: fn,
    true_negative: tn,
    false_positive: fp,
    clean_abstentions: abstainClean,
    error_abstentions: abstainError,
    coverage: safeDiv(
      eligible.length
        - abstainClean
        - abstainError,
      eligible.length,
    ),
    accuracy: safeDiv(
      tp + tn,
      eligible.length,
    ),
    precision,
    recall,
    specificity,
    false_positive_rate: fpr,
    f1,
    family_recall: familyRecall,
  };
}

export function permutationControl(rows) {
  const eligible = rows
    .filter((row) => row.observable)
    .map((row) => ({...row}))
    .sort((a, b) => {
      const left = digest(
        `${a.instance_id}|${PERMUTATION_SEED}`,
      );
      const right = digest(
        `${b.instance_id}|${PERMUTATION_SEED}`,
      );
      return left.localeCompare(right);
    });
  const decisions = eligible.map(
    (row) => row.decision,
  );
  if (decisions.length) {
    decisions.push(decisions.shift());
  }
  const permuted = eligible.map(
    (row, index) => ({
      ...row,
      decision: decisions[index],
    }),
  );
  return {
    seed: PERMUTATION_SEED,
    metrics: metrics(permuted),
  };
}

export function directProvenance(caseValue) {
  const values = caseValue.values ?? {};
  const provenance =
    caseValue.provenance ?? {};
  const valueKeys = Object.keys(
    values,
  ).sort();
  const sourceKeys = Object.keys(
    provenance,
  ).sort();
  if (
    JSON.stringify(valueKeys)
    !== JSON.stringify(sourceKeys)
  ) {
    return false;
  }
  return valueKeys.every((key) => {
    const source = provenance[key] ?? {};
    return (
      source.accn === caseValue.accession
      && ["10-K", "10-K/A"].includes(
        source.form,
      )
      && Boolean(source.concept)
      && Boolean(source.filed)
      && Boolean(source.end)
      && Number(source.value)
        === Number(values[key])
    );
  });
}
