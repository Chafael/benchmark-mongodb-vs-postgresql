SELECT fuente->>'nombre' AS fuente,
       data->'veredicto'->>'categoria' AS categoria,
       SUM((fuente->'respuesta'->>'detecciones')::numeric) AS detecciones_totales,
       AVG((fuente->>'latenciaMs')::numeric) AS latencia_promedio_ms,
       COUNT(*) AS consultas
FROM analisis, jsonb_array_elements(data->'fuentes') AS fuente
WHERE fuente->>'estado' = 'ok'
GROUP BY 1, 2;
