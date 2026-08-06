# Data Science pipeline v10 — signed validator trust registry

This bounded Stage 07 extension authenticates channel-validation receipts before they can authorize evidence.

## Controls

- Ed25519 public keys live in a deterministic trust registry;
- registry SHA-256 must match the externally pinned value;
- validator ID must exist in the registry;
- policy and evidence channel must be explicitly authorized;
- the signature binds the registry hash and the complete v9 channel-validation receipt;
- the v9 receipt already binds channel, observation hash, validator ID and policy hash;
- forged signatures, cross-validator replay, cross-channel replay, unauthorized policies/channels, altered observations and registry drift fail closed.

## Reproduce

```bash
cd data_science_pipeline_v10_signed_validator
python -m pip install -r requirements.txt
EVIDENCE_SCOPE_ROOT=../data_science_pipeline_v9_evidence_scope python verify.py
```

The verifier checks the frozen v9 source, v10 source/tests/verifier/dependency hashes, runs 13 tests, compiles the code, checks a deterministic 1,000-case adversarial report and emits `evidence/receipt.json` plus SHA-256.

## Boundary

All private keys used in tests are synthetic fixed seeds. No real validator key, revocation process, rotation procedure or production trust root is present. This proves a finite software authorization policy only; a real public-key registry and a fresh preregistered external document remain required.
