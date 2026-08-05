# USAspending V3 — resultado oficial

**FAIL 0/3. Score: 465/1000.**

La corrida oficial `31023664997` fue válida: el candidato congelado produjo y selló las tres respuestas antes de descargar validadores o ground truth; cada validador se ejecutó una sola vez.

| Query | Candidato | Esperado | Causa principal |
|---|---:|---:|---|
| 8 | `60` | `25` | No vinculó “Lockheed Martin” como filtro de recipiente. |
| 9 | `77` | `147` | No interpretó “no English-language description” y persiste pérdida en la reconciliación monto–descripción. |
| 10 | IDs de 10 awards | `141` | Clasificó awards, no recipients, y descartó en vez de conservar la existencia de montos `_OLD`. |

Evidencia:

- artifact `8937788141`, SHA-256 `73e703653144ef5b7c837998f6c0652caf54a57af18e6619a89f7366ade37093`;
- candidate SHA-256 `b963b2579756dbe6900da06c2c49de6c81d80354af83073e6572226e25811621`;
- answer manifest SHA-256 `3b18fb6b0cb85459dfd07e3a76b8884661840d66f3f9650d8d95577c45008388`;
- validation SHA-256 `bf73e051cd0f64a9723d34700fc28bb576c663b41f4d77e1127f87374a9872d3`.

Las consultas USAspending `1–10` quedan completamente expuestas y retiradas de cualquier promoción futura. Pueden usarse sólo como regresión diagnóstica. No hubo merge, retuning, GCloud ni puntos de novedad.
