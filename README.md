# Medición de métricas en bases documentales: MongoDB vs PostgreSQL JSONB

Implementación del playbook "Medición de métricas en bases documentales" (Bases de Datos en la Nube, IT2iD, UPChiapas 2026), adaptada al caso EnlaceSeguro: colección `analisis` de la base `enlaceseguro`, con el resultado de cada revisión de un enlace sospechoso. Las equivalencias con el ejemplo de órdenes del playbook y la justificación de cada cambio están en `ADAPTACION.md`.

## Qué hay en el repositorio

```
docker-compose.yml            Motores + telemetría; los límites salen del perfil elegido
versions.env                  Versiones exactas de las imágenes (MongoDB 9.0.4, PostgreSQL 18.6)
profiles/                     PROFILE_A_BASELINE, PROFILE_B_MEDIUM, PROFILE_C_SEVERE
telemetry/prometheus.yml      cAdvisor + Node Exporter, scrape_interval 1s
ADAPTACION.md                 Por qué se usó EnlaceSeguro, forma del documento y cómo se adaptó cada consulta
synthetic_data_generator.py   Genera los 500 000 análisis (semilla fija) y los carga a cada motor
queries/                      Q1 y Q2 de MongoDB y SQL adaptadas a EnlaceSeguro
benchmark_runner.py           Runner en Python multiproceso: una repetición de una celda
run_benchmarks.sh             Recorre la matriz completa, reanudable
planes_ejecucion.sh           explain executionStats y EXPLAIN (ANALYZE, BUFFERS)
results/mediciones.csv        Una fila por repetición, esquema 8.2 del playbook
results/estado.json           Qué corridas ya terminaron (para reanudar)
logs/                         Evidencia por corrida: límites reales, versión, errores, spill, OOM
PASOS.md                      Lista de avance del trabajo manual
extras/                       Opcional: análisis automático, costo en la nube, monitor térmico (ver extras/README.md)
```

## Antes de empezar (Windows)

Todo se corre desde Windows con tres programas:

- **Docker Desktop**: levanta los contenedores. Por dentro usa una máquina virtual Linux con cgroups v2, que es la que pone los límites de CPU y memoria.
- **Python 3** para Windows (python.org), marcando "Add python.exe to PATH" al instalar.
- **Git para Windows** (git-scm.com), que trae **Git Bash**: la terminal donde se corren los scripts `.sh`.

**Memoria para Docker.** El perfil A le da 4 CPUs y 4 GB al motor, y además corren Prometheus, cAdvisor y el runner. Docker Desktop necesita bastante más que 4 GB; si no, el baseline ya estaría bajo contención. Docker Desktop toma sus recursos de WSL, así que se configuran en un archivo de Windows: Win + R, escribir `notepad %USERPROFILE%\.wslconfig` (decir que sí si pregunta si lo crea) y dejar:

```
[wsl2]
memory=10GB
processors=8
swap=2GB
```

Guardar, abrir PowerShell, ejecutar `wsl --shutdown` y volver a abrir Docker Desktop.

**Instalar las librerías de Python** (en Git Bash, dentro de la carpeta del proyecto):

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Cada vez que se abra una Git Bash nueva hay que volver a entrar a la carpeta y correr `source .venv/Scripts/activate`.

**Comprobaciones** (el script de la matriz también las hace solo):

```bash
docker info --format "{{.CgroupVersion}}"                  # debe imprimir 2
docker run --rm alpine:3.20 nproc                           # CPUs que ve Docker (8)
```

**Limpieza de caché.** El playbook pide `sync; echo 3 > /proc/sys/vm/drop_caches`. Eso solo existe en Linux, así que el script lo ejecuta dentro de un contenedor privilegiado: limpia la caché del kernel Linux de Docker Desktop, que es justo donde corren los motores. No se necesita sudo ni contraseña.

En Linux o WSL todo funciona igual; solo se usa `python3` en lugar de `python`.

**Descargar las imágenes** (una sola vez, unos 2 GB):

```bash
docker compose --env-file versions.env --env-file profiles/PROFILE_A_BASELINE.env --profile mongodb --profile postgresql --profile telemetry pull
docker pull alpine:3.20
```

**Puertos.** Los contenedores usan 27018 (MongoDB) y 5433 (PostgreSQL) en lugar de los puertos normales, para no chocar con un MongoDB o PostgreSQL instalado directo en Windows.

## 1. Datos

```bash
python synthetic_data_generator.py generate            # data/analisis.jsonl, unos 520 MB
md5sum data/analisis.jsonl                              # debe dar ee017c95c1cd435b16ff2091a2f1b7b9

# Cargar cada motor (con el perfil A para que cargue rápido)
docker compose --env-file versions.env --env-file profiles/PROFILE_A_BASELINE.env --profile mongodb up -d
python synthetic_data_generator.py load --engine mongodb
docker stop bench-mongodb

docker compose --env-file versions.env --env-file profiles/PROFILE_A_BASELINE.env --profile postgresql up -d
python synthetic_data_generator.py load --engine postgresql
docker stop bench-postgresql
```

Los datos quedan en volúmenes de Docker y sobreviven a los reinicios. Cambiar de perfil solo cambia los límites del contenedor, no los datos.

## 2. Celda piloto (diapositiva 13)

```bash
PILOTO=1 ./run_benchmarks.sh
cat results/piloto.csv
```

Hay que revisar que `cpu_throttled_seconds` y `max_rss_mb` tengan valor. Si salen vacíos, Prometheus no está viendo el contenedor: abrir http://localhost:9090 y buscar `container_memory_rss{name="bench-mongodb"}`.

## 3. Matriz completa

```bash
./run_benchmarks.sh
```

Son 2 motores × 3 perfiles × 3 consultas (Q1, Q2_V1, Q2_V2) × 3 concurrencias × 3 repeticiones = 162 corridas. Cada una dura unos 7.5 minutos (60 + 300 + 60 s más el reinicio del motor), en total cerca de 20 horas. Se puede partir en varias noches:

```bash
ENGINES=mongodb ./run_benchmarks.sh
ENGINES=postgresql ./run_benchmarks.sh
```

Si se corta (Ctrl+C, apagón, la laptop se suspende), basta con volver a ejecutar el mismo comando: `results/estado.json` sabe qué corridas terminaron y continúa con las que faltan. La laptop debe estar conectada a la corriente, con la suspensión desactivada (Configuración > Sistema > Energía) y con la ventana de Git Bash abierta mientras corre.

## 4. Planes de ejecución

```bash
./planes_ejecucion.sh PROFILE_A_BASELINE
./planes_ejecucion.sh PROFILE_C_SEVERE
```

## Decisiones que hay que poder explicar

- **Variantes de Q2 en el CSV.** El esquema 8.2 no tiene columna para la variante y no se pueden agregar columnas, así que va en el valor de `query_id`: `Q2_V1` = `allowDiskUse:false` / `work_mem 4MB`, `Q2_V2` = `allowDiskUse:true` / `work_mem 64MB` (`queries/variantes_q2.json`).
- **Swap.** En cgroups v2 Docker ignora `mem_swappiness`. Además, `docker compose config` no muestra el valor 0 (lo omite al imprimir). Se deja en 0 como pide el playbook y además `memswap_limit = mem_limit`, que es lo que de verdad impide usar swap. El valor que Docker aplicó realmente queda en cada log (`limits_reales.memory_swappiness` y `memory_swap_bytes`).
- **Flush de caché.** Se hace con un contenedor privilegiado (`docker run --privileged alpine ... drop_caches`) para que funcione igual en Windows y Linux. `drop_caches` limpia la caché de Linux, pero no la caché interna de WiredTiger ni los `shared_buffers` de Postgres. Por eso en cada repetición el motor se detiene y se vuelve a arrancar.
- **Throttling.** Fuente principal: `increase(container_cpu_cfs_throttled_seconds_total[300s])` de cAdvisor. Como verificación, el runner también lee `throttled_usec` de `/sys/fs/cgroup/cpu.stat` del contenedor al inicio y al final de la ventana; las dos lecturas quedan en el log.
- **RSS.** cAdvisor publica el KPI `container_memory_rss_bytes` con el nombre `container_memory_rss`; se toma el máximo de la ventana de 300 s.
- **Spill.** MongoDB: líneas `"usedDisk":true` en el log de consultas lentas. PostgreSQL: aumento de `temp_files` en `pg_stat_database`, y además `log_temp_files=0` deja cada archivo temporal en el log como evidencia.
- **OOM.** `docker inspect` → `State.OOMKilled`. Los contenedores tienen `restart: "no"` para que un OOM no se esconda con un reinicio automático.
- **Latencias.** Solo cuentan las consultas que terminaron dentro de los 300 s de medición; lo del warmup se descarta. `throughput_qps` = consultas terminadas / 300.

## Resultados

La matriz completa (162 corridas) se ejecutó del 31 de octubre al 1 de noviembre de 2026 en una laptop con Windows y Docker Desktop. El CSV de mediciones, los logs por corrida, los planes de ejecución y el reporte se entregan aparte del repositorio.

**Telemetría en esa ejecución.** cAdvisor 0.52.1 no reconoce contenedores cuando Docker Desktop guarda las imágenes con containerd ("failed to identify the read-write layer ID"). Por eso el runner lee el throttling y la CPU de `cpu.stat` y la memoria de `memory.stat` (campo `anon`) directo del cgroup v2 de cada contenedor. Cada log dice de dónde salió cada métrica (`throttling_fuente`, `rss_fuente`).

## Extras

En `extras/` hay herramientas opcionales que no cambian la práctica: análisis automático del CSV con las gráficas del reporte, confiabilidad de las repeticiones, costo en AWS y monitor de temperatura de la laptop. Ver `extras/README.md`. El runner guarda, solo en el log JSON de cada corrida, la CPU consumida y la curva de RSS que usan estos extras; el CSV no cambia.
