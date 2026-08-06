# OpenVINO v7 metadata gate — independent terminal audit

**Date:** 2026-08-06  
**Flight:** `08599f29-9814-4dfd-afc1-56d2c34b2489`  
**Run:** `1` (`019fd8b1-599b-7e03-bc5d-8009e71ae2ff`)  
**Execution:** `SUCCEEDED`, exit code `0`  
**Coordination lane:** `COORD-2026-08-06-PARALLEL-V2`

## Exact result

- Metadata/schema/power gate: **PASS**
- Scientific verdict: **`UNKNOWN_NO_IMAGE_OUTCOMES_OPENED`**
- Exact source rows scanned in both stages: **207,790**
- Exact selected numeric image rows: **20,629**
- Frozen projected-power boundary: **16,997**
- Projected verified claims: **485.49208386820715**
- Frozen minimum projected verified claims: **400**
- Selected record-set SHA-256: `35ad9e1e43d81ef826f10a04659f77cacf13b987360e83625b52edcd7e223870`
- Separate full gate eligible only after license review: **true**
- Full image download authorized now: **false**
- OCR authorized now: **false**

## Integrity

- Frozen scientific source commit: `fa20f6d210fa8be7272178b1f152e38b2d583637`
- Frozen candidate stable payload: `160a3e79c6075a6741a1a6365b0c833115bfc6e156176cb4cb5744b1189119cd`
- Frozen source-seal stable payload: `3c1192c6a0dc420c4b9de66e4c5f0a2a916339286aa6f28b2e39ba28531ee089`
- Full census stable payload: `f88ef6b533def1bfe47ede75ae46b238d0759380e553d790ad7ec5cab510e1d4`
- Full census file SHA-256: `88fa61d1b483c04632304721c89d83415069f766c6a086e23f12f8adb7806742`
- Terminal stable payload: `bf94a65f0c157f6a8aeebbb7916a827282191550452794590722039728a64b4f`
- Run-summary stable payload: `641678a95bceaadc5e4799985cf6993033eb3118a8f6615082c44e7594e75f6b`

The four emitted gzip/base64 payloads decoded successfully; all reported compressed and raw hashes matched; source seal, candidate, terminal, and run-summary stable payloads replayed exactly; the projection was independently recalculated as `20,629 × 110 / 4,674 = 485.49208386820715`.

## Constraints verified

No image bytes, OCR, or candidate inference were executed. GCloud, GPU, paid APIs, production mutation, and external spend were all false or zero.

## Audit limit

The compact census intentionally omits the 20,629 selected records, so the full census stable payload cannot be recomputed from the compact copy alone. The in-run independent adjudicator verified the full census before emitting the terminal receipt, and the selected record set is cryptographically bound by `35ad9e1e43d81ef826f10a04659f77cacf13b987360e83625b52edcd7e223870`.

## Interpretation

This is a metadata/schema/power PASS only. It is not a quality PASS, speed PASS, 10× result, production claim, or authorization to download images. The next scientific stage requires an explicit license review and a separately preregistered full external gate.
