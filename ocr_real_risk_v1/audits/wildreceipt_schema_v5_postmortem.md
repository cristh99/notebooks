# WildReceipt schema-v5 — postmortem externo

**Veredicto:** `WILDRECEIPT_EXTERNAL_TENFOLD_BOUND_NOT_REACHED`  
**Cota certificada:** **5.876×**, no 10×.  
**Estado metodológico:** validación externa reparada completada; ningún cambio de producción autorizado.

## Resultado terminal

| Métrica | Resultado |
|---|---:|
| Recibos físicos seleccionados | 1720 / 1739 |
| Baseline elegible / errores | 680 / 92 |
| Error baseline observado | 13.529% |
| Cota inferior baseline | 10.723% |
| Candidato aceptado | 347 |
| Aceptaciones correctas / falsas | 346 / 1 |
| Falsa aceptación observada | 0.288% |
| Cota superior del candidato | 1.825% |
| Cobertura observada / cota inferior | 20.174% / 18.043% |
| Contrafactuales falsamente aceptados | 1 / 1720 |
| Cota superior contrafactual | 0.370% |
| Folds de estabilidad aprobados | 0 / 3 |
| Timeouts OCR | 0 |

El protocolo falló por dos causas simultáneas: la cota de reducción quedó en **5.876×** y la cobertura conservadora quedó en **18.043%**, por debajo de 25%. El contrafactual sí permaneció bajo su límite de 1%.

## Embudo causal

| Etapa | Correctos | Incorrectos | Total |
|---|---:|---:|---:|
| Reclamo elegible del detector | 751 | 107 | 858 |
| Bosque aceptó | 374 | 1 | 375 |
| Guard rechazó después del bosque | 28 | 0 | 28 |
| Aceptación final | 346 | 1 | 347 |

El detector ya entregó **751 reclamos correctos elegibles**. El cuello de botella no es la muestra ni la oferta de candidatos: el bosque descartó **377** correctos y el guard descartó otros **28**. Hay **405** correctos disponibles para rescate downstream.

## Frontera exacta

La cota inferior del baseline fija como máximo admisible para el candidato `0.010723`.

- Con **cero** falsas aceptaciones se necesitan al menos **472** aceptados; faltan **125**.
- Conservando **una** falsa aceptación se necesitan al menos **593** aceptados; faltan **246**.
- Bajar únicamente el umbral del bosque no resuelve el problema: incluso en `0.0`, el guard limita la aceptación a 374 y aparecen dos falsas aceptaciones.

## Falsa aceptación natural

`test-00000-of-00001:70`: anotación `11.98` → verdad `1198`; baseline, cinco PSM, bosque y ambos guards produjeron `1199`.

- Probabilidad mínima del bosque: `0.336770`.
- Votos: `5` de PSM `[3, 4, 6, 11, 12]`.
- Confianza OCR: `72.8`.
- Conflictos de igual longitud: `[]`.
- Hash del crop: `0688b25bc04abd935acc18165de22e456f0d1091d031c7a449af3da3d03b3112`.

Es una confusión correlacionada `8→9`; aumentar votos o exigir que ambos guards coincidan no la elimina porque todas las rutas actuales dependen de evidencia visual/Tesseract estrechamente correlacionada.

## Falsa aceptación contrafactual

`train-00000-of-00002:173`: verdad y reclamo natural `22995`; el bosque predijo la mutación `22905` con probabilidad mínima `0.269827` y una vista del guard también leyó `22905`.

## Resultado por shard

| Shard | Seleccionados | Elegibles | Aceptados | Falsos naturales | Falsos contrafactuales |
|---|---:|---:|---:|---:|---:|
| `test-00000-of-00001` | 468 | 246 | 102 | 1 | 0 |
| `train-00000-of-00002` | 624 | 303 | 104 | 0 | 1 |
| `train-00001-of-00002` | 628 | 309 | 141 | 0 | 0 |

## Dirección del sucesor

1. WildReceipt pasa a ser **datos de desarrollo abiertos**; no puede reutilizarse como certificado externo intacto.
2. Minar hard negatives, especialmente confusiones `8↔9` y `0↔9`, y entrenar un verificador visual independiente del stack Tesseract.
3. Mantener la ruta conservadora actual y añadir una ruta de rescate calibrada para recuperar al menos **126** reclamos correctos sin falsos.
4. Exigir margen de desarrollo —preferiblemente ≥600 aceptados, cero falsos naturales y cero contrafactuales— antes de congelar.
5. Congelar código, modelo, umbrales y rutas antes de abrir un corpus externo nuevo y sellado.

## Trazabilidad

- Run: `30998215981`
- Candidato estable: `95d4525b8c14de6168d080c8d3aec51852c7f954097426e2f69c00682dd3d387`
- Protocolo estable: `dc582b1ac36eca9199d1032913af2cc1ab391eaf40a22641fcea78e115f5cb42`
- Agregado estable: `762d3350739f94bd0054d1db2e9b460f6b5043c7e1969242d8df6cd9b4b06ccf`
- Postmortem estable: `ec8b2846b7fc5bb91dbdc21d2de237bc1635bffdde4182d37d9c20c9e2d3632c`
- Gasto externo: `$0`; GCloud/GPU/API pagada: no; producción: intacta.
