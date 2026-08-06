# OpenVINO v7 — license and provenance review

**Date:** 2026-08-06  
**Coordination lane:** `COORD-2026-08-06-PARALLEL-V2`  
**Repository / PR:** `cristh99/notebooks#129`  
**Scientific state:** metadata/schema/power PASS; scientific verdict `UNKNOWN_NO_IMAGE_OUTCOMES_OPENED`  
**Operational decision:** `BLOCKED_MISSING_PER_IMAGE_ATTRIBUTION_PROVENANCE`

## Decision

Do **not** download, decode, inspect, redistribute, or run OCR on the embedded `image` bytes in the Hugging Face `openvino` Parquet mirror. Do not start the separately preregistered full external gate.

This is a fail-closed operational compliance decision, not a legal opinion. The block remains until the exact 207,790 rows can be linked deterministically to upstream Open Images image IDs and a complete per-image provenance and attribution ledger can be produced and verified.

## Verified facts

1. The Hugging Face aggregate says it embeds raw image bytes and exposes only these fields for each row: `image`, `texts`, `bboxes`, `polygons`, and `num_text_regions`. It labels the aggregate dataset Apache-2.0.
2. Its `openvino` split is identified as OpenVINO text-detection training data. The exact population and annotation counts match the paper *Open Images V5 Text Annotation and Yet Another Mask Text Spotter*: 207,790 images and 2,571,610 text instances.
3. The official Open Images V5 page states that Open Images annotations are CC BY 4.0 and that images are listed as CC BY 2.0, while explicitly instructing users to verify the license of each image themselves.
4. The official Open Images image metadata includes `ImageID`, original and landing URLs, license, author profile, author, title, original size, hash, thumbnail URL, and rotation.
5. The mirrored Parquet schema does not include `ImageID`, `License`, `Author`, `AuthorProfileURL`, `OriginalLandingURL`, or equivalent attribution/provenance fields.

## Evidence-based interpretation

- The aggregate Apache-2.0 declaration is evidence about the mirror's declared license, but it does not by itself prove that every embedded upstream image may be used without the per-image attribution and verification required by the upstream Open Images records.
- Because the mirror omits the upstream image identifier and attribution fields, the current row set cannot be independently reconciled to the official license metadata.
- The specific license governing the Intel/OpenVINO text-annotation package was not independently established in the reviewed primary materials. The paper establishes authorship, scope, counts, and availability, but not a separate dataset license.
- Therefore the evidence is insufficient to authorize image access or a full OCR benchmark from this mirror.

## Allowed now

- Preserve and audit the already completed metadata-only receipts.
- Read schema, counts, text annotations, bounding boxes, polygons, hashes, and public documentation without opening image bytes.
- Prepare provenance-reconstruction code and tests without executing them on image bytes.
- Ask the mirror maintainer or upstream maintainers for a deterministic row-to-Open-Images-`ImageID` mapping and explicit licensing documentation.

## Prohibited now

- Full or partial download of the embedded image column.
- Decoding, viewing, hashing decoded pixels, OCR, candidate inference, or quality/speed evaluation on those images.
- Redistribution of embedded image bytes.
- Claiming that Apache-2.0 supersedes upstream per-image CC attribution or verification requirements.
- Merging PR #129 or reporting quality, speed, 10×, or production PASS.

## Exact unblock conditions

All conditions must be met:

1. A deterministic mapping from every selected mirror row to the official Open Images `ImageID`, with immutable source revision and checksum.
2. A complete attribution ledger containing at least `ImageID`, `OriginalURL`, `OriginalLandingURL`, `License`, `AuthorProfileURL`, `Author`, `Title`, and the official source metadata hash.
3. Per-image license verification and an explicit policy for missing, changed, revoked, or non-CC records.
4. Independent confirmation of the license for the OpenVINO text annotations or written permission sufficient for the intended evaluation.
5. Encoded-byte and decoded-pixel deduplication against all previously opened corpora.
6. A separately preregistered full gate that preserves the frozen v7 candidate, thresholds, metrics, abstention semantics, one-run rule, zero retuning, zero paid services, and draft/no-merge boundary.
7. A terminal artifact and independent audit before any scientific claim.

## Preferred remediation

Reconstruct the evaluation population from official Open Images metadata rather than using the mirror's embedded bytes:

1. obtain the exact OpenVINO annotation files and their immutable hashes;
2. recover each annotation's Open Images `ImageID`;
3. join to official Open Images image metadata;
4. exclude rows without verifiable and usable license/provenance;
5. generate an attribution ledger and exclusion receipt;
6. estimate the post-filter power before authorizing any image download;
7. preregister a new full gate only if power remains sufficient.

## Sources reviewed

- Hugging Face: `Yesianrohn/OCR-Data` dataset card and schema.
- Open Images V5 official description and license section.
- Open Images V5 official download page and image-metadata schema.
- Krylov, Nosov, and Sovrasov (2021), *Open Images V5 Text Annotation and Yet Another Mask Text Spotter*, arXiv:2106.12326.
- OpenVINO-hosted `open_images_v5_text` distribution index.

## Final status

`LICENSE_REVIEW_BLOCKED_MISSING_PER_IMAGE_ATTRIBUTION_PROVENANCE`

The metadata gate remains valid and audited. The scientific verdict remains `UNKNOWN_NO_IMAGE_OUTCOMES_OPENED`. Image access, OCR, and the full external gate remain unauthorized.
