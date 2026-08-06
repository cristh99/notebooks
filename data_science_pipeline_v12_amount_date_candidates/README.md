# Data Science Lane M v1 — amount/date numeric candidates

**Coordination:** `COORD-2026-08-06-PARALLEL-V2`  
**Owner:** GPT-5.6 Thinking — amount/date candidate lane  
**Predecessor:** `cristh99/notebooks#107` head `543de7607f689ed424578af3ae0f6fe2c71552ce`  
**Downstream arbiter:** `cristh99/notebooks#135` (separate owner; this lane does not promote decisions)  
**Status:** `SOFTWARE_REGRESSION_ONLY`  
**External document access:** `0`  
**Production writes:** `0`  
**External spend:** `USD 0.00`

## Purpose

Emit conservative numeric candidates after Normalize without creating another normalizer or arbiter. The lane preserves exact decimal strings, source spans, lineage and explicit role hints; ambiguous numeric tokens remain unresolved instead of being coerced.

## Frozen classes

- `MONETARY_AMOUNT`
- `CALENDAR_DATE`
- `FISCAL_PERIOD`
- `LEGAL_INSTRUMENT_ID`
- `TELEPHONE_CONTACT`
- `PAGE_LIST_NUMBER`
- `UNRESOLVED_NUMERIC`

## Precedence and fail-closed rules

1. Explicit fiscal-period context.
2. Valid full dates and month-year dates.
3. Legal IDs only with nearby legal context.
4. Monetary amounts only with explicit standalone currency.
5. Phones only with country-code form or explicit contact context.
6. Page/list numbers only with explicit page/list context.
7. Everything else numeric remains `UNRESOLVED_NUMERIC`.

Full dates are evaluated before telephone patterns, so `2024-11-10` and `10-11-2020` cannot become phone numbers. Invalid dates such as `31-02-2024` remain unresolved. Dotted short forms such as `10.11.20` remain unresolved rather than being inferred.

Money is represented as an exact decimal string; `float` is not used as the authority for identity or financial tie-out. Role hints are emitted only from explicit nearby terms such as contract, commitment/obligation, accrual, payment order, payment, reception/acceptance, liquidation or validity. Hints are candidates, never proof of transaction identity.

## Frozen regression controls

The local suite contains 17 deterministic controls including:

- `EJERCICIO FISCAL 2024` → fiscal period, never money;
- `2024-11-10` → calendar date, never phone;
- `10-11-2020` → calendar date, never phone;
- `10/11/2020` → calendar date;
- `31-02-2024` → unresolved;
- `10.11.20` → unresolved, never money;
- `+504 2209-5355` → telephone;
- `Decreto 62-2023` → legal instrument;
- bare `62-2023` → unresolved without legal context;
- `L. 1,250.00`, `1.250,00 lempiras`, `USD 10.50` → exact monetary candidates;
- `Página 37` → page/list number;
- `noviembre 2024` → month-precision date;
- explicit contract amount and payment-date role hints;
- exact source span preservation.

No fresh external document or scientific holdout is consumed by this software-only successor. Promotion remains governed by the separate arbiter and a future preregistered fresh-document gate.
