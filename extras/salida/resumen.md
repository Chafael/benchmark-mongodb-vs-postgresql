# Resumen automatico de resultados

Filas en el CSV: 162. Celdas: 54. Repeticiones por celda: 3 a 3.

## Estabilidad entre repeticiones

Se considera inestable una celda cuyo throughput o P99 varia mas de 10% entre sus 3 repeticiones (coeficiente de variacion = desviacion estandar / media). En esas celdas conviene repetir la medicion o explicar la causa en el reporte.

- mongodb / PROFILE_B_MEDIUM / Q2_V2 / 10 clientes: CV qps 23%, CV P99 1%
- mongodb / PROFILE_C_SEVERE / Q2_V2 / 1 clientes: CV qps 1%, CV P99 11%
- postgresql / PROFILE_A_BASELINE / Q1 / 10 clientes: CV qps 10%, CV P99 36%
- postgresql / PROFILE_B_MEDIUM / Q1 / 1 clientes: CV qps 39%, CV P99 23%
- postgresql / PROFILE_B_MEDIUM / Q1 / 10 clientes: CV qps 12%, CV P99 8%
- postgresql / PROFILE_B_MEDIUM / Q1 / 50 clientes: CV qps 0%, CV P99 34%
- postgresql / PROFILE_C_SEVERE / Q1 / 1 clientes: CV qps 16%, CV P99 17%
- postgresql / PROFILE_C_SEVERE / Q1 / 10 clientes: CV qps 61%, CV P99 17%

## Spill, OOM y errores

- postgresql / PROFILE_A_BASELINE / Q1 / 1 clientes: spill:3
- postgresql / PROFILE_A_BASELINE / Q1 / 10 clientes: spill:3
- postgresql / PROFILE_A_BASELINE / Q1 / 50 clientes: error:3
- postgresql / PROFILE_B_MEDIUM / Q1 / 1 clientes: spill:3
- postgresql / PROFILE_B_MEDIUM / Q1 / 10 clientes: spill:3
- postgresql / PROFILE_B_MEDIUM / Q1 / 50 clientes: spill:3
- postgresql / PROFILE_C_SEVERE / Q1 / 1 clientes: spill:3
- postgresql / PROFILE_C_SEVERE / Q1 / 10 clientes: spill:3
- postgresql / PROFILE_C_SEVERE / Q1 / 50 clientes: oom:3

## M3: huella por cada 1 000 documentos (perfil y concurrencia 1)

- mongodb / PROFILE_A_BASELINE / Q1: 3.26 ms de CPU, 1.129 MB de RSS
- mongodb / PROFILE_A_BASELINE / Q2_V1: 0.91 ms de CPU, 1.130 MB de RSS
- mongodb / PROFILE_A_BASELINE / Q2_V2: 0.92 ms de CPU, 1.127 MB de RSS
- mongodb / PROFILE_B_MEDIUM / Q1: 3.38 ms de CPU, 1.178 MB de RSS
- mongodb / PROFILE_B_MEDIUM / Q2_V1: 2.63 ms de CPU, 1.265 MB de RSS
- mongodb / PROFILE_B_MEDIUM / Q2_V2: 2.64 ms de CPU, 1.260 MB de RSS
- mongodb / PROFILE_C_SEVERE / Q1: 3.61 ms de CPU, 0.761 MB de RSS
- mongodb / PROFILE_C_SEVERE / Q2_V1: 9.23 ms de CPU, 0.753 MB de RSS
- mongodb / PROFILE_C_SEVERE / Q2_V2: 9.23 ms de CPU, 0.768 MB de RSS
- postgresql / PROFILE_A_BASELINE / Q1: 8.37 ms de CPU, 0.206 MB de RSS
- postgresql / PROFILE_A_BASELINE / Q2_V1: 1.35 ms de CPU, 0.023 MB de RSS
- postgresql / PROFILE_A_BASELINE / Q2_V2: 1.38 ms de CPU, 0.023 MB de RSS
- postgresql / PROFILE_B_MEDIUM / Q1: 8.18 ms de CPU, 0.203 MB de RSS
- postgresql / PROFILE_B_MEDIUM / Q2_V1: 1.31 ms de CPU, 0.023 MB de RSS
- postgresql / PROFILE_B_MEDIUM / Q2_V2: 1.32 ms de CPU, 0.021 MB de RSS
- postgresql / PROFILE_C_SEVERE / Q1: 9.54 ms de CPU, 0.202 MB de RSS
- postgresql / PROFILE_C_SEVERE / Q2_V1: 1.30 ms de CPU, 0.022 MB de RSS
- postgresql / PROFILE_C_SEVERE / Q2_V2: 1.30 ms de CPU, 0.022 MB de RSS

## Costo estimado en la nube (AWS Fargate, us-east-1)

Precio usado: USD 0.04048 por vCPU-hora y USD 0.004445 por GB-hora. Costo por millon de consultas = costo por hora / consultas por hora x 1 000 000.

- mongodb Q1: lo mas barato fue PROFILE_C_SEVERE con 1 clientes, USD 22.55 por millon de consultas
- mongodb Q2_V1: lo mas barato fue PROFILE_A_BASELINE con 10 clientes, USD 6.94 por millon de consultas
- mongodb Q2_V2: lo mas barato fue PROFILE_A_BASELINE con 10 clientes, USD 7.03 por millon de consultas
- postgresql Q1: lo mas barato fue PROFILE_A_BASELINE con 1 clientes, USD 95.99 por millon de consultas
- postgresql Q2_V1: lo mas barato fue PROFILE_C_SEVERE con 1 clientes, USD 8.12 por millon de consultas
- postgresql Q2_V2: lo mas barato fue PROFILE_C_SEVERE con 10 clientes, USD 8.09 por millon de consultas

## Graficas generadas

- p99_vs_concurrencia.png
- throttling_vs_qps.png
- rss_vs_concurrencia.png
- curva_rss_tiempo.png
