# FIN-RVI-002 Stage 1 — independent clean replay capsule

This branch is an isolated, unmerged replay capsule for the public ONCAE–SEFIN Stage 1 experiment selected by Logic Power v10 as a finance meta-controller.

## Bound source

- repository: `cristh99/notebooks`;
- source commit: `1063b81df29e3054961c3dba3ef190ea083ed88a`;
- canonical deterministic replay SHA-256: `0441d92dfa643e93ee95c77955ce6d24e09f343a0bf9572966299d56d0bef826`;
- canonical report payload SHA-256: `bbd117b249fe214cc74dca58a5ae080545e1c34bc5652857850eec2fa6008440`.

## Replay contract

The workflow checks out the exact source commit into a fresh directory, reruns all unit/adversarial tests, redownloads the six official OCP Registry packages, reconstructs the release index and sealed holdout, reacquires public documents, and requires byte-identical deterministic evidence.

It additionally verifies the six fixed official package SHA-256 values and the core Stage 1 outcomes:

- 20 holdout pairs;
- 16 supported, 1 rejected, 3 unresolved;
- 4 unsupported baseline promotions;
- zero unsupported evidence-policy promotions;
- L 4,644,050.40 unsupported amount at risk avoided.

## Boundary

This is an independent runtime replay, not an independent implementation or human ground-truth adjudication. A successful run closes reproducibility of the declared experiment, but it does not by itself prove legal payment, delivery, receipt, physical result, or scientific priority.

Keep this PR draft and unmerged. Its only purpose is reproducible evidence.
