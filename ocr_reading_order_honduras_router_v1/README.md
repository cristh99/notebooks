# OCR Reading Order Honduras Router v1

This experiment tests the minimum contextual router selected after PR #33 falsified universal XY-cut in Honduran public documents.

Logic Power Problem Solver v1 is used only as a research controller. Neither Logic Power nor the Solver is imported by OCR runtime.

## Frozen router

The router compares two already-computed geometry-only orders over the same Tesseract blocks:

```text
baseline: top-to-bottom, left-to-right
candidate: frozen xycut_loose
```

It then applies the following rules, frozen before the new holdout was acquired:

1. identical orders → baseline;
2. any disagreement in the top 35% → baseline, protecting header/reference metadata;
3. all disagreement blocks in the bottom 45% → XY-cut, targeting signatures and parallel footers;
4. middle-body disagreement → XY-cut only with a page-width gap of at least 8%, at least 20% vertical overlap, and no wide spanning block;
5. otherwise → baseline.

Inputs are block boxes and page dimensions only. The router cannot see text, confidence, document type, page rule, source institution, ground truth or prior outcomes.

## Independent holdout

The manifest was committed before acquisition and uses the next five unused FIN-RVI-002 records, lines 6–10. It declares ten official public PDFs:

- five processes not present in PR #33;
- one first-page header-oriented document and one last-page signature/body-oriented document per process;
- notices, amendment, clarification, opening acts and contracts;
- deterministic `FIRST` or `LAST` page rules fixed by document type.

## Preparation

Public GitHub Actions:

1. downloads each PDF with a 25 MB cap;
2. validates PDF magic and preserves URL, bytes and SHA-256;
3. determines exact page count with `pdfinfo`;
4. renders only the frozen first or last page at 150 DPI;
5. runs Tesseract once with Spanish + English;
6. records baseline, XY-cut and router orders plus router features and reason;
7. creates numbered overlays and a blank partial-order annotation template;
8. fails closed unless at least 8/10 pages are prepared.

## Evaluation boundary

Only after the preparation artifact is frozen are the overlays annotated once. Every block is partitioned into semantic or ignored, and semantic reading order is represented as a partial-order DAG. The evaluator compares baseline, universal XY-cut and the contextual router.

The annotation is agent-generated, not blinded and not independent human ground truth. It is sufficient for internal falsification and routing decisions, not for external validation or a SOTA claim.

## Constraints

- external spend: `$0`;
- GCloud: forbidden and unused;
- paid APIs: unused;
- GPU: unused;
- one Tesseract pass per page;
- no production modification;
- draft, isolated and unmerged until evidence closes.
