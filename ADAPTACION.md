# Adaptación del playbook al caso EnlaceSeguro

El playbook usa como ejemplo una colección de órdenes de compra. Esas consultas eran de muestra y había que proponer un caso de uso propio y ajustarlas. Usé EnlaceSeguro, el proyecto de la app que revisa enlaces sospechosos antes de abrirlos (repositorio `ArturoYJ/Enlace-Seguro`). El proyecto es en equipo; esta práctica y sus decisiones son individuales.

## Por qué este caso encaja

El repositorio tiene una decisión abierta: la propuesta original dice PostgreSQL 16 y el ejercicio de modelado dice MongoDB (`Context/architecture/system.json`, nodo `database-engine` con estado `unknown`). Esta práctica compara justo esos dos motores guardando documentos, así que los resultados sirven como evidencia para esa decisión.

Además, el resultado de un análisis es un documento anidado por naturaleza. El patrón P3 ("Registrar resultado completo de análisis") pide guardar usuario, URL inicial, fecha, veredicto con razones, redirecciones, señales, captura y la respuesta o el fallo de cada fuente de reputación. P5 ("Consultar detalle de un análisis") lee todo eso junto.

## Forma del documento

El repositorio todavía no tiene esquema físico (`database/schema/README.md`). La forma del documento es mi propuesta y sale de los datos que piden P3 y P5 y de los requisitos de la propuesta:

```
analisis {
  _id, usuarioId, urlInicial, destinoFinal, fecha,
  estado: "completo" | "parcial",
  duracionMs,
  veredicto: { categoria, razones[] },
  redirecciones: [ { url, codigoHttp } ],
  senales: [ ... ],
  captura: { uri, ancho, alto },
  fuentes: [ { nombre, estado, latenciaMs, consultadoEn, respuesta: { detecciones, categoria } } ]
}
```

De dónde sale cada campo que no está escrito tal cual en P3:

- `estado` (completo/parcial): el requisito "un fallo de proveedor debe quedar visible como resultado parcial/no concluyente".
- `fuentes[].estado` y `latenciaMs`: P3 pide guardar "respuestas/fallos de fuentes", y las fuentes dependen de "credenciales, cuotas y disponibilidad".
- `fuentes[].respuesta.detecciones`: el "desglose de fuentes" que muestra P5.
- `duracionMs`: el requisito de "límites de tiempo/recursos" del sandbox; sin guardar la duración no hay forma de revisar si esos límites están bien puestos.
- Las categorías del veredicto (peligroso, sospechoso, sin amenazas detectadas) son las del glosario del proyecto.

Los datos son sintéticos, como dice el propio CSV de patrones. Los dominios usan los TLD reservados `.test` y `.example`, así ningún documento apunta a un sitio real.

## Equivalencias con el playbook

- Colección `orders` → colección `analisis` de la base `enlaceseguro`. En PostgreSQL, tabla `analisis (id UUID PRIMARY KEY, data JSONB)`.
- 500 000 órdenes → 500 000 análisis.
- `items` (promedio 3) → `fuentes` (de 0 a 4 por análisis según credenciales y cuota; promedio 3).
- Tercer nivel: `customer.geo` → `fuentes[].respuesta`.
- `timestamp` → `fecha`.
- `payment.status = "completed"` → `estado = "completo"`.
- `payment.final_total` (lo que se ordena en Q2) → `duracionMs`.
- `payment.gateway_latency_ms` → `fuentes[].latenciaMs`, que además ya estaba en el ejemplo como métrica de latencia de un servicio externo.
- Índice simple en `timestamp` → índice simple en `fecha`.
- Índice simple en `order_id` → índice simple en `usuarioId`, el que necesita el historial personal (P4). El `_id` lo indexa MongoDB solo.

## Q1: desanidar, filtrar y agrupar (saturación de CPU)

Pregunta de operación: por cada fuente de reputación y cada categoría de veredicto, cuántas detecciones dio, cuál fue su latencia promedio y cuántas consultas respondió bien. Sirve para ver qué fuente es más lenta y cuál aporta más detecciones, lo que ayuda a decidir tiempos de espera y prioridades entre proveedores.

Conserva la forma de la consulta del playbook:

- `$unwind` de `fuentes`, igual que el de `items`.
- El filtro `price > 50` pasa a `fuentes.estado = "ok"`: se descartan las respuestas fallidas, que no traen detecciones.
- Se agrupa por fuente y categoría en lugar de país y categoría, con una suma, un promedio y un conteo, como en el original.

Salen 12 grupos (4 fuentes por 3 categorías).

## Q2: ordenamiento masivo y Top-1000 (estrés de buffer)

Pregunta de operación: los 1000 análisis completos más lentos desde el 1 de enero de 2026. Sirve para revisar qué tipo de enlaces se acercan al límite de tiempo del sandbox.

Conserva la forma: filtro de igualdad más rango de fecha, orden descendente sin índice sobre el campo ordenado (`duracionMs`), `LIMIT 1000` y proyección de pocos campos. Las variantes de memoria no cambian: `allowDiskUse` false/true en MongoDB y `work_mem` 4 MB/64 MB en PostgreSQL. El 37 % de los análisis pasa el filtro, cerca del 32 % que pasaba en el ejemplo de órdenes.

## Detalles de la migración de datos entre motores

- El generador escribe Extended JSON v2 (`$oid`, `$date`). En MongoDB se carga con tipos reales (ObjectId y Date), y la colección se crea con un validador `$jsonSchema` con la forma de arriba, así que un documento mal formado haría fallar la carga.
- JSONB no tiene tipo fecha ni ObjectId. En PostgreSQL las fechas quedan como texto ISO-8601 y los ObjectId como texto hexadecimal. Por eso la consulta SQL convierte la fecha con `::timestamptz` antes de compararla.
- El `id UUID` de PostgreSQL se deriva del `_id` de MongoDB (UUID v5): cada documento tiene siempre el mismo id en las dos bases y entre cargas.

## Comprobación de que las consultas son equivalentes

Con una muestra de 30 000 análisis comparé el resultado de las dos versiones de cada consulta. En Q1 coinciden los 12 grupos con sus sumas, promedios y conteos. En Q2 coinciden los 1000 análisis y su orden por duración.
