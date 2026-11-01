SELECT data->>'_id' AS analisis_id,
       data->>'urlInicial' AS url_inicial,
       data->'veredicto'->>'categoria' AS categoria,
       (data->>'duracionMs')::numeric AS duracion_ms
FROM analisis
WHERE data->>'estado' = 'completo'
  AND (data->>'fecha')::timestamptz >= '2026-01-01 00:00:00Z'
ORDER BY (data->>'duracionMs')::numeric DESC
LIMIT 1000;
