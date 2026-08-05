# WildReceipt schema-v5: pre-result statistical audit

**State:** frozen external evaluation in progress; no shard outcome or aggregate verdict was used to write this audit.

## Immutable bindings

- Candidate: `numeric-consensus-v4-wildreceipt-schema-v5`
- Candidate artifact: `8926919972`
- Candidate artifact SHA-256: `6f6a0b588dbadc19b4fd59ff7e018c148d2eb62a7389cd7cbcf83fc038389e5b`
- Candidate stable payload: `95d4525b8c14de6168d080c8d3aec51852c7f954097426e2f69c00682dd3d387`
- Candidate source commit: `03e4787e7d9aed5a4a92ee399797bf117a5857f0`
- Model SHA-256: `53229915331c2bbea2454f9e7cb5768a26e9edb30de750747f4397f1ff4cf92c`
- Protocol artifact: `8927148015`
- Protocol stable payload: `dc582b1ac36eca9199d1032913af2cc1ab391eaf40a22641fcea78e115f5cb42`
- Selected physical receipts: `1720 / 1739`
- Duplicate physical associations surviving: `0`

The geometry repair, risk-unit selection, counterfactual construction, model, threshold, guard, exact gates, evaluator, and recursive local import closure were bound before these OCR outcomes.

## Exact familywise gates

Four one-sided Clopper-Pearson bounds use `alpha = 0.0125` each. Bonferroni therefore bounds familywise error by `0.05` without an independence assumption.

A pass requires all of the following:

1. selected receipts `>= 1200`;
2. accepted receipts `>= 400`;
3. lower coverage bound `>= 0.25`;
4. at least one baseline error;
5. candidate error upper bound `<= baseline error lower bound / 10`;
6. counterfactual false-accept upper bound `<= 0.01`;
7. at least two of three leave-one-source-shard-out folds pass their proportionally scaled gates.

## Exact frontier fixed before outcomes

For `1720` selected receipts, the coverage bound—not the nominal count gate—requires at least **472 accepted receipts**. At 472 accepted, its one-sided lower bound is `0.2505211541`.

Assuming zero candidate false accepts, the following frontier applies:

| Accepted | Candidate error upper | Required baseline error lower for 10x |
|---:|---:|---:|
| 472 | 0.0092409919 | 0.0924099188 |
| 500 | 0.0087257609 | 0.0872576090 |
| 553 | 0.0078927859 | 0.0789278589 |
| 600 | 0.0072767729 | 0.0727677287 |
| 650 | 0.0067189060 | 0.0671890597 |

With zero counterfactual false accepts among all `1720` selected receipts, the counterfactual upper bound is `0.0025444473`, comfortably below `0.01`.

One retained false accept materially raises the candidate upper bound: at 553 accepted it rises from `0.0078927859` to `0.0114827656`. The certificate is therefore intentionally difficult.

## Method audit

- Baseline and candidate claims are scored spatially against the preselected expert location; truth and expert geometry are not used to construct detector candidates.
- Candidate acceptance requires detector eligibility, digit-forest agreement at threshold `0.25`, and an independent PSM-7 crop guard.
- The one-digit counterfactual has equal length. Forest segmentation and probabilities therefore remain identical; testing the already-computed prediction and guard reading against the counterfactual is equivalent to rerunning those downstream checks for that claim.
- Bounds are conservative even though baseline and candidate observations are paired, because the proof uses simultaneous marginal bounds rather than an independence assumption.
- The external claim, if reached, is limited to selective numeric quality on this schema-repaired WildReceipt protocol. It is not a general OCR, Honduras-production, or automatic-deployment claim.

## Deferred performance work

No optimization below may alter this run. For a separately frozen successor only:

- short-circuit the crop guard unless the forest accepts the natural claim or can accept the equal-length counterfactual;
- benchmark bounded parallel execution of independent PSM calls on fixed CPU resources;
- retain byte-for-byte parity tests against schema-v5 before accepting any speed change.
