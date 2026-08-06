# Data Science pipeline v9 — identity-aware external resolution

This gate tests one fresh official ONCAE circular without requiring landing-page or filename tokens to appear in the PDF body.

The protocol separates:

1. **Source authority** — official landing page and one allowlisted PDF link.
2. **Document binding** — exact PDF bytes, URL, size, page count and SHA-256.
3. **Content resolution** — facts supported by the body only.

The candidate sees three frozen OCR outputs and emits only facts agreed by at least two strategies. Native PDF text is forbidden until the candidate JSON is sealed. A separate native-text oracle then adjudicates exact-set precision and recall. No result authorizes merge, production use or mass processing.
