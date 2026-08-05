# Próximo gate fresco de DataAgentBench

## Estado canónico

- El resultado externo sellado de seis consultas expuestas fue 4/6.
- No se concede puntuación por reajustar contra esas seis consultas.
- La puntuación permanece en 465/1000 hasta superar un gate nuevo, externo y reproducible.

## Objetivo del siguiente candidato

Resolver de forma general, no mediante respuestas específicas, los dos fallos observados:

1. Extracción estructural de registros semiestructurados: bloques, tablas, versiones temporales, nombres canónicos y joins posteriores.
2. Resolución de entidades con alta cobertura y control de colisiones: OCR 0/O, 1/I, 2/Z, 5/S, 6/G y 8/B; prefijos; separadores; mayúsculas; sufijos obsoletos; aliases y duplicados.

## Invariantes

- El candidato se congela antes de conocer consultas, validadores, ground truth o valores de evaluación.
- Puede leer la consulta en tiempo de ejecución, pero nunca validadores ni ground truth.
- Sin red, subprocess ni acceso lateral desde el candidato.
- Una sola ejecución adjudicable por conjunto fresco.
- Los resultados negativos se preservan; no se borran ni reinterpretan.
- Sin merge al tronco ni cambio de score hasta PASS externo.

## Gates previos obligatorios

1. Pruebas unitarias de normalización y parsing.
2. Pruebas metamórficas: variantes equivalentes deben producir la misma identidad y monto.
3. Pruebas adversariales de colisión: identidades distintas no deben fusionarse.
4. Pruebas de cobertura: recall alto con precisión explícita y casos ambiguos en cuarentena.
5. Prueba sintética multibase completa.
6. Auditoría estática de aislamiento y hashes.

## Gate externo fresco

- Seleccionar consultas no usadas previamente.
- Fijar commit del benchmark, datasets, dependencias y candidato por SHA-256.
- Ejecutar exactamente una vez.
- Publicar respuestas, validadores, hashes, logs y recibo de cadena de custodia.
- PASS solo si todas las consultas seleccionadas superan sus validadores oficiales.

## Regla de puntuación

Un PASS fresco aumenta la evidencia de dominancia; un FAIL conserva 465/1000 y define el siguiente frente de investigación. Ninguna demostración sintética, reejecución sobre consultas expuestas o mejora interna concede puntos por sí sola.
