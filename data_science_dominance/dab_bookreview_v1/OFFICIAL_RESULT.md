# BookReview V1 — resultado oficial

**FAIL 0/2. Score: 465/1000.**

El candidato congelado se ejecutó una sola vez en la corrida `31026531776`. Una respuesta vacía hizo fallar erróneamente el control de archivo no vacío; las respuestas exactas se recuperaron del log original y se sellaron sin reejecutar el candidato. Después, cada validador se ejecutó una sola vez en la corrida `31026852816`.

| Query | Respuesta | Frontera revelada |
|---|---|---|
| 2 | vacía | Faltó el título esperado `The Sludge`. |
| 3 | `Benny Goes To The Moon…` | Faltó el título esperado `Around the World Mazes`. |

La integración PostgreSQL–SQLite, el fuzzy join y el parsing semiestructurado no bastaron para las dos consultas frescas. No hubo retuning, merge, GCloud, cómputo pagado ni puntos de novedad.

Evidencia:

- artifact `8939004533`, ZIP SHA-256 `2ed61d4f3abf3ed6943e61f622357d6166847dfc380749e5fad50a4c9427fbc6`;
- candidate SHA-256 `f539ea1d8e7434ade8b8333054ba40d10a69f6e4c430e784ea321ccafde06414`;
- answer manifest SHA-256 `4a136662b02e69a5b9d36e2addfe3fb95e49e6deee2bb9c6becbf6b29c32398a`;
- validation SHA-256 `46b649c869ed1d9d7cef7bd583db711cadc4c0a137eb8f0bad142fee87f3c9fa`.

BookReview `query1–3` queda totalmente expuesto y retirado de promoción; sólo puede usarse como regresión diagnóstica.
