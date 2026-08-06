# Data Science pipeline v11 — Sigstore preregistration

This layer freezes a fresh ONCAE document **before** resolving the PDF URL, downloading bytes, opening content, running OCR, or resolving claims.

## Selected source metadata

- official page: `https://oncae.gob.hn/biblioteca/manuales/catalogo-electronico/manual-de-usuario-para-compras-por-catalogo-electronico/`;
- visible title: `Manual de usuario para compras por catálogo electrónico`;
- visible download label: `Manual de usuario Catálogo Electrónico Abril 2016`;
- PDF URL, bytes, hash and page count remain unknown at freeze time.

## Trust root

The workflow uses GitHub Actions OIDC and `actions/attest` pinned at commit
`59d89421af93a897026c735860bf21b6eb4f7b26` to create a custom Sigstore attestation.
Verification pins:

- repository `cristh99/notebooks`;
- signer workflow path;
- source branch and commit;
- custom predicate type;
- GitHub-hosted runner;
- subject SHA-256.

This removes the need to place a private signing key in the repository. The signed
record still contains declarations made by this workflow; Sigstore does not prove that
those declarations are factually true outside the workflow boundary.

## Static verification

```bash
cd data_science_pipeline_v11_sigstore_preregistration
python verify.py
```

The local gate runs 12 adversarial tests, checks canonical JSON and frozen file hashes,
and confirms zero document-content access and zero external evaluations.

## Boundary

The attestation proves subject integrity, the signer workflow identity, repository/ref/
commit provenance, and that the preregistration record existed at the attested commit.
It does not prove actual pre-commit non-access, evaluation count or cost, and it does not
prove that the user-controlled predicate is true without reviewing the trusted workflow.
It also does not prove document authenticity, OCR quality, resolver accuracy,
beneficial ownership, payment, legality, intent or corruption.

Stage 08 remains blocked until the attested preregistration is followed by one fresh,
full-document, no-retuning execution with independent truth and byte-identical replay.
