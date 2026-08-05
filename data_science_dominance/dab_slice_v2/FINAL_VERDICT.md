# DataAgentBench six-query slice — final verdict

**FAIL externo válido: 4/6.**

- PASS: CVE (`4`), StockIndex (`399001.SZ`), BookReview (`2020s`), MusicBrainz (`1059.46`).
- FAIL: Civic (lista vacía; faltaron 11 proyectos), USAspending (`58` frente a `898`).
- Candidate SHA-256: `0796f1d66d944e832181034f6e8e8800461b60d71e66716d5b19fe3fd1957dec`.
- Run: `30995835958`.
- Artifact: `8926161553`; ZIP SHA-256 `7c9a6cfe2ff3194a800114a5b4de75fd1cfc26690b4d66eeaef30723a0b1ffab`.
- Official report SHA-256: `5d0ba5ab71b399b79798046a760a9923286b6bbab72ef1305dc7a36af156634c`.
- External evaluations: exactly one.
- Post-hoc retuning: prohibited.
- Score impact: none; canonical practical-dominance score remains `465/1000`.

The exposed queries are retired from promotion. The next candidate must address general unstructured-record extraction and high-recall identifier reconciliation, then be tested on fresh queries.
