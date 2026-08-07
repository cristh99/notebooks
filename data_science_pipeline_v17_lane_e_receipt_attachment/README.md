# Lane E exact receipt-byte attachment

This package binds the exact 1,398-byte canonical Lane E receipt to the previously signed canonical Lane E subject.

The external workflow downloads the retained artifact from the prior successful GitHub OIDC/Sigstore run, verifies the archive and evidence hashes, independently re-verifies the prior signature, checks the exact receipt file and self-hash against the signed subject, and signs this attachment envelope with a separate workflow identity.

This closes only the Lane E exact-byte attachment gate. Lane M, bid count, the explicit SEFIN source document, relationship promotion, production, and Stage 08 remain open or blocked.
