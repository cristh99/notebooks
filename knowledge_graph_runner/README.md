# Knowledge Graph Public Runner

Ejecutor público y gratuito para actualizar diariamente el grafo derivado del Knowledge Base de Notion sin consumir minutos privados ni persistir contenido privado en este repositorio.

## Seguridad

- El repositorio contiene únicamente código genérico y un paquete portable auditado.
- Cada corrida reconstruye el grafo en el disco efímero del runner y elimina la salida al terminar.
- No se suben artefactos, títulos, URLs, relaciones ni cuerpos de Notion.
- La única escritura permitida es un recibo agregado en `Ejecuciones del grafo derivado`.
- No modifica páginas canónicas, bases de conocimiento ni relaciones curadas.

## Activación

Crear en este repositorio el secreto de Actions `NOTION_GRAPH_TOKEN` con una integración de Notion que pueda:

1. leer `Classifier` y sus descendientes visibles;
2. crear páginas solamente en `Ejecuciones del grafo derivado`.

El workflow descubre por título la raíz `Classifier` y la data source de recibos. Si existen duplicados, permisos incompletos o fallos estructurales, termina cerrado (`BLOCKED`) en lugar de inventar cobertura.

## Ejecución

- Automática: todos los días a las `08:17 UTC`.
- Manual: pestaña **Actions → Knowledge Graph Public Runner → Run workflow**.
- Costo adicional configurado: **USD 0**.
