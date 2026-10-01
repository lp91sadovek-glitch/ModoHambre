import json
import os
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "orders.db"

# Donde vive la web publica y la API (Render). La PC del local tambien corre este
# mismo archivo, pero es la que avisa que sigue encendida.
URL_HOST = "https://modohambre.onrender.com"

# Render pone RENDER=true en el entorno. Ahi no hay nada que sincronizar, porque
# el archivo del contenedor es temporal y no sirve como respaldo.
EN_RENDER = os.environ.get("RENDER", "").lower() == "true"

# Cada cuanto la PC del local le avisa al host que esta abierta.
INTERVALO_LATIDO = 5

# Si el local dejo de avisar durante 5 minutos se lo considera cerrado y el host
# deja de aceptar pedidos. El margen es amplio a proposito: el local tiene que
# cortar la pagina con tiempo antes de que el servicio termine.
SEGUNDOS_PARA_CERRADO = 300

app = Flask(__name__, static_folder=".", static_url_path="")

# El panel de pedidos corre en la PC del local y consulta esta API, que esta
# en otro dominio. Sin esto el navegador bloquea la respuesta.
CORS(app, resources={r"/api/.*": {"origins": "*"}})


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS platos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            precio INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            items TEXT NOT NULL,
            total INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS local (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            ultimo_latido REAL
        )
        """
    )
    conn.commit()

    cols = [row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()]
    if "estado" not in cols:
        conn.execute(
            "ALTER TABLE orders ADD COLUMN estado TEXT NOT NULL DEFAULT 'nuevo'"
        )
        conn.commit()

    if "envio" not in cols:
        conn.execute(
            "ALTER TABLE orders ADD COLUMN envio TEXT NOT NULL DEFAULT 'local'"
        )
        conn.execute(
            "ALTER TABLE orders ADD COLUMN cliente TEXT NOT NULL DEFAULT '{}'"
        )
        conn.commit()

    existing = conn.execute("SELECT COUNT(*) AS count FROM platos").fetchone()["count"]
    if existing == 0:
        platos_seed = [
            ("Pollo al espiedo", 850),
            ("Pollo con arroz", 780),
            ("Pollo con mostaza", 820),
            ("Chorizo con papas", 760),
            ("Hamburguesa de pollo", 890),
            ("Chorizo al espiedo", 700),
            ("Hamburguesa con lechuga", 880),
            ("Azado Argento", 950),
        ]
        conn.executemany(
            "INSERT INTO platos (nombre, precio) VALUES (?, ?)",
            platos_seed,
        )
        conn.commit()

    conn.close()


init_db()


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/platos")
def get_platos():
    conn = get_db_connection()
    platos = conn.execute("SELECT nombre, precio FROM platos ORDER BY id").fetchall()
    conn.close()
    return jsonify([{"nombre": p["nombre"], "precio": p["precio"]} for p in platos])


# ---------------------------------------------------------------------------
# ESTADO DEL LOCAL
#
# La PC del local no esta siempre prendida: cuando cierra, la web sigue
# funcionando y los clientes podrian hacer pedidos que nadie va a preparar. Para
# evitarlo, la PC del local le avisa al host cada 5 segundos que sigue abierta
# (un "latido") y el host deja de aceptar pedidos si pasan 5 minutos sin aviso.
# ---------------------------------------------------------------------------


def estado_del_local():
    """Devuelve (local_abierto, segundos_desde_el_ultimo_latido)."""
    if not EN_RENDER:
        # esta soy la PC del local: si estas viendo la respuesta, el local
        # esta abierto, no hace falta mirar la tabla
        return True, None

    conn = get_db_connection()
    fila = conn.execute("SELECT ultimo_latido FROM local WHERE id = 1").fetchone()
    conn.close()

    if fila is None or fila["ultimo_latido"] is None:
        return False, None

    hace = time.time() - fila["ultimo_latido"]
    return hace <= SEGUNDOS_PARA_CERRADO, hace


@app.route("/api/local/latido", methods=["POST"])
def latido_del_local():
    """La PC del local avisa que sigue encendida."""
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO local (id, ultimo_latido) VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET ultimo_latido = excluded.ultimo_latido
        """,
        (time.time(),),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/local/estado")
def estado_local():
    """Si el local esta abierto ahora mismo."""
    abierto, hace = estado_del_local()
    return jsonify(
        {
            "abierto": abierto,
            "hace_segundos": None if hace is None else int(hace),
            "margen_segundos": SEGUNDOS_PARA_CERRADO,
        }
    )


@app.route("/api/orders", methods=["GET", "POST", "DELETE"])
def orders():
    if request.method == "DELETE":
        conn = get_db_connection()
        cur = conn.execute("DELETE FROM orders")
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "eliminados": cur.rowcount})

    if request.method == "GET":
        conn = get_db_connection()
        rows = conn.execute("SELECT id, items, total, created_at, estado, envio, cliente FROM orders ORDER BY id DESC").fetchall()
        conn.close()
        return jsonify(
            [
                {
                    "id": row["id"],
                    "items": json.loads(row["items"]),
                    "total": row["total"],
                    "estado": row["estado"],
                    "envio": row["envio"],
                    "cliente": json.loads(row["cliente"] or "{}"),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        )

    data = request.get_json(silent=True) or {}

    # Si el local esta cerrado el pedido no se guarda: no hay nadie en el local
    # para prepararlo, asi que es mejor avisarle al cliente antes de que pague.
    abierto, hace = estado_del_local()
    if not abierto:
        return (
            jsonify(
                {
                    "error": "El local esta cerrado ahora mismo. No se pudo enviar el pedido.",
                    "codigo": "local_cerrado",
                }
            ),
            503,
        )

    items = data.get("items", [])
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Se requiere al menos un plato"}), 400

    envio = data.get("envio", "local")
    if envio not in ("domicilio", "local"):
        return jsonify({"error": "Tipo de envío inválido"}), 400

    cliente = data.get("cliente", {})
    if not isinstance(cliente, dict):
        return jsonify({"error": "Datos del cliente inválidos"}), 400

    total = sum(
        int(item.get("price", 0)) * int(item.get("quantity", 1) or 1)
        for item in items
        if isinstance(item, dict)
    )
    payload = json.dumps(items)
    cliente_payload = json.dumps(cliente, ensure_ascii=False)

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO orders (items, total, envio, cliente) VALUES (?, ?, ?, ?)",
        (payload, total, envio, cliente_payload),
    )
    conn.commit()
    order_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()

    return jsonify({"ok": True, "order_id": order_id, "total": total})


@app.route("/api/orders/<int:order_id>/estado", methods=["POST"])
def update_estado(order_id):
    data = request.get_json(silent=True) or {}
    estado = data.get("estado")
    if estado not in ("nuevo", "recibido", "listo"):
        return jsonify({"error": "Estado inválido"}), 400

    conn = get_db_connection()
    cur = conn.execute(
        "UPDATE orders SET estado = ? WHERE id = ?",
        (estado, order_id),
    )
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return jsonify({"error": "Pedido no encontrado"}), 404

    return jsonify({"ok": True, "order_id": order_id, "estado": estado})


@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    conn = get_db_connection()
    cur = conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return jsonify({"error": "Pedido no encontrado"}), 404

    return jsonify({"ok": True, "order_id": order_id})


# ---------------------------------------------------------------------------
# ARCHIVO LOCAL DE PEDIDOS
#
# El host guarda los pedidos de forma temporal: cuando Render se duerme o se
# redespliega, esa base se borra. Por eso esta PC baja los pedidos del host cada
# 5 segundos y los copia a pedidos.jsonl, un archivo de texto que vive en el
# disco y no se pierde nunca (se puede abrir con el Bloc de notas).
# ---------------------------------------------------------------------------

ARCHIVO_PEDIDOS = BASE_DIR / "pedidos.jsonl"
INTERVALO_SINCRONIZACION = INTERVALO_LATIDO


def clave_pedido(pedido):
    return "{}|{}".format(pedido.get("id"), pedido.get("created_at"))


def leer_archivo():
    """Devuelve los pedidos guardados en el archivo local."""
    if not ARCHIVO_PEDIDOS.exists():
        return []

    pedidos = []
    for linea in ARCHIVO_PEDIDOS.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            pedidos.append(json.loads(linea))
        except ValueError:
            # una linea rota no debe voltear el archivo entero
            continue
    return pedidos


def guardar_en_archivo(pedidos_nuevos):
    """Agrega pedidos al archivo. Si ya estaban, actualiza su estado."""
    if not pedidos_nuevos:
        return 0

    por_clave = {clave_pedido(p): p for p in leer_archivo()}
    agregados = 0

    for pedido in pedidos_nuevos:
        if not isinstance(pedido, dict) or pedido.get("id") is None:
            continue
        clave = clave_pedido(pedido)
        if clave not in por_clave:
            agregados += 1
        por_clave[clave] = pedido

    ordenados = sorted(
        por_clave.values(),
        key=lambda p: (p.get("created_at") or "", p.get("id") or 0),
        reverse=True,
    )

    with ARCHIVO_PEDIDOS.open("w", encoding="utf-8") as archivo:
        for pedido in ordenados:
            archivo.write(json.dumps(pedido, ensure_ascii=False) + "\n")

    return agregados


def sincronizar_una_vez():
    """Descarga los pedidos del host y los deja en el archivo local."""
    try:
        with urllib.request.urlopen(URL_HOST + "/api/orders", timeout=15) as respuesta:
            pedidos = json.loads(respuesta.read().decode("utf-8"))
    except Exception:
        # si el host no responde no pasa nada, se reintenta en el proximo ciclo
        return 0

    return guardar_en_archivo(pedidos)


def avisar_que_el_local_esta_abierto():
    """Le dice al host que esta PC sigue encendida."""
    peticion = urllib.request.Request(
        URL_HOST + "/api/local/latido",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=15) as respuesta:
        respuesta.read()


def sincronizar_en_segundo_plano():
    while True:
        try:
            sincronizar_una_vez()
        except Exception as error:
            print("No se pudo sincronizar con el host:", error)
        try:
            # el latido va aparte de la descarga: asi el host se entera igual
            # de que el local esta abierto aunque falle bajar los pedidos
            avisar_que_el_local_esta_abierto()
        except Exception as error:
            print("No se pudo avisar al host que el local esta abierto:", error)
        time.sleep(INTERVALO_SINCRONIZACION)


@app.route("/api/archivo", methods=["GET", "POST"])
def archivo_pedidos():
    """El archivo local: GET lo lee, POST agrega un pedido."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        pedido = data.get("pedido", data)
        if not isinstance(pedido, dict) or pedido.get("id") is None:
            return jsonify({"error": "Pedido inválido"}), 400
        return jsonify({"ok": True, "nuevos": guardar_en_archivo([pedido])})

    return jsonify(leer_archivo())


def puerto_ocupado(puerto):
    """waitress no avisa si el puerto ya esta en uso, asi que lo comprobamos."""
    conexion = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        conexion.bind(("0.0.0.0", puerto))
    except OSError:
        return True
    finally:
        conexion.close()
    return False


def run_http_server():
    from waitress import serve

    serve(app, host="0.0.0.0", port=5000, threads=8)


# En la PC del local el archivo se mantiene solo: no hace falta que el panel este
# abierto para que los pedidos queden guardados en el disco.
if not EN_RENDER:
    threading.Thread(target=sincronizar_en_segundo_plano, daemon=True).start()


if __name__ == "__main__":
    if puerto_ocupado(5000):
        print("")
        print("El puerto 5000 ya esta en uso.")
        print("")
        print("Casi seguro ya hay otra ventana de Modo Hambre abierta.")
        print("Cerrala con Ctrl+C o cerrando la ventana, y volve a abrir el programa.")
        sys.exit(1)

    try:
        print("Servidor iniciado en http://localhost:5000")
        run_http_server()
    except ImportError:
        print("")
        print("Falta la dependencia 'waitress'.")
        print("Ejecutá: pip install -r requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        print("")
        print("Servidor detenido")
