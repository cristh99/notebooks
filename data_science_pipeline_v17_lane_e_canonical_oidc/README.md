# Lane E canonical OIDC signature

This package signs the exact canonical Lane E subject supplied by the Lane V owner through Neon coordination.

It binds the canonical Lane E receipt hashes, event universe, selected review item, identity commitments, source commitments, operational abstentions, and governance state. It does not include the exact operational receipt bytes and therefore does not replace that evidence.

The signature establishes only the exact signed bytes and the GitHub Actions/Sigstore workflow identity. It does not establish entity resolution accuracy, supplier identity truth, bid count, a SEFIN source document, Lane M validity, wrongdoing, production readiness, or Stage 08 readiness.
