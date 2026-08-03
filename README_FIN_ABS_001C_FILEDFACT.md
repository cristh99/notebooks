# FIN-ABS-001C — independent passage-complete accounting breadth

## Purpose

Finance remains **423/1000** after FIN-ABS-001B was blocked by SEC HTTP 403
from GitHub-hosted runners. FIN-ABS-001C tests the same core capability on an
independent, public, passage-complete SEC/XBRL dataset without weakening the
provenance, breadth, safety, or score boundary.

## Frozen source

- Dataset: `StockAlloy/filedfact-passages`.
- Dataset card version: `v1.2`.
- Selection manifest SHA-256:
  `bc0b3e526742567daa5b17deacb533a4419e5cab4375962cdb5a0e0a7ef78a3a`.
- Split: `validation` only.
- The Hub commit SHA is resolved before loading any rows and then used as the
  immutable revision for every download.
- The public card reports 776 validation passages from 765 companies; train
  and validation are company-disjoint.

## Direct evidence boundary

Every relation must remain inside one passage and one filing accession. Every
fact must carry:

- stable fact ID;
- XBRL concept, period, unit, and dimensions;
- normalized value;
- exact displayed-text span satisfying
  `text[text_start:text_end] == displayed_text`;
- SEC filing URL and passage hash.

No value is imputed, residualized, inferred from sector conventions, or fetched
from a different filing.

## Relation families

1. **Statement equations**
   - assets = liabilities-and-equity total;
   - assets = liabilities + equity;
   - gross profit = revenue − cost of revenue;
   - net income = pretax income − tax, only when the source numbers reconcile;
   - cash change = CFO + CFI + CFF + exchange effect.
2. **Dimension totals**
   - one non-dimensional total equals at least two unique members of one XBRL
     axis for the same concept, period, and unit.

Candidate relations are accepted only when the unmodified filing facts already
reconcile within the frozen tolerance. Controlled errors are created only after
that source-clean relation has been frozen.

## Gates

All must pass:

- source revision pinned and public selection manifest verified;
- exactly 776 validation rows and at least 700 validation companies;
- at least 40 eligible companies, 60 relations, 20 SIC codes, and two forms;
- both relation families represented by at least five relations;
- at least 20 dimension-total and five statement-equation relations;
- all relations retain direct span-grounded provenance;
- exact precision 100%, FPR 0, recall 100%, and coverage 100%;
- rounded-to-millions FPR 0 and recall at least 95%;
- fixed permutation control is worse;
- Node independently reimplements decisions, metrics, gates, provenance, and
  score logic;
- score, source, relation, and prediction forgeries are rejected.

## Score contract

A complete pass may add only **6 absolute points**:

- generality across an independent dataset: +3;
- external construct validity: +3;
- world-SOTA: +0;
- historical originality: +0.

Maximum result: **429/1000**. This visible-label research sample is not a blind
benchmark and cannot establish Finance 1000.

## Cost and isolation

- Paid infrastructure: **US$0**.
- Uses public Hugging Face data and GitHub Actions only.
- No GCloud, MotherDuck, OCR, crawlers, or active agents are touched.
- Branch remains isolated, draft, and unmerged.
