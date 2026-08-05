# Data Science fresh gate v1

Este módulo prepara un candidato nuevo para un gate externo fresco de DataAgentBench. No contiene respuestas, constantes ni lógica específica de las seis consultas previamente expuestas.

## Frentes

### 1. Resolución de entidades

- normalización Unicode y de etiquetas/prefijos;
- firmas conservadoras y firmas tolerantes a OCR;
- distancia de edición ponderada para `0/O`, `1/I/L`, `2/Z`, `5/S`, `6/G` y `8/B`;
- generación de candidatos por bloques para evitar comparación cuadrática innecesaria;
- asignación uno-a-uno con requisito de mejor coincidencia mutua;
- umbral mínimo y margen contra el segundo candidato;
- cuarentena de ambigüedades;
- exclusión explícita de registros superseded `_OLD`.

### 2. Extracción estructural temporal

- bloques `clave: valor`;
- tablas Markdown;
- estructuras JSON/Python literales;
- canonicalización conservadora de nombres de proyecto;
- selección del reporte más reciente en o antes de una fecha de corte;
- agregación de financiación por identidad canónica;
- deduplicación estable con trazabilidad.

## Regla científica

Estas pruebas internas no conceden puntos. Solo permiten congelar un candidato antes de un conjunto externo fresco. El score canónico continúa en `465/1000` hasta un PASS externo reproducible.

## Ejecución

```bash
python -m unittest discover -s data_science_dominance/fresh_gate_v1/tests -v
```
