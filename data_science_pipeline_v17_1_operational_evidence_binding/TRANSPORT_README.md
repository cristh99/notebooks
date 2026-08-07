# Data Science Lane V v17.1 — canonical transport

This repository directory contains the public, deterministic transport and the small public evidence receipts. The complete source, tests, and replay program are inside the canonical capsule.

```bash
./reconstruct.sh
unzip -q capsule.zip
cd data_science_pipeline_v17_1_operational_evidence_binding
python verify.py
```

Expected result: `40/40` tests pass; procurement method is hash-bound to the contract role; bid count remains `NOT_REPORTED`; the SEFIN primary document and independent Lane E/M signatures remain missing; Stage 08 remains blocked.

The transport is seven Base64 text parts bound by per-part SHA-256/Git-blob commitments and a decoded archive commitment. `reconstruct.sh` verifies all parts and ZIP members before atomically writing `capsule.zip`.
