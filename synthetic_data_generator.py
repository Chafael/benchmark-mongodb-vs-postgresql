#!/usr/bin/env python3
"""
Generador del dataset sintetico (playbook, seccion 4) adaptado a EnlaceSeguro, y carga a ambos motores.

Caso de uso: coleccion `analisis` de EnlaceSeguro (patron P3, "Registrar resultado completo de analisis").
Cada documento es el resultado de revisar un enlace sospechoso. Ver ADAPTACION.md.

  python synthetic_data_generator.py generate            -> data/analisis.jsonl (500 000 documentos)
  python synthetic_data_generator.py load --engine mongodb
  python synthetic_data_generator.py load --engine postgresql

Datos 100 % sinteticos: los dominios usan los TLD reservados .test y .example (RFC 2606/6761),
asi ningun documento apunta a un sitio real. Semilla fija: el archivo sale identico en cualquier equipo,
y el MISMO archivo se carga en los dos motores (baseline comparable).
"""
import argparse
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

SEED = 42
N_RECORDS = 500_000
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ROOT, "data", "analisis.jsonl")
DB_NAME = "enlaceseguro"
COLLECTION = "analisis"
N_USUARIOS = 20_000

F_INICIO = datetime(2025, 1, 1, tzinfo=timezone.utc)
F_FIN = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)

# Fuentes de reputacion de la propuesta. Las tres primeras se consultan casi siempre;
# RDAP/WHOIS es una senal condicionada. Promedio: 3 fuentes por analisis.
FUENTES = [("VirusTotal", 0.85), ("Google Safe Browsing", 0.85), ("URLhaus", 0.80), ("RDAP", 0.50)]
LATENCIA_BASE = {"VirusTotal": 900, "Google Safe Browsing": 180, "URLhaus": 350, "RDAP": 600}
PALABRAS = ["banco", "seguro", "promo", "premio", "verifica", "cuenta", "paquete", "envio", "factura",
            "soporte", "login", "regalo", "pago", "netflix-clon", "bono", "sat-aviso", "tienda", "cupon"]
TLDS = [".test", ".example"]
SENALES = ["formulario_credenciales", "descarga_bloqueada", "dominio_reciente", "script_ofuscado",
           "redireccion_externa", "certificado_invalido", "suplantacion_marca", "ventana_emergente"]
RAZONES = {"peligroso": ["Detectado como malicioso por fuentes de reputacion", "Pide credenciales en un dominio no oficial"],
           "sospechoso": ["Dominio registrado hace pocos dias", "Redirige varias veces antes del destino",
                          "Contiene codigo ofuscado"],
           "sin_amenazas_detectadas": ["Ninguna fuente reporto amenazas"]}


def oid_hex(rng):
    return f"{rng.getrandbits(96):024x}"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def url_falsa(rng):
    dominio = "-".join(rng.sample(PALABRAS, rng.randint(1, 3))) + rng.choice(TLDS)
    ruta = "/".join(rng.sample(PALABRAS, rng.randint(0, 2)))
    return f"{rng.choice(['https', 'https', 'http'])}://{dominio}/{ruta}"


def make_analisis(rng, usuarios):
    fecha = F_INICIO + timedelta(seconds=rng.randrange(int((F_FIN - F_INICIO).total_seconds())))
    url = url_falsa(rng)

    redirecciones = []
    actual = url
    for _ in range(rng.choices([0, 1, 2, 3], weights=[45, 30, 17, 8])[0]):
        actual = url_falsa(rng)
        redirecciones.append({"url": actual, "codigoHttp": rng.choice([301, 302, 302, 307])})

    senales = rng.sample(SENALES, rng.choices([0, 1, 2, 3], weights=[40, 30, 20, 10])[0])

    # Respuesta por fuente (3 niveles: documento -> fuentes[] -> respuesta -> detecciones)
    malicioso = rng.random() < 0.18
    fuentes = []
    for nombre, prob in FUENTES:
        if rng.random() > prob:
            continue                                   # sin credenciales o sin cuota: no se consulto
        consultado = fecha + timedelta(milliseconds=rng.randint(50, 4000))
        latencia = int(rng.lognormvariate(0, 0.6) * LATENCIA_BASE[nombre])
        if rng.random() < 0.07:                        # fallo del proveedor (timeout o error)
            fuentes.append({"nombre": nombre, "estado": "error", "latenciaMs": max(latencia, 5000),
                            "consultadoEn": {"$date": iso(consultado)}, "respuesta": {"detecciones": 0, "categoria": "no_disponible"}})
            continue
        det = (rng.randint(1, 30) if nombre == "VirusTotal" else 1) if (malicioso and rng.random() < 0.8) else 0
        fuentes.append({"nombre": nombre, "estado": "ok", "latenciaMs": latencia,
                        "consultadoEn": {"$date": iso(consultado)},
                        "respuesta": {"detecciones": det, "categoria": "malicioso" if det else "limpio"}})

    detecciones = sum(f["respuesta"]["detecciones"] for f in fuentes)
    if detecciones:
        categoria = "peligroso"
    elif len(senales) >= 2 or "formulario_credenciales" in senales:
        categoria = "sospechoso"
    else:
        categoria = "sin_amenazas_detectadas"
    hubo_fallo = any(f["estado"] == "error" for f in fuentes) or not fuentes
    oid = oid_hex(rng)

    return {
        "_id": {"$oid": oid},
        "usuarioId": {"$oid": rng.choice(usuarios)},
        "urlInicial": url,
        "destinoFinal": actual,
        "fecha": {"$date": iso(fecha)},
        # Un fallo de proveedor deja el resultado como parcial (requisito de la propuesta)
        "estado": "parcial" if hubo_fallo else "completo",
        "duracionMs": int(rng.lognormvariate(9.0, 0.45)),   # tiempo total del analisis en el sandbox
        "veredicto": {"categoria": categoria, "razones": rng.sample(RAZONES[categoria], 1)},
        "redirecciones": redirecciones,
        "senales": senales,
        "captura": {"uri": f"capturas/{oid}.png", "ancho": 1280, "alto": 720},
        "fuentes": fuentes,
    }


def generate(n, path):
    """Escribe Extended JSON v2 ($oid, $date)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rng = random.Random(SEED)
    usuarios = [oid_hex(rng) for _ in range(N_USUARIOS)]
    t0 = time.time()
    # newline="\n": en Windows evita \r\n y el archivo es identico en cualquier sistema (mismo md5)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for i in range(n):
            f.write(json.dumps(make_analisis(rng, usuarios), separators=(",", ":")) + "\n")
            if (i + 1) % 100_000 == 0:
                print(f"  {i + 1:,} documentos ({time.time() - t0:.0f} s)")
    print(f"Listo: {n:,} documentos en {path} ({os.path.getsize(path) / 1e6:.0f} MB)")


def read_batches(path, size):
    batch = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            batch.append(line)
            if len(batch) == size:
                yield batch
                batch = []
    if batch:
        yield batch


def a_json_plano(v):
    """Extended JSON -> JSON plano para JSONB: ObjectId como texto hex, fechas como texto ISO-8601."""
    if isinstance(v, dict):
        if set(v) == {"$oid"}:
            return v["$oid"]
        if set(v) == {"$date"}:
            return v["$date"]
        return {k: a_json_plano(x) for k, x in v.items()}
    if isinstance(v, list):
        return [a_json_plano(x) for x in v]
    return v


def esquema_propuesto():
    """$jsonSchema propuesto para analisis (el repositorio aun no define esquema fisico; ver ADAPTACION.md)."""
    oid, dt, st, it = {"bsonType": "objectId"}, {"bsonType": "date"}, {"bsonType": "string"}, {"bsonType": "int"}
    return {"$jsonSchema": {
        "bsonType": "object",
        "required": ["usuarioId", "urlInicial", "fecha", "estado", "veredicto", "fuentes"],
        "properties": {
            "_id": oid, "usuarioId": oid, "urlInicial": st, "destinoFinal": st, "fecha": dt,
            "estado": {"enum": ["completo", "parcial"]},
            "duracionMs": {"bsonType": "int", "minimum": 0},
            "veredicto": {"bsonType": "object", "required": ["categoria"], "properties": {
                "categoria": {"enum": ["peligroso", "sospechoso", "sin_amenazas_detectadas"]},
                "razones": {"bsonType": "array", "items": st}}},
            "redirecciones": {"bsonType": "array", "items": {"bsonType": "object", "properties": {
                "url": st, "codigoHttp": it}}},
            "senales": {"bsonType": "array", "items": st},
            "captura": {"bsonType": "object", "properties": {"uri": st, "ancho": it, "alto": it}},
            "fuentes": {"bsonType": "array", "items": {"bsonType": "object",
                "required": ["nombre", "estado"], "properties": {
                    "nombre": st, "estado": {"enum": ["ok", "error"]}, "latenciaMs": it, "consultadoEn": dt,
                    "respuesta": {"bsonType": "object", "properties": {"detecciones": it, "categoria": st}}}}},
        }}}


def load_mongodb(path, uri):
    from bson import json_util
    from pymongo import MongoClient, ASCENDING
    db = MongoClient(uri)[DB_NAME]
    db.drop_collection(COLLECTION)
    db.create_collection(COLLECTION, validator=esquema_propuesto())
    coll = db[COLLECTION]
    for batch in read_batches(path, 5000):
        coll.insert_many([json_util.loads(l) for l in batch], ordered=False)
    # Indices (playbook seccion 2, adaptados): simple en la marca de tiempo (fecha)
    # y simple en usuarioId, que es el que pide el historial personal (P4)
    coll.create_index([("fecha", ASCENDING)])
    coll.create_index([("usuarioId", ASCENDING)])
    print(f"MongoDB: {coll.count_documents({}):,} documentos en {DB_NAME}.{COLLECTION}, "
          f"indices: {list(coll.index_information())}")


def load_postgresql(path, dsn):
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {COLLECTION}")
        # Tabla del playbook: id UUID PRIMARY KEY, data JSONB (el _id de Mongo queda dentro de data)
        conn.execute(f"CREATE TABLE {COLLECTION} (id UUID PRIMARY KEY, data JSONB NOT NULL)")
        with conn.cursor() as cur:
            with cur.copy(f"COPY {COLLECTION} (id, data) FROM STDIN") as copy:
                for batch in read_batches(path, 5000):
                    for line in batch:
                        doc = a_json_plano(json.loads(line))
                        copy.write_row((uuid.uuid5(uuid.NAMESPACE_OID, doc["_id"]),
                                        json.dumps(doc, separators=(",", ":"))))
        conn.execute(f"CREATE INDEX analisis_fecha_idx ON {COLLECTION} ((data->>'fecha'))")
        conn.execute(f"CREATE INDEX analisis_usuario_idx ON {COLLECTION} ((data->>'usuarioId'))")
        conn.execute(f"ANALYZE {COLLECTION}")
        n = conn.execute(f"SELECT count(*) FROM {COLLECTION}").fetchone()[0]
        print(f"PostgreSQL: {n:,} filas en {COLLECTION}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("-n", type=int, default=N_RECORDS)
    g.add_argument("--out", default=DATA_FILE)
    l = sub.add_parser("load")
    l.add_argument("--engine", choices=["mongodb", "postgresql"], required=True)
    l.add_argument("--file", default=DATA_FILE)
    l.add_argument("--mongo-uri", default=os.getenv("MONGO_URI", "mongodb://127.0.0.1:27018"))
    l.add_argument("--pg-dsn", default=os.getenv("PG_DSN", "postgresql://bench:bench@127.0.0.1:5433/bench"))
    a = p.parse_args()

    if a.cmd == "generate":
        generate(a.n, a.out)
    elif a.engine == "mongodb":
        load_mongodb(a.file, a.mongo_uri)
    else:
        load_postgresql(a.file, a.pg_dsn)


if __name__ == "__main__":
    sys.exit(main())
