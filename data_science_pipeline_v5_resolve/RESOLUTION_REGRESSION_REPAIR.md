# Data Science pipeline v5 — strict amount regression repair

## Result

The original v5 integration run `31063323232` failed correctly because the amount parser interpreted the final `L` in `EJERCICIO FISCAL 2024` as the standalone lempira marker and emitted `L 2024` / `HNL 2024.00`.

This branch makes the smallest bounded repair:

- currency prefixes must be standalone tokens;
- explicit forms such as `L. 1,250.00`, `HNL 1250`, `$ 10.50`, and `1.250,00 lempiras` remain supported;
- fiscal years, decree identifiers, page numbers, and phone numbers remain non-money;
- the existing entity, date, legal-reference, contact, lineage, and replay behavior is unchanged.

## Verification

- public workflow run: `31070183356` — SUCCESS;
- tests: `13/13 PASS`;
- exact sealed upstream artifact: `8952699633`;
- upstream ZIP SHA-256: `3c2aa0e8551b559ab2540f61a13a1aef3d69d6efec64437721d574f1d38be2d8`;
- two complete resolutions: byte-identical;
- amount rows: `0`;
- amount abstentions: `1`;
- entity collisions: `0`;
- evidence artifact: `8955335328`;
- artifact ZIP SHA-256: `334e61cce7fbc7afcadeb2127d803a9f8f6b83b249ff6f71d6eb4115a4fc6a58`;
- integration receipt SHA-256: `96c98a7091f322bdf69dd3ce72e5cc79be652149fe57e15566f0986d434fe45a`;
- external cost: `USD 0.00`.

## Boundary

This proves the repair for one official ONCAE document and the first three pages already sealed by the upstream pipeline. It does not authorize merge, production, mass processing, or broader entity/amount accuracy claims.
