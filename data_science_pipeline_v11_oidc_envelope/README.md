# Stage 07 OIDC preregistration envelope

This capsule signs a canonical envelope that binds the exact Git blob of the already-frozen ONCAE preregistration. It does not open, resolve, download, OCR, or evaluate the source PDF.

A valid Sigstore bundle proves only envelope integrity and the GitHub Actions identity recorded in the certificate. It does not prove the declarations inside the original preregistration, document authenticity, OCR quality, resolution accuracy, legality, intent, corruption, or Stage 08 readiness.
