#!/usr/bin/env bash
# Planes de ejecucion para la seccion 5 del reporte:
#   MongoDB: explain("executionStats")   PostgreSQL: EXPLAIN (ANALYZE, BUFFERS)
# Uso: ./planes_ejecucion.sh PROFILE_A_BASELINE      (guarda en logs/planes/)
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash en Windows: no convertir rutas de Linux
cd "$(dirname "$0")"
PROFILE=${1:?Indica el perfil, ej. PROFILE_C_SEVERE}
OUT=logs/planes; mkdir -p "$OUT"
if [[ -z "${PY:-}" ]]; then
  if python3 -c "" > /dev/null 2>&1; then PY=python3; else PY=python; fi
fi
compose() { docker compose --env-file versions.env --env-file "profiles/$PROFILE.env" "$@"; }

for engine in mongodb postgresql; do
  other=$([[ $engine == mongodb ]] && echo postgresql || echo mongodb)
  docker stop "bench-$other" > /dev/null 2>&1 || true
  compose --profile "$engine" up -d --force-recreate "$engine" > /dev/null
  for _ in $(seq 1 120); do
    if [[ $engine == mongodb ]]; then
      docker exec bench-mongodb mongosh --quiet --eval 'db.runCommand({ping:1}).ok' 2>/dev/null | grep -q 1 && break
    else
      docker exec bench-postgresql pg_isready -U bench -d bench > /dev/null 2>&1 && break
    fi
    sleep 1
  done
  for q in Q1 Q2_V1 Q2_V2; do
    f="$OUT/${engine}_${PROFILE}_${q}.txt"
    $PY benchmark_runner.py --engine "$engine" --query "$q" --explain > "$f" 2>&1
    echo "$engine $q -> $f"
  done
  docker stop "bench-$engine" > /dev/null
done
