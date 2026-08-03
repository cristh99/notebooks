import fs from "node:fs";
import crypto from "node:crypto";

export const POLICY_ID =
  "FIN-ABS-001B-SEC-DIRECT-RELATIONAL-VERIFIER-V1";
export const SCHEMA =
  "fin-abs-001b/sec-direct-breadth/1";
export const BEFORE = 423;
export const PASS_DELTA = 8;
export const RELATIVE_TOLERANCE = 0.001;
export const ABSOLUTE_TOLERANCE = 2.0;
export const PERMUTATION_SEED =
  "FIN-ABS-001B-PERMUTATION-V1";

export function canonical(value) {
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(",")}]`;
  }
  if (
    value !== null
    && typeof value === "object"
  ) {
    return `{${Object.keys(value)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${canonical(
            value[key],
          )}`,
      )
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function digest(value) {
  return crypto
    .createHash("sha256")
    .update(canonical(value), "utf8")
    .digest("hex");
}

export function fileSha256(path) {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(path))
    .digest("hex");
}

export function readJsonl(path) {
  return fs
    .readFileSync(path, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

export function tolerance(observed, expected) {
  return Math.max(
    ABSOLUTE_TOLERANCE,
    RELATIVE_TOLERANCE
      * Math.max(
        Math.abs(observed),
        Math.abs(expected),
        1,
      ),
  );
}

export function relationSpecs(
  values,
  provenance,
) {
  const relations = [];
  const has = (...keys) =>
    keys.every((key) =>
      Object.prototype.hasOwnProperty.call(
        values,
        key,
      ),
    );

  if (has("assets", "liabilities_and_equity")) {
    relations.push({
      relation_id: "BS_DIRECT_TOTAL",
      family: "AE",
      observed_key: "assets",
      terms: [["liabilities_and_equity", 1]],
    });
  }
  if (has("assets", "liabilities", "equity")) {
    relations.push({
      relation_id: "BS_COMPONENT_IDENTITY",
      family: "AE",
      observed_key: "assets",
      terms: [
        ["liabilities", 1],
        ["equity", 1],
      ],
    });
  }
  if (
    has(
      "gross_profit",
      "revenue",
      "cost_of_revenue",
    )
  ) {
    relations.push({
      relation_id: "IS_GROSS_PROFIT",
      family: "AE",
      observed_key: "gross_profit",
      terms: [
        ["revenue", 1],
        ["cost_of_revenue", -1],
      ],
      absolute_keys: ["cost_of_revenue"],
    });
  }
  if (
    has(
      "net_change_cash",
      "cfo",
      "cfi",
      "cff",
      "fx_effect",
    )
  ) {
    relations.push({
      relation_id: "CFS_COMPONENT_SUM",
      family: "CL",
      observed_key: "net_change_cash",
      terms: [
        ["cfo", 1],
        ["cfi", 1],
        ["cff", 1],
        ["fx_effect", 1],
      ],
    });
  }

  const current = provenance.cash ?? {};
  const prior = provenance.prior_cash ?? {};
  const change =
    provenance.net_change_cash ?? {};
  const compatible =
    (
      current.concept
        === "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
      && change.concept
        === "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"
    )
    || (
      current.concept
        === "CashAndCashEquivalentsAtCarryingValue"
      && change.concept
        === "CashAndCashEquivalentsPeriodIncreaseDecrease"
    );

  if (
    has(
      "cash",
      "prior_cash",
      "net_change_cash",
    )
    && current.concept === prior.concept
    && compatible
  ) {
    relations.push({
      relation_id: "CASH_ROLL_FORWARD",
      family: "YOY",
      observed_key: "cash",
      terms: [
        ["prior_cash", 1],
        ["net_change_cash", 1],
      ],
    });
  }
  return relations;
}

export function expected(relation, values) {
  const absolute = new Set(
    relation.absolute_keys ?? [],
  );
  return relation.terms.reduce(
    (sum, [key, coefficient]) => {
      const raw = Number(values[key]);
      const value = absolute.has(key)
        ? Math.abs(raw)
        : raw;
      return sum + Number(coefficient) * value;
    },
    0,
  );
}

export function predict(caseValue) {
  const values = caseValue.values ?? {};
  const provenance =
    caseValue.provenance ?? {};
  const enabled = new Set(
    (caseValue.enabled_relation_ids ?? [])
      .map(String),
  );
  const relations = relationSpecs(
    values,
    provenance,
  ).filter((relation) =>
    enabled.has(relation.relation_id),
  );

  const checks = relations.map((relation) => {
    const observed = Number(
      values[relation.observed_key],
    );
    const exp = expected(relation, values);
    const tol = tolerance(observed, exp);
    const residual = observed - exp;
    return {
      relation_id: relation.relation_id,
      family: relation.family,
      observed_key: relation.observed_key,
      expected_keys: relation.terms.map(
        ([key]) => key,
      ),
      observed,
      expected: exp,
      residual,
      tolerance: tol,
      passed: Math.abs(residual) <= tol,
    };
  });
  const failed = checks.filter(
    (check) => !check.passed,
  );
  const visible = [
    ...new Set(
      checks.flatMap((check) => [
        check.observed_key,
        ...check.expected_keys,
      ]),
    ),
  ].sort();
  return {
    policy_id: POLICY_ID,
    decision:
      checks.length < 1
        ? "ABSTAIN"
        : failed.length
          ? "ERROR"
          : "CLEAN",
    relation_count: checks.length,
    failed_relations: failed,
    all_relations: checks,
    visible_keys: visible,
  };
}

export function roundedCase(
  caseValue,
  divisor = 1_000_000,
) {
  return {
    ...caseValue,
    values: Object.fromEntries(
      Object.entries(
        caseValue.values ?? {},
      ).map(([key, value]) => [
        key,
        Math.round(Number(value) / divisor),
      ]),
    ),
    reporting_variant: {
      name: "rounded_millions",
      divisor,
      rounding: "nearest integer",
    },
  };
}

export function rowFromInstance(
  instance,
  rounded,
) {
  const caseValue = rounded
    ? roundedCase(instance.case)
    : instance.case;
  const prediction = predict(caseValue);
  const ground = instance.ground_truth ?? {};
  const target = ground.target_key ?? null;
  return {
    instance_id: instance.instance_id,
    ticker: caseValue.ticker,
    sic: caseValue.sic ?? "",
    variant: rounded
      ? "rounded_millions"
      : "exact",
    gold_error: Boolean(ground.has_error),
    target_key: target,
    family: ground.family ?? null,
    observable:
      !target
      || prediction.visible_keys.includes(
        target,
      ),
    decision: prediction.decision,
    relation_count:
      prediction.relation_count,
    failed_relation_ids:
      prediction.failed_relations.map(
        (relation) => relation.relation_id,
      ),
    visible_keys: prediction.visible_keys,
    prediction_sha256: "",
  };
}

export function stripPredictionHash(row) {
  const value = {...row};
  delete value.prediction_sha256;
  return value;
}
