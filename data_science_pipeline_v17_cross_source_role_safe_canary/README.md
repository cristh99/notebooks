# Data Science v17 — cross-source role-safe canary

This package narrows the remaining Lane V gate using a deterministic pre-outcome selection over the frozen Stage 7 ONCAE–SEFIN sample.

The first eligible review item is selected by immutable `review_item_id` ordering only after exact supplier identifier, supplier name, buyer name, HNL amount, two-source and Stage 7 left/right gates pass. No fuzzy matching, substring promotion, manual identity inference or post-result retuning is used.

The selected pair contains two economically different events: an ONCAE contract and a SEFIN payment. Their equal amounts do not authorize event collapse. The software preserves `CONTRACT_VALUE / CONTRACT_DATE` and `PAYMENT_VALUE / PAYMENT_DATE` as separate roles and refuses to assert a transaction relationship.

The canary remains `CANDIDATE_REVIEW` because the SEFIN source document, procurement method and bid count are missing. Stage 08 remains blocked. Public files contain commitments, not raw supplier/buyer identities or raw process IDs.
