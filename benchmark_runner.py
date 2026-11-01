#!/usr/bin/env python3
"""
Runner de carga (Python multiproceso). Ejecuta UNA repeticion de UNA celda de la matriz:
motor x perfil x query x concurrencia x run_number.

Ciclo dentro del runner: warmup (60 s, se ejecuta la carga pero no se mide) y medicion (300 s).
El flush de cache y el cooldown los hace run_benchmarks.sh antes y despues.

Escribe una fila en results/mediciones.csv con el esquema EXACTO del playbook (8.2)
y un log JSON con la evidencia (limites reales de Docker, version, errores, spill, OOM).
"""
import argparse
import csv
import json
import multiprocessing as mp
import os
import subprocess
import time

# numpy y requests se importan solo en el proceso principal (dentro de las funciones):
# en Windows cada cliente arranca un Python nuevo y cargarlas 50 veces llena la memoria.

ROOT = os.path.dirname(os.path.abspath(__file__))
QDIR = os.path.join(ROOT, "queries")
CSV_COLUMNS = [
    "timestamp_epoch", "engine", "profile", "query_id", "concurrency", "run_number",
    "throughput_qps", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
    "cpu_throttled_seconds", "max_rss_mb", "disk_spill", "status",
]
CONTAINER = {"mongodb": "bench-mongodb", "postgresql": "bench-postgresql"}
VARIANTS = json.load(open(os.path.join(QDIR, "variantes_q2.json")))
DB_NAME, COLLECTION = "enlaceseguro", "analisis"   # caso de uso adaptado (ver ADAPTACION.md)


# ---------------------------------------------------------------- consultas
def load_query(engine, query_id):
    base = "q1" if query_id == "Q1" else "q2"
    ext = "json" if engine == "mongodb" else "sql"
    with open(os.path.join(QDIR, f"{base}_{engine}.{ext}"), encoding="utf-8") as f:
        if ext == "sql":
            return f.read()
        from bson import json_util   # Extended JSON: convierte {"$date": ...} en fecha real de MongoDB
        return json_util.loads(f.read())


def make_executor(engine, query_id, args):
    """Devuelve una funcion sin argumentos que ejecuta la consulta completa una vez."""
    query = load_query(engine, query_id)
    variant = VARIANTS.get(query_id, {}).get(engine, {})
    if engine == "mongodb":
        from pymongo import MongoClient
        coll = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10000)[DB_NAME][COLLECTION]
        opts = {}
        if "allowDiskUse" in variant:
            opts["allowDiskUse"] = variant["allowDiskUse"]
        return lambda: list(coll.aggregate(query, **opts))
    import psycopg
    conn = psycopg.connect(args.pg_dsn, autocommit=True)
    if "work_mem" in variant:
        conn.execute(f"SET work_mem = '{variant['work_mem']}'")
    return lambda: conn.execute(query).fetchall()


def worker(engine, query_id, args, deadline, out_q):
    """Cliente concurrente: ejecuta la consulta en ciclo hasta el deadline.
    Reporta CADA consulta en cuanto termina, asi una consulta que se queda corriendo
    mucho despues de la ventana no hace perder las que ya se completaron."""
    try:
        run = make_executor(engine, query_id, args)
    except Exception as e:  # no pudo ni conectarse
        out_q.put(("e", (time.time(), f"connect: {type(e).__name__}: {e}"[:300])))
        out_q.put(("fin", None))
        return
    while time.time() < deadline:
        t0 = time.time()
        try:
            run()
            out_q.put(("s", (t0, time.time())))
        except Exception as e:
            out_q.put(("e", (time.time(), f"{type(e).__name__}: {e}"[:300])))
            if engine == "postgresql":  # conexion posiblemente rota: reconectar
                try:
                    run = make_executor(engine, query_id, args)
                except Exception:
                    time.sleep(1)
            else:
                time.sleep(0.2)
    out_q.put(("fin", None))


# ---------------------------------------------------------------- evidencia del entorno
def sh(*cmd, stderr=False):
    """Ejecuta un comando sin pasar por la shell (funciona igual en Windows, Linux y macOS)."""
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return (r.stdout + (r.stderr if stderr else "")).strip()


def docker_state(engine):
    raw = sh("docker", "inspect", CONTAINER[engine])
    try:
        d = json.loads(raw)[0]
    except (ValueError, IndexError):
        return {}
    hc = d["HostConfig"]
    return {
        "oom_killed": d["State"]["OOMKilled"],
        "running": d["State"]["Running"],
        "exit_code": d["State"]["ExitCode"],
        "image": d["Config"]["Image"],
        "limits_reales": {
            "cpus": hc.get("NanoCpus", 0) / 1e9,
            "memory_bytes": hc.get("Memory"),
            "memory_swap_bytes": hc.get("MemorySwap"),
            "memory_swappiness": hc.get("MemorySwappiness"),
        },
    }


def cgroup_cpu_stat(engine):
    """Lectura directa de cgroups v2 (respaldo de cAdvisor): cpu.stat del contenedor."""
    out = sh("docker", "exec", CONTAINER[engine], "cat", "/sys/fs/cgroup/cpu.stat")
    stats = dict(l.split() for l in out.splitlines() if len(l.split()) == 2)
    return {k: int(stats[k]) for k in ("throttled_usec", "usage_usec") if k in stats}


def cgroup_rss_bytes(engine):
    """RSS del contenedor desde cgroups v2: memoria anonima (anon) de memory.stat. Respaldo de cAdvisor."""
    out = sh("docker", "exec", CONTAINER[engine], "cat", "/sys/fs/cgroup/memory.stat")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "anon":
            return int(parts[1])
    return None


def stat_delta(before, after, key):
    if key in before and key in after:
        return (after[key] - before[key]) / 1e6
    return None


def prom_range(args, expr, start, end, step=5):
    """Serie de tiempo (para la curva de RSS en extras/)."""
    import requests
    try:
        r = requests.get(f"{args.prometheus}/api/v1/query_range",
                         params={"query": expr, "start": start, "end": end, "step": step}, timeout=10)
        res = r.json()["data"]["result"]
        return [[float(t) - start, float(v)] for t, v in res[0]["values"]] if res else []
    except Exception:
        return []


def engine_info(engine, args):
    try:
        if engine == "mongodb":
            from pymongo import MongoClient
            c = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
            st = c.admin.command("serverStatus")
            return {"version": st["version"],
                    "wiredtiger_cache_bytes": st["wiredTiger"]["cache"]["maximum bytes configured"]}
        import psycopg
        with psycopg.connect(args.pg_dsn) as conn:
            q = lambda s: conn.execute(s).fetchone()[0]
            return {"version": q("SELECT version()"), "shared_buffers": q("SHOW shared_buffers"),
                    "work_mem_default": q("SHOW work_mem")}
    except Exception as e:
        return {"error": str(e)[:200]}


def pg_temp_files(args):
    import psycopg
    try:
        with psycopg.connect(args.pg_dsn) as conn:
            return conn.execute(
                "SELECT temp_files, temp_bytes FROM pg_stat_database WHERE datname = current_database()").fetchone()
    except Exception:
        return None


def prom_query(args, expr, at):
    import requests
    try:
        r = requests.get(f"{args.prometheus}/api/v1/query", params={"query": expr, "time": at}, timeout=10)
        res = r.json()["data"]["result"]
        return float(res[0]["value"][1]) if res else None
    except Exception:
        return None


def detect_spill(engine, args, since_epoch, temp_before):
    if engine == "mongodb":
        # mongod deja en el log las consultas lentas (>100 ms) con "usedDisk":true cuando volco a disco
        logs = sh("docker", "logs", "--since", str(int(since_epoch)), CONTAINER[engine], stderr=True)
        n = logs.count('"usedDisk":true')
        return n > 0, {"lineas_usedDisk": n}
    after = pg_temp_files(args)
    if temp_before is None or after is None:
        return False, {"temp_files": None}
    files, nbytes = after[0] - temp_before[0], after[1] - temp_before[1]
    return files > 0, {"temp_files": files, "temp_bytes": nbytes}


def explain(engine, query_id, args):
    """MongoDB: explain("executionStats"); PostgreSQL: EXPLAIN (ANALYZE, BUFFERS). Con la misma variante de Q2."""
    query = load_query(engine, query_id)
    variant = VARIANTS.get(query_id, {}).get(engine, {})
    if engine == "mongodb":
        from bson import json_util
        from pymongo import MongoClient
        db = MongoClient(args.mongo_uri)[DB_NAME]
        cmd = {"explain": {"aggregate": COLLECTION, "pipeline": query, "cursor": {},
                           **({"allowDiskUse": variant["allowDiskUse"]} if "allowDiskUse" in variant else {})},
               "verbosity": "executionStats"}
        try:
            return json_util.dumps(db.command(cmd), indent=2)
        except Exception as e:
            return f"ERROR: {e}"
    import psycopg
    with psycopg.connect(args.pg_dsn, autocommit=True) as conn:
        if "work_mem" in variant:
            conn.execute(f"SET work_mem = '{variant['work_mem']}'")
        rows = conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + query).fetchall()
        return "\n".join(r[0] for r in rows)


# ---------------------------------------------------------------- principal
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=["mongodb", "postgresql"], required=True)
    p.add_argument("--profile", default="")
    p.add_argument("--explain", action="store_true",
                   help="solo imprime el plan de ejecucion (seccion 5 del reporte) y termina")
    p.add_argument("--query", choices=["Q1", "Q2_V1", "Q2_V2"], required=True)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--run", type=int, default=1)
    p.add_argument("--warmup", type=int, default=60)
    p.add_argument("--duration", type=int, default=300)
    p.add_argument("--out", default=os.path.join(ROOT, "results", "mediciones.csv"))
    p.add_argument("--mongo-uri", default=os.getenv("MONGO_URI", "mongodb://127.0.0.1:27018"))
    p.add_argument("--pg-dsn", default=os.getenv("PG_DSN", "postgresql://bench:bench@127.0.0.1:5433/bench"))
    p.add_argument("--prometheus", default=os.getenv("PROMETHEUS_URL", "http://localhost:9090"))
    args = p.parse_args()
    import numpy as np
    engine, cname = args.engine, CONTAINER[args.engine]
    if args.explain:
        print(explain(engine, args.query, args))
        return 0

    state_before = docker_state(engine)
    info = engine_info(engine, args)

    start = time.time()
    win_start = start + args.warmup
    win_end = win_start + args.duration
    q = mp.Queue()
    procs = [mp.Process(target=worker, args=(engine, args.query, args, win_end, q), daemon=True)
             for _ in range(args.concurrency)]
    print(f"[{engine} {args.profile} {args.query} c={args.concurrency} run={args.run}] "
          f"warmup {args.warmup}s + medicion {args.duration}s")
    for pr in procs:
        pr.start()

    # Al iniciar la ventana de medicion tomamos las lecturas "antes"
    time.sleep(max(0, win_start - time.time()))
    thr_before = cgroup_cpu_stat(engine)
    temp_before = pg_temp_files(args) if engine == "postgresql" else None
    # Muestreo propio de RSS cada 2 s (respaldo por si cAdvisor no reporta el contenedor)
    rss_cg_series = []
    while time.time() < win_end - 1:
        v = cgroup_rss_bytes(engine)
        if v is not None:
            rss_cg_series.append([round(time.time() - win_start, 1), v])
        time.sleep(max(0, min(2, win_end - time.time() - 1)))
    time.sleep(max(0, win_end - time.time()))
    thr_after = cgroup_cpu_stat(engine)

    # Recolectar resultados. Se espera hasta 120 s a que terminen las consultas que quedaron en vuelo;
    # las que sigan corriendo despues se cortan (terminaron fuera de la ventana, no cuentan).
    import queue as _queue
    samples, errors, fin = [], [], 0
    limite = win_end + 120
    while fin < len(procs) and time.time() < limite:
        try:
            tipo, dato = q.get(timeout=1)
        except _queue.Empty:
            continue
        if tipo == "s":
            samples.append(dato)
        elif tipo == "e":
            errors.append(dato)
        else:
            fin += 1
    cortados = len(procs) - fin
    for pr in procs:
        if pr.is_alive():
            pr.terminate()
        pr.join(timeout=5)
    while True:  # lo que haya quedado en la cola
        try:
            tipo, dato = q.get_nowait()
        except Exception:
            break
        if tipo == "s":
            samples.append(dato)
        elif tipo == "e":
            errors.append(dato)

    # Solo cuentan las consultas que TERMINARON dentro de la ventana de medicion
    lat = np.array([(e - s) * 1000 for s, e in samples if win_start <= e <= win_end])
    errs_window = [e for e in errors if win_start <= e[0] <= win_end + 120]
    pct = (lambda x: round(float(np.percentile(lat, x)), 2)) if len(lat) else (lambda x: "")

    # Telemetria: Prometheus/cAdvisor (fuente principal) y cgroup directo (respaldo/verificacion)
    sel = f'{{name="{cname}"}}'
    thr_prom = prom_query(args, f"increase(container_cpu_cfs_throttled_seconds_total{sel}[{args.duration}s])", win_end)
    rss_prom = prom_query(args, f"max_over_time(container_memory_rss{sel}[{args.duration}s])", win_end)
    thr_cg = stat_delta(thr_before, thr_after, "throttled_usec")
    throttled = thr_prom if thr_prom is not None else thr_cg
    # Extra (solo en el log, el CSV no cambia): CPU consumida y curva de RSS, para M3 y la grafica de RSS
    cpu_prom = prom_query(args, f"increase(container_cpu_usage_seconds_total{sel}[{args.duration}s])", win_end)
    cpu_cg = stat_delta(thr_before, thr_after, "usage_usec")
    rss_series = prom_range(args, f"container_memory_rss{sel}", win_start, win_end)
    rss_cg_max = max((v for _, v in rss_cg_series), default=None)
    rss_fuente = "prometheus_cadvisor" if rss_prom is not None else ("cgroup_memory_stat" if rss_cg_max is not None else None)
    if rss_prom is None:
        rss_prom = rss_cg_max
    if not rss_series:
        rss_series = rss_cg_series

    spill, spill_ev = detect_spill(engine, args, win_start, temp_before)
    state_after = docker_state(engine)
    oom = bool(state_after.get("oom_killed")) or (state_after and not state_after.get("running"))

    if oom:
        status = "oom"
    elif errs_window and len(lat) == 0:
        status = "error"
    elif spill:
        status = "spill"
    elif errs_window:
        status = "error"
    else:
        status = "ok"

    row = {
        "timestamp_epoch": int(win_start),
        "engine": engine,
        "profile": args.profile,
        "query_id": args.query,
        "concurrency": args.concurrency,
        "run_number": args.run,
        "throughput_qps": round(len(lat) / args.duration, 4),
        "latency_p50_ms": pct(50),
        "latency_p95_ms": pct(95),
        "latency_p99_ms": pct(99),
        "cpu_throttled_seconds": round(throttled, 3) if throttled is not None else "",
        "max_rss_mb": round(rss_prom / 1048576, 1) if rss_prom is not None else "",
        "disk_spill": str(spill).lower(),
        "status": status,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    new = not os.path.exists(args.out)
    with open(args.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)

    log = {
        "fila_csv": row,
        "motor": info,
        "docker_antes": state_before,
        "docker_despues": state_after,
        "ventana": {"inicio": win_start, "fin": win_end, "warmup_s": args.warmup, "medicion_s": args.duration},
        "consultas_completadas": int(len(lat)),
        "consultas_fuera_de_ventana": len(samples) - int(len(lat)),
        "errores_en_ventana": len(errs_window),
        "clientes_cortados_al_final": cortados,
        "ejemplos_error": [m for _, m in errs_window[:5]],
        "throttling": {"prometheus_s": thr_prom, "cgroup_cpu_stat_s": thr_cg},
        "rss_max_bytes": rss_prom,
        "rss_fuente": rss_fuente,
        "throttling_fuente": "prometheus_cadvisor" if thr_prom is not None else ("cgroup_cpu_stat" if thr_cg is not None else None),
        "cpu_usage_s": {"prometheus_s": cpu_prom, "cgroup_cpu_stat_s": cpu_cg},
        "rss_serie_bytes": rss_series,
        "spill": spill_ev,
    }
    log_dir = os.path.join(ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    name = f"{engine}_{args.profile}_{args.query}_c{args.concurrency}_r{args.run}.json"
    with open(os.path.join(log_dir, name), "w") as f:
        json.dump(log, f, indent=2, default=str)

    print(f"  -> qps={row['throughput_qps']} p95={row['latency_p95_ms']} p99={row['latency_p99_ms']} "
          f"throttled={row['cpu_throttled_seconds']} rss={row['max_rss_mb']}MB spill={row['disk_spill']} status={status}")
    return 0


if __name__ == "__main__":
    # Windows no tiene "fork"; ahi se usa "spawn" (cada cliente arranca su propio proceso de Python)
    mp.set_start_method(os.getenv("BENCH_MP", "spawn" if os.name == "nt" else "fork"))
    raise SystemExit(main())
