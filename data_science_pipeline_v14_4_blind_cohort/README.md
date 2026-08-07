# Stage 09 — blind real cohort freeze

This lane applies the externally signed scale-up protocol from PR #151 to one exact public ONCAE 2024 OCDS archive. It streams the archive once, reads only fields permitted during discovery, and retains at most the 20 smallest deterministic commitment keys per registered method group.

The inventory may inspect contract existence, explicit contract value/currency/date, exact `procurementMethod`, and source lineage. It must not inspect or export `bid_count`, tenderer counts, `low_competition`, outcomes, labels, buyer/supplier identities, OCIDs, process identifiers, rankings, or documentary relationships.

Eligible methods are exact `direct → DIRECT` and `open → OPEN`. Each group freezes ten primary and ten reserve event commitments. The output contains commitments and source-lineage hashes only. No raw source row or identity is retained.

A successful cohort freeze permits a separate, later outcome-reveal lane to look only for an explicit nonnegative integer bid count. It does not run Fisher inference, reveal outcomes, validate the contract-payment relationship, authorize production, or unblock Stage 10.
