# Extras

Nada de esta carpeta cambia la práctica. El CSV, el runner y el script de la matriz funcionan igual con o sin ella. Sirve para escribir el reporte más rápido y con más argumentos.

## 1. Análisis automático del CSV

```bash
python extras/analizar_resultados.py
```

Lee `results/mediciones.csv` y deja en `extras/salida/`:

- `tabla_consolidada.csv`: mediana de las 3 repeticiones de cada celda. Va en la sección 3 del reporte.
- `p99_vs_concurrencia.png`, `throttling_vs_qps.png` y `rss_vs_concurrencia.png`: las tres gráficas que pide la sección 4.
- `curva_rss_tiempo.png`: la RAM segundo a segundo durante la medición, con el límite del perfil marcado en rojo. Usa los logs.
- `huella_m3.csv`: la respuesta a M3, cuánta CPU (ms) y cuánta memoria (MB) cuesta cada 1 000 documentos procesados. La CPU sale de los logs.
- `resumen.md`: lista de hallazgos para redactar a partir de ellos.

Las tablas y las tres gráficas obligatorias salen solo del CSV. Así se puede demostrar lo que pidió el profe: con el CSV basta para rehacer el reporte.

## 2. Confiabilidad de las repeticiones

Va dentro del mismo script. Para cada celda calcula el coeficiente de variación (desviación estándar entre la media) del throughput y del P99 de sus 3 repeticiones. Si alguno pasa de 10 %, la celda se marca como inestable en `tabla_consolidada.csv` (columna `estable`) y en `resumen.md`. Así se contesta la pregunta 5 del revisor con datos. También avisa si alguna celda quedó con menos de 3 repeticiones.

## 3. Costo en la nube

Cada perfil se valúa con los precios de AWS Fargate (USD 0.04048 por vCPU-hora y USD 0.004445 por GB-hora, us-east-1, consultados el 31 de octubre de 2026), porque Fargate deja pedir exactamente 4/4, 2/2 o 1/1. Con el throughput medido calcula cuánto costaría un millón de consultas en cada perfil: `costo_nube.csv`. Sirve para la sección 7 de recomendaciones, por ejemplo para ver si conviene pagar más recursos o si el perfil chico sale más barato por consulta aunque sea más lento.

## 4. Vigilar la temperatura de la laptop

Si el procesador se calienta, Windows le baja la velocidad y las mediciones de ese rato salen más lentas por culpa de la laptop, no del motor. Mientras corre la matriz, deja abierta una ventana de PowerShell con:

```powershell
powershell -ExecutionPolicy Bypass -File extras\monitor_cpu_windows.ps1
```

Registra cada 5 s el rendimiento real del CPU, su frecuencia y la temperatura en `extras\monitor_cpu.csv`. Al analizar, el script cruza esos datos con la ventana de cada corrida y marca como sospechosas las que tuvieron el CPU por debajo del 85 % de su rendimiento normal o a 90 °C o más (`revision_termica.csv`). Esas corridas se pueden repetir borrando su línea de `results/estado.json` y de `mediciones.csv`. Muchas laptops no exponen la temperatura; en ese caso la columna sale vacía y la revisión usa solo el rendimiento.
