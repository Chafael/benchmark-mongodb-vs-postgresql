#!/usr/bin/env python3
"""
Analisis automatico de results/mediciones.csv (extra, no modifica nada de la practica).

  python3 extras/analizar_resultados.py
  python3 extras/analizar_resultados.py --csv results/mediciones.csv --logs logs --monitor extras/monitor_cpu.csv

Genera en extras/salida/:
  tabla_consolidada.csv      mediana de las 3 repeticiones por celda + variacion entre repeticiones
  huella_m3.csv              M3: CPU y memoria por cada 1 000 documentos procesados
  costo_nube.csv             costo estimado por millon de consultas en AWS Fargate
  p99_vs_concurrencia.png    grafica 1 de la seccion 4 del reporte
  throttling_vs_qps.png      grafica 2
  rss_vs_concurrencia.png    grafica 3 (desde el CSV)
  curva_rss_tiempo.png       curva de RSS en el tiempo (solo si hay logs con la serie)
  resumen.md                 hallazgos para redactar el reporte

Solo necesita el CSV para las tablas y las 3 graficas: es la prueba que pidio el profe
("si me llevo solo el CSV, ¿puedo rehacer el reporte?"). Los logs y el monitor de CPU son opcionales.
"""
import argparse
import glob
import json
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import logging
warnings.filterwarnings("ignore", message="findfont")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams["font.family"] = ["Arial", "Liberation Sans", "DejaVu Sans"]  # Arial si existe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_POR_CONSULTA = 500_000   # cada ejecucion recorre la coleccion completa (dataset del playbook)
UMBRAL_CV = 0.10              # variacion entre repeticiones mayor a 10 % = celda inestable

# Precios AWS Fargate Linux/x86, us-east-1 (consultados el 31-oct-2026 en aws.amazon.com/fargate/pricing).
# Fargate permite pedir exactamente la CPU y memoria de cada perfil, por eso se usa como referencia.
PRECIO_VCPU_HORA = 0.04048
PRECIO_GB_HORA = 0.004445

PROFILE_ORDER = ["PROFILE_A_BASELINE", "PROFILE_B_MEDIUM", "PROFILE_C_SEVERE"]
PROFILE_LABEL = {"PROFILE_A_BASELINE": "A (4 CPU, 4 GB)", "PROFILE_B_MEDIUM": "B (2 CPU, 2 GB)",
                 "PROFILE_C_SEVERE": "C (1 CPU, 1 GB)"}
ENGINE_COLOR = {"mongodb": "#2E7D32", "postgresql": "#1565C0"}
PROFILE_STYLE = {"PROFILE_A_BASELINE": ("-", "o"), "PROFILE_B_MEDIUM": ("--", "s"), "PROFILE_C_SEVERE": (":", "^")}
KEYS = ["engine", "profile", "query_id", "concurrency"]


def leer_perfiles():
    perfiles = {}
    for f in glob.glob(os.path.join(ROOT, "profiles", "*.env")):
        d = dict(l.strip().split("=", 1) for l in open(f) if "=" in l and not l.startswith("#"))
        mem = d["MEM_LIMIT"].lower()
        gb = float(mem.rstrip("m")) / 1024 if mem.endswith("m") else float(mem.rstrip("g"))
        perfiles[d["PROFILE_ID"]] = {"cpus": float(d["CPUS"]), "mem_gb": gb}
    return perfiles


def cv(x):
    x = pd.to_numeric(x, errors="coerce").dropna()
    return float(x.std(ddof=1) / x.mean()) if len(x) > 1 and x.mean() else np.nan


def consolidar(df):
    num = ["throughput_qps", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms", "cpu_throttled_seconds", "max_rss_mb"]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["disk_spill"] = df["disk_spill"].astype(str).str.lower().eq("true")
    g = df.groupby(KEYS)
    t = g[num].median().add_suffix("_mediana")
    t["repeticiones"] = g.size()
    t["runs_con_spill"] = g["disk_spill"].sum()
    t["estados"] = g["status"].agg(lambda s: ",".join(f"{k}:{v}" for k, v in s.value_counts().items()))
    t["cv_qps"] = g["throughput_qps"].agg(cv)
    t["cv_p99"] = g["latency_p99_ms"].agg(cv)
    t["estable"] = ~((t["cv_qps"] > UMBRAL_CV) | (t["cv_p99"] > UMBRAL_CV))
    return t.reset_index()


def leer_logs(logs_dir):
    filas = []
    for f in glob.glob(os.path.join(logs_dir, "*.json")):
        try:
            d = json.load(open(f))
            r = d["fila_csv"]
        except Exception:
            continue
        cpu = d.get("cpu_usage_s", {})
        filas.append({**{k: r[k] for k in KEYS}, "run_number": r["run_number"],
                      "cpu_s": cpu.get("prometheus_s") if cpu.get("prometheus_s") is not None else cpu.get("cgroup_cpu_stat_s"),
                      "consultas": d.get("consultas_completadas"),
                      "rss_serie": d.get("rss_serie_bytes") or []})
    return pd.DataFrame(filas)


def huella_m3(tabla, logs):
    h = tabla[KEYS + ["max_rss_mb_mediana", "throughput_qps_mediana"]].copy()
    # Memoria por 1 000 documentos: pico de RSS repartido entre los 500 000 documentos del dataset
    h["rss_mb_por_1000_docs"] = h["max_rss_mb_mediana"] / (DOCS_POR_CONSULTA / 1000)
    h["cpu_ms_por_1000_docs"] = np.nan
    if len(logs) and logs["cpu_s"].notna().any():
        l = logs.dropna(subset=["cpu_s"]).copy()
        l = l[l["consultas"] > 0]
        # CPU consumida en la ventana / (consultas completadas x documentos por consulta / 1000)
        l["cpu_ms_1000"] = l["cpu_s"] * 1000 / (l["consultas"] * DOCS_POR_CONSULTA / 1000)
        m = l.groupby(KEYS)["cpu_ms_1000"].median().reset_index()
        h = h.drop(columns="cpu_ms_por_1000_docs").merge(
            m.rename(columns={"cpu_ms_1000": "cpu_ms_por_1000_docs"}), on=KEYS, how="left")
    return h


def costo_nube(tabla, perfiles):
    c = tabla[KEYS + ["throughput_qps_mediana"]].copy()
    c["cpus"] = c["profile"].map(lambda p: perfiles.get(p, {}).get("cpus"))
    c["mem_gb"] = c["profile"].map(lambda p: perfiles.get(p, {}).get("mem_gb"))
    c["usd_por_hora"] = c["cpus"] * PRECIO_VCPU_HORA + c["mem_gb"] * PRECIO_GB_HORA
    qph = c["throughput_qps_mediana"] * 3600
    c["usd_por_millon_consultas"] = np.where(qph > 0, c["usd_por_hora"] / qph * 1e6, np.nan)
    return c


def revisar_termico(df, monitor_csv):
    if not monitor_csv or not os.path.exists(monitor_csv):
        return None
    m = pd.read_csv(monitor_csv)
    for c in ["pct_rendimiento", "temp_c"]:
        m[c] = pd.to_numeric(m[c], errors="coerce")
    ref = m["pct_rendimiento"].median()
    filas = []
    for _, r in df.iterrows():
        t0 = int(r["timestamp_epoch"])
        w = m[(m["epoch"] >= t0) & (m["epoch"] <= t0 + 300)]
        if w.empty:
            continue
        perf, temp = w["pct_rendimiento"].mean(), w["temp_c"].max()
        sospechosa = (perf < 0.85 * ref) or (pd.notna(temp) and temp >= 90)
        filas.append({**{k: r[k] for k in KEYS}, "run_number": r["run_number"],
                      "pct_rendimiento_prom": round(perf, 1), "temp_max_c": temp, "sospechosa": sospechosa})
    return pd.DataFrame(filas)


# ------------------------------------------------------------------ graficas
def leyenda_comun(fig, perfiles_presentes):
    from matplotlib.lines import Line2D
    h = [Line2D([], [], color=c, lw=2, label=e) for e, c in ENGINE_COLOR.items()]
    h += [Line2D([], [], color="gray", ls=PROFILE_STYLE[p][0], marker=PROFILE_STYLE[p][1], label=PROFILE_LABEL[p])
          for p in PROFILE_ORDER if p in perfiles_presentes]
    fig.legend(handles=h, loc="lower center", ncol=len(h), frameon=False, fontsize=9)


def grafica_por_query(tabla, col, ylabel, titulo, archivo, log=False):
    qs = sorted(tabla["query_id"].unique())
    fig, axes = plt.subplots(1, len(qs), figsize=(5 * len(qs), 4.2), sharey=True, squeeze=False)
    for ax, q in zip(axes[0], qs):
        for (e, p), s in tabla[tabla["query_id"] == q].groupby(["engine", "profile"]):
            s = s.sort_values("concurrency")
            ls, mk = PROFILE_STYLE.get(p, ("-", "o"))
            ax.plot(s["concurrency"], s[col], ls=ls, marker=mk, color=ENGINE_COLOR.get(e, "k"))
        ax.set_title(q)
        ax.set_xlabel("Clientes concurrentes")
        ax.set_xticks(sorted(tabla["concurrency"].unique()))
        if log:
            ax.set_yscale("log")
        ax.grid(alpha=0.3)
    axes[0][0].set_ylabel(ylabel)
    fig.suptitle(titulo)
    leyenda_comun(fig, tabla["profile"].unique())
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(archivo, dpi=150)
    plt.close(fig)


def grafica_throttling(tabla, archivo):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for (e, p), s in tabla.groupby(["engine", "profile"]):
        ax.scatter(s["cpu_throttled_seconds_mediana"], s["throughput_qps_mediana"],
                   color=ENGINE_COLOR.get(e, "k"), marker=PROFILE_STYLE.get(p, ("-", "o"))[1], s=45, alpha=0.85)
    ax.set_xlabel("Tiempo de throttling CFS en la ventana (s)")
    ax.set_ylabel("Throughput (consultas/s)")
    ax.set_title("Throttling contra throughput (mediana de 3 repeticiones)")
    ax.grid(alpha=0.3)
    leyenda_comun(fig, tabla["profile"].unique())
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(archivo, dpi=150)
    plt.close(fig)


def grafica_curva_rss(logs, archivo, perfiles):
    if logs.empty or not logs["rss_serie"].map(len).any():
        return False
    l = logs[logs["rss_serie"].map(len) > 0]
    # Curva representativa: la concurrencia mas alta medida, repeticion 1, cada consulta en su panel
    cmax = l["concurrency"].max()
    l = l[(l["concurrency"] == cmax) & (l["run_number"] == l["run_number"].min())]
    qs = sorted(l["query_id"].unique())
    fig, axes = plt.subplots(1, len(qs), figsize=(5 * len(qs), 4.2), sharey=True, squeeze=False)
    for ax, q in zip(axes[0], qs):
        for _, r in l[l["query_id"] == q].iterrows():
            t, v = zip(*r["rss_serie"])
            ls, _ = PROFILE_STYLE.get(r["profile"], ("-", "o"))
            ax.plot(t, np.array(v) / 1048576, ls=ls, color=ENGINE_COLOR.get(r["engine"], "k"))
        for p, info in perfiles.items():
            if p in l["profile"].values:
                ax.axhline(info["mem_gb"] * 1024, color="red", lw=0.8, ls=PROFILE_STYLE[p][0], alpha=0.5)
        ax.set_title(f"{q}, {cmax} clientes")
        ax.set_xlabel("Segundos de medicion")
        ax.grid(alpha=0.3)
    axes[0][0].set_ylabel("RSS (MB); lineas rojas = limite del perfil")
    fig.suptitle("Curva de memoria RSS durante la medicion")
    leyenda_comun(fig, l["profile"].unique())
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(archivo, dpi=150)
    plt.close(fig)
    return True


# ------------------------------------------------------------------ resumen
def resumen_md(df, tabla, huella, costo, termico, curva_ok):
    L = ["# Resumen automatico de resultados", "",
         f"Filas en el CSV: {len(df)}. Celdas: {len(tabla)}. "
         f"Repeticiones por celda: {tabla['repeticiones'].min()} a {tabla['repeticiones'].max()}.", ""]

    falt = tabla[tabla["repeticiones"] < 3]
    if len(falt):
        L += ["## Celdas con menos de 3 repeticiones", ""]
        L += [f"- {r.engine} / {r.profile} / {r.query_id} / {r.concurrency} clientes: {r.repeticiones}" for r in falt.itertuples()]
        L.append("")

    L += ["## Estabilidad entre repeticiones", "",
          f"Se considera inestable una celda cuyo throughput o P99 varia mas de {UMBRAL_CV:.0%} entre sus 3 repeticiones "
          "(coeficiente de variacion = desviacion estandar / media). En esas celdas conviene repetir la medicion "
          "o explicar la causa en el reporte.", ""]
    inest = tabla[~tabla["estable"]]
    if len(inest):
        L += [f"- {r.engine} / {r.profile} / {r.query_id} / {r.concurrency} clientes: "
              f"CV qps {r.cv_qps:.0%}, CV P99 {r.cv_p99:.0%}" for r in inest.itertuples()]
    else:
        L.append("Todas las celdas son estables.")
    L.append("")

    raro = tabla[tabla["estados"].str.contains("spill|oom|error")]
    L += ["## Spill, OOM y errores", ""]
    L += [f"- {r.engine} / {r.profile} / {r.query_id} / {r.concurrency} clientes: {r.estados}" for r in raro.itertuples()] \
        or ["Ninguna celda reporto spill, OOM ni errores."]
    L.append("")

    L += ["## M3: huella por cada 1 000 documentos (perfil y concurrencia 1)", ""]
    h1 = huella[huella["concurrency"] == huella["concurrency"].min()]
    for r in h1.itertuples():
        cpu = f"{r.cpu_ms_por_1000_docs:.2f} ms de CPU" if pd.notna(r.cpu_ms_por_1000_docs) else "CPU sin dato (faltan logs)"
        L.append(f"- {r.engine} / {r.profile} / {r.query_id}: {cpu}, {r.rss_mb_por_1000_docs:.3f} MB de RSS")
    L.append("")

    L += ["## Costo estimado en la nube (AWS Fargate, us-east-1)", "",
          f"Precio usado: USD {PRECIO_VCPU_HORA} por vCPU-hora y USD {PRECIO_GB_HORA} por GB-hora. "
          "Costo por millon de consultas = costo por hora / consultas por hora x 1 000 000.", ""]
    best = costo.dropna(subset=["usd_por_millon_consultas"]).sort_values("usd_por_millon_consultas")
    for (e, q), s in best.groupby(["engine", "query_id"]):
        r = s.iloc[0]
        L.append(f"- {e} {q}: lo mas barato fue {r.profile} con {r.concurrency} clientes, "
                 f"USD {r.usd_por_millon_consultas:,.2f} por millon de consultas")
    L.append("")

    if termico is not None and len(termico):
        sos = termico[termico["sospechosa"]]
        L += ["## Revision termica del host", "",
              f"Corridas revisadas: {len(termico)}. Con rendimiento del CPU bajo (menos del 85 % de lo normal) "
              f"o temperatura de 90 C o mas: {len(sos)}.", ""]
        L += [f"- {r.engine} / {r.profile} / {r.query_id} / {r.concurrency} clientes / run {r.run_number}: "
              f"rendimiento {r.pct_rendimiento_prom} %, temp max {r.temp_max_c}" for r in sos.itertuples()]
        L.append("")

    L += ["## Graficas generadas", "", "- p99_vs_concurrencia.png", "- throttling_vs_qps.png", "- rss_vs_concurrencia.png"]
    if curva_ok:
        L.append("- curva_rss_tiempo.png")
    return "\n".join(L) + "\n"


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--csv", default=os.path.join(ROOT, "results", "mediciones.csv"))
    a.add_argument("--logs", default=os.path.join(ROOT, "logs"))
    a.add_argument("--monitor", default=os.path.join(ROOT, "extras", "monitor_cpu.csv"))
    a.add_argument("--salida", default=os.path.join(ROOT, "extras", "salida"))
    args = a.parse_args()
    os.makedirs(args.salida, exist_ok=True)
    out = lambda n: os.path.join(args.salida, n)

    df = pd.read_csv(args.csv)
    perfiles = leer_perfiles()
    tabla = consolidar(df.copy())
    logs = leer_logs(args.logs)
    huella = huella_m3(tabla, logs)
    costo = costo_nube(tabla, perfiles)
    termico = revisar_termico(df, args.monitor)

    tabla.round(4).to_csv(out("tabla_consolidada.csv"), index=False)
    huella.round(4).to_csv(out("huella_m3.csv"), index=False)
    costo.round(4).to_csv(out("costo_nube.csv"), index=False)
    if termico is not None:
        termico.to_csv(out("revision_termica.csv"), index=False)

    grafica_por_query(tabla, "latency_p99_ms_mediana", "Latencia P99 (ms, escala log)",
                      "P99 contra concurrencia (mediana de 3 repeticiones)", out("p99_vs_concurrencia.png"), log=True)
    grafica_throttling(tabla, out("throttling_vs_qps.png"))
    grafica_por_query(tabla, "max_rss_mb_mediana", "RSS maximo (MB)",
                      "Memoria RSS maxima contra concurrencia", out("rss_vs_concurrencia.png"))
    curva_ok = grafica_curva_rss(logs, out("curva_rss_tiempo.png"), perfiles)

    with open(out("resumen.md"), "w", encoding="utf-8") as f:
        f.write(resumen_md(df, tabla, huella, costo, termico, curva_ok))
    print(f"Listo. Archivos en {args.salida}")


if __name__ == "__main__":
    main()
