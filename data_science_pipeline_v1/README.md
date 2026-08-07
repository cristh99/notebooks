# Canonical Data Science Pipeline v1

This isolated branch contains the first executable spine for the Knowledge Base's Data Science system.

## What it enforces

- decision and source contracts before data processing;
- 14 canonical stages from definition to retirement;
- content-addressed immutable raw artifacts;
- exact input conservation: every input is accepted, quarantined, rejected, superseded, published, retired, or causes a closed failure;
- material quarantine with reason codes;
- parent/child lineage and artifact registry;
- append-only SHA-256 hash-chained ledger;
- deterministic idempotency and unique run IDs;
- duration and USD cost receipts;
- fail-closed execution on stage crashes, invalid costs, incompatible states, unknown parents, or silent loss.

## Verification

The frozen bundle passed 20/20 local and adversarial tests plus `compileall`.

```text
Manifest SHA-256: d10202fc0c01be5ac398dd27dc5bec0b2c2fad4936b5dc7a790d7d3b86985592
Ledger head:        e8baeb5b090370ee739e6aea840752563f3e8569d4424a3750815b2def83baee
Receipt SHA-256:    8732826a49333619ec23047b3f92c16ea788e1e9517e8c0b29d298b31b6596c4
Bundle SHA-256:     d2116de142fc94daaa833b949daadbc3ff7052c6c8e421348d49aa7d5022ea3f
```

## Reconstruct

```bash
bash data_science_pipeline_v1/reconstruct.sh
cd data_science_pipeline_v1/materialized/canonical_data_science_pipeline_v1
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

## Scope boundary

The local-first core is executable. IAIP/ONCAE acquisition, OCR, entity resolution, knowledge graph, semantic snapshots, modeling, monitoring, and retirement still require adapters; none may bypass preservation, lineage, quarantine, cost, or scientific gates.

No merge, deployment, GCloud, paid compute, or automatic workflow execution is included.
