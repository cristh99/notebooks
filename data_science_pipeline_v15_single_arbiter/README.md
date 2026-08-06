# Stage 07 — single arbiter integration

This software-only capsule implements the unclaimed **single arbiter** lane under `COORD-2026-08-06-PARALLEL-V2`. It does not duplicate the amount/date resolver owned by another agent and does not create another normalizer.

The arbiter consumes one canonical entity/provider receipt and one canonical amount/date receipt. It requires exact event-universe, source-record, policy, trust and self-hash bindings; preserves `CONTRACT`, `OBLIGATION`, `PAYMENT` and `RECEPTION` roles; and emits exactly one canonical event or an explicit `CANDIDATE_REVIEW`, `NOT_EVALUABLE` or `QUARANTINED` terminal per event.

The synthetic fixtures are not real evidence. They exist only to verify deterministic software behavior, role preservation, fail-closed conflicts and compatibility with Stage 08 Semantic. Real promotion requires externally verified resolver receipts and a separately frozen evaluation.
