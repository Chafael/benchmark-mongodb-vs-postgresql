# Pasos de la práctica (marcar con [x] al terminar)

El avance de las 162 corridas lo lleva solo `results/estado.json`. Esta lista es para el trabajo manual.

## 0. Prerrequisitos
- [x] Docker Desktop, Python 3 y Git para Windows instalados
- [x] `.wslconfig` con 10 GB y `wsl --shutdown` (ver README, "Antes de empezar")
- [x] `docker info --format "{{.CgroupVersion}}"` devuelve `2`
- [x] Entorno de Python con `pip install -r requirements.txt`
- [x] Imágenes descargadas (`docker compose ... pull`)

## 1. Datos
- [x] `python synthetic_data_generator.py generate` (500 000 análisis, unos 45 s)
- [x] md5 del archivo anotado para el reporte: `md5sum data/analisis.jsonl`
- [x] Carga en MongoDB e índices
- [x] Carga en PostgreSQL e índice

## 2. Celda piloto
- [x] `PILOTO=1 ./run_benchmarks.sh`
- [x] Revisar `results/piloto.csv`: 14 columnas, throttling y RSS con valor
- [x] Revisar `logs/mongodb_PROFILE_A_BASELINE_Q1_c1_r1.json`: límites reales, versión

## 3. Matriz completa
- [x] MongoDB (`ENGINES=mongodb ./run_benchmarks.sh`)
- [x] PostgreSQL (`ENGINES=postgresql ./run_benchmarks.sh`)

## 4. Planes de ejecución
- [x] `./planes_ejecucion.sh PROFILE_A_BASELINE` y `./planes_ejecucion.sh PROFILE_C_SEVERE`

## 5. Reporte
- [x] Gráficas y tablas desde `results/mediciones.csv`
- [x] Las 7 secciones del playbook
