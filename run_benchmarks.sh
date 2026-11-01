#!/usr/bin/env bash
# Automatizacion de la matriz de mediciones (playbook, secciones 6 y 8.1).
#
#   ./run_benchmarks.sh                 # corre todo lo que falte (reanuda solo)
#   ENGINES=mongodb PROFILES=PROFILE_A_BASELINE ./run_benchmarks.sh   # un pedazo de la matriz
#   PILOTO=1 ./run_benchmarks.sh        # celda piloto: mongodb x A x Q1 x c=1 x 1 run, tiempos cortos
#
# Ciclo por repeticion: detener motor -> flush de cache del SO -> arrancar motor ->
#   warmup 60 s -> medicion 300 s -> cooldown 60 s
# El avance se guarda en results/estado.json. Si se interrumpe (Ctrl+C, apagon, se durmio la laptop),
# al volver a ejecutar el script se salta lo que ya termino y sigue donde se quedo.

set -uo pipefail
cd "$(dirname "$0")"
# Funciona en Linux/WSL y en Windows con Git Bash + Docker Desktop.
export MSYS_NO_PATHCONV=1   # evita que Git Bash convierta rutas como /sys/fs/cgroup en rutas de Windows

ENGINES=${ENGINES:-"mongodb postgresql"}
PROFILES=${PROFILES:-"PROFILE_A_BASELINE PROFILE_B_MEDIUM PROFILE_C_SEVERE"}
QUERIES=${QUERIES:-"Q1 Q2_V1 Q2_V2"}
CONCURRENCIES=${CONCURRENCIES:-"1 10 50"}
RUNS=${RUNS:-"1 2 3"}
WARMUP=${WARMUP:-60}
DURATION=${DURATION:-300}
COOLDOWN=${COOLDOWN:-60}
OUT=${OUT:-results/mediciones.csv}
STATE=results/estado.json
if [[ -z "${PY:-}" ]]; then   # en Windows el comando suele ser "python"; en Linux "python3"
  if python3 -c "" > /dev/null 2>&1; then PY=python3; else PY=python; fi
fi

if [[ "${PILOTO:-0}" == "1" ]]; then
  ENGINES=mongodb; PROFILES=PROFILE_A_BASELINE; QUERIES=Q1; CONCURRENCIES=1; RUNS=1
  WARMUP=10; DURATION=30; COOLDOWN=5; OUT=results/piloto.csv; STATE=results/estado_piloto.json
fi

compose() { docker compose --env-file versions.env --env-file "profiles/$1.env" "${@:2}"; }
log() { echo "[$(date '+%F %T')] $*"; }

mkdir -p results logs
[[ -f "$STATE" ]] || echo '{"completadas": [], "fallidas": []}' > "$STATE"

state_has() { $PY -c "import json,sys; d=json.load(open('$STATE')); sys.exit(0 if '$1' in d['completadas'] else 1)"; }
state_add() {
  $PY - "$STATE" "$1" "$2" <<'EOF'
import json, sys, time
path, key, field = sys.argv[1:]
d = json.load(open(path))
d.setdefault(field, [])
if key not in d[field]:
    d[field].append(key)
d["actualizado"] = time.strftime("%Y-%m-%d %H:%M:%S")
json.dump(d, open(path, "w"), indent=2)
EOF
}

flush_cache() {
  # "sync; echo 3 > /proc/sys/vm/drop_caches" (playbook, seccion 6) ejecutado en un contenedor privilegiado:
  # limpia la cache del kernel Linux donde corren los contenedores (la VM de Docker Desktop en Windows,
  # o el propio Linux), sin necesitar sudo en el host.
  if ! docker run --rm --privileged alpine:3.20 sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' > /dev/null 2>&1; then
    log "AVISO: no se pudo limpiar la cache del SO."; return 1
  fi
}

wait_ready() {
  local engine=$1
  for _ in $(seq 1 120); do
    if [[ $engine == mongodb ]]; then
      docker exec bench-mongodb mongosh --quiet --eval 'db.runCommand({ping:1}).ok' 2>/dev/null | grep -q 1 && return 0
    else
      docker exec bench-postgresql pg_isready -U bench -d bench > /dev/null 2>&1 && return 0
    fi
    sleep 1
  done
  log "ERROR: $engine no respondio en 120 s"; return 1
}

# ---------- verificaciones previas ----------
CG=$(docker info --format '{{.CgroupVersion}}' 2>/dev/null)
[[ "$CG" == "2" ]] && log "cgroups v2 confirmado" || log "AVISO: Docker no usa cgroups v2 (CgroupVersion='$CG')."
compose PROFILE_A_BASELINE --profile telemetry up -d > /dev/null
curl -sf http://localhost:9090/-/ready > /dev/null || log "AVISO: Prometheus no responde en :9090"

total=0; for e in $ENGINES; do for p in $PROFILES; do for q in $QUERIES; do for c in $CONCURRENCIES; do for r in $RUNS; do total=$((total+1)); done; done; done; done; done
n=0

for engine in $ENGINES; do
  other=$([[ $engine == mongodb ]] && echo postgresql || echo mongodb)
  docker stop "bench-$other" > /dev/null 2>&1   # un solo motor a la vez
  for profile in $PROFILES; do
    log "== $engine con $profile: recreando contenedor con los limites del perfil =="
    compose "$profile" --profile "$engine" up -d --force-recreate "$engine" > /dev/null
    wait_ready "$engine" || exit 1
    for query in $QUERIES; do
      for conc in $CONCURRENCIES; do
        for run in $RUNS; do
          n=$((n+1))
          key="$engine|$profile|$query|$conc|$run"
          if state_has "$key"; then log "($n/$total) ya hecha: $key"; continue; fi
          log "($n/$total) $key"

          # 1) flush de cache: detener el motor (vacia su cache interna) y limpiar la del SO
          docker stop "bench-$engine" > /dev/null
          flush_cache
          docker start "bench-$engine" > /dev/null
          wait_ready "$engine" || { state_add "$key" fallidas; continue; }

          # 2) warmup + 3) medicion (dentro del runner)
          if $PY benchmark_runner.py --engine "$engine" --profile "$profile" --query "$query" \
               --concurrency "$conc" --run "$run" --warmup "$WARMUP" --duration "$DURATION" --out "$OUT"; then
            state_add "$key" completadas
          else
            state_add "$key" fallidas
          fi

          # 4) cooldown
          sleep "$COOLDOWN"
        done
      done
    done
  done
  docker stop "bench-$engine" > /dev/null 2>&1
done

log "Matriz terminada. Resultados en $OUT, evidencia en logs/, avance en $STATE"
