import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
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

# El puerto del host local (la PC del local).
PUERTO = 5000
URL_LOCAL = f"http://localhost:{PUERTO}"

# ---------------------------------------------------------------------------
# CLAVE DEL PANEL
#
# El panel muestra los pedidos con nombre, telefono y direccion del cliente, asi
# que no puede quedar abierto en internet. El dueno escribe la clave y recien ahi
# puede verlos.
#
# La clave se busca en dos lugares, en este orden:
#   1. La variable de entorno CLAVE_PANEL de Render (la del host).
#   2. La linea "CLAVE_PANEL:" del archivo de texto de la PC del local, que ese
#      archivo no se sube al repositorio justamente para que la clave no quede
#      a la vista de cualquiera.
# ---------------------------------------------------------------------------

CABECERA_CLAVE = "X-Clave-Panel"
ARCHIVO_CLAVE = "para abrir el hostlocal.txt"


def leer_clave_del_archivo():
    """Busca la linea 'CLAVE_PANEL:' en el archivo de texto de la PC del local."""
    for carpeta in (BASE_DIR, BASE_DIR.parent):
        ruta = carpeta / ARCHIVO_CLAVE
        if not ruta.exists():
            continue
        try:
            lineas = ruta.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for linea in lineas:
            if linea.strip().startswith("CLAVE_PANEL:"):
                return linea.split(":", 1)[1].strip()
    return ""


def limpiar_clave(valor):
    """Los guiones y las mayusculas no cuentan: la clave se puede escribir como sea."""
    return re.sub(r"[\s-]", "", valor or "").lower()


CLAVE_PANEL = os.environ.get("CLAVE_PANEL", "").strip() or leer_clave_del_archivo()
CLAVE_PANEL_LIMPIA = limpiar_clave(CLAVE_PANEL)

app = Flask(__name__, static_folder=".", static_url_path="")

# El panel de pedidos corre en la PC del local y consulta esta API, que esta
# en otro dominio. Sin esto el navegador bloquea la respuesta.
CORS(
    app,
    resources={r"/api/.*": {"origins": "*"}},
    allow_headers=["Content-Type", CABECERA_CLAVE],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
)


def panel_permitido():
    """Si el pedido que llego puede tocar los datos del panel."""
    if not CLAVE_PANEL_LIMPIA:
        # Todavia no se configuro ninguna clave. En la PC del local el panel
        # funciona igual (es la maquina del local), pero en el host queda cerrado
        # para no dejar los pedidos a la vista de cualquiera.
        return not EN_RENDER
    enviada = limpiar_clave(request.headers.get(CABECERA_CLAVE, ""))
    return bool(enviada) and secrets.compare_digest(enviada, CLAVE_PANEL_LIMPIA)


def pedir_clave():
    """Devuelve la respuesta de error, o None si el pedido puede seguir."""
    if panel_permitido():
        return None
    return jsonify({"error": "Falta la clave del panel", "codigo": "sin_clave"}), 401



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
    # Sin clave no se avisa: si cualquiera pudiera mandar latidos, el host nunca
    # detectaria que el local esta cerrado.
    error = pedir_clave()
    if error:
        return error

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


@app.route("/api/panel/estado")
def estado_panel():
    """Solo para comprobar la clave. Si esta mal, responde 401."""
    error = pedir_clave()
    if error:
        return error

    if not CLAVE_PANEL_LIMPIA:
        # en la PC del local puede no haber clave puesta: el panel abre igual
        return jsonify({"ok": True, "con_clave": False})

    return jsonify({"ok": True, "con_clave": True})


@app.route("/api/orders", methods=["GET", "POST", "DELETE"])
def orders():
    # El POST es el que usan los clientes para pedir, va sin clave. Todo lo demas
    # (mirar pedidos, cambiarlos de estado, borrarlos) es del dueno.
    if request.method != "POST":
        error = pedir_clave()
        if error:
            return error

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
    error = pedir_clave()
    if error:
        return error

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
    error = pedir_clave()
    if error:
        return error

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
        peticion = urllib.request.Request(
            URL_HOST + "/api/orders",
            # sin la clave el host no devuelve nada: los pedidos llevan datos
            # de los clientes y esa informacion solo se ve con la clave del panel
            headers={CABECERA_CLAVE: CLAVE_PANEL},
        )
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            pedidos = json.loads(respuesta.read().decode("utf-8"))
    except Exception:
        # si el host no responde no pasa nada, se reintenta en el proximo ciclo
        return 0

    return guardar_en_archivo(pedidos)


AVISO_CLAVE_MOSTRADO = False


def avisar_que_el_local_esta_abierto():
    """Le dice al host que esta PC sigue encendida."""
    peticion = urllib.request.Request(
        URL_HOST + "/api/local/latido",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            # el host pide la misma clave del panel para creerle el latido
            CABECERA_CLAVE: CLAVE_PANEL,
        },
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=15) as respuesta:
        respuesta.read()


def avisar_falta_la_clave():
    """Lo dice una sola vez, no cada 5 segundos."""
    global AVISO_CLAVE_MOSTRADO
    if AVISO_CLAVE_MOSTRADO:
        return
    AVISO_CLAVE_MOSTRADO = True
    print("")
    print("No hay clave del panel en esta PC, asi que el host no puede saber")
    print("que el local esta abierto. Agrega esta linea en el archivo")
    print(f"  {ARCHIVO_CLAVE}")
    print("y reinicia el host.")


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
            if not CLAVE_PANEL_LIMPIA:
                avisar_falta_la_clave()
            else:
                print("No se pudo avisar al host que el local esta abierto:", error)
        time.sleep(INTERVALO_SINCRONIZACION)


@app.route("/api/archivo", methods=["GET", "POST"])
def archivo_pedidos():
    """El archivo local: GET lo lee, POST agrega un pedido."""
    error = pedir_clave()
    if error:
        return error

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

    serve(app, host="0.0.0.0", port=PUERTO, threads=8)


# --- cartel de consola (misma estetica que instalar_requerimientos.py) ---

def mostrar_mensaje(texto):
    """Imprime sin problemas caracteres especiales en la consola de Windows."""
    print(texto.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()


def mostrar_titulo(subtitulo):
    mostrar_mensaje("=" * 60)
    mostrar_mensaje("  MODO HAMBRE")
    mostrar_mensaje(f"  {subtitulo}")
    mostrar_mensaje("=" * 60)
    mostrar_mensaje("")


def mostrar_aviso(titulo, lineas=()):
    mostrar_mensaje("-" * 60)
    mostrar_mensaje(f"  {titulo}")
    for linea in lineas:
        mostrar_mensaje(f"  {linea}")
    mostrar_mensaje("-" * 60)
    mostrar_mensaje("")


def esperar_servidor(intentos=40):
    """Espera a que el servidor responda en lugar de asumir que levanto."""
    for _ in range(intentos):
        try:
            with urllib.request.urlopen(URL_LOCAL, timeout=2):
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.25)
    return False


# En la PC del local el archivo se mantiene solo: no hace falta que el panel este
# abierto para que los pedidos queden guardados en el disco.
if not EN_RENDER:
    threading.Thread(target=sincronizar_en_segundo_plano, daemon=True).start()


if __name__ == "__main__":
    mostrar_titulo("Servidor local del local")

    if puerto_ocupado(PUERTO):
        mostrar_aviso(
            f"El puerto {PUERTO} ya esta en uso.",
            [
                "Casi seguro ya hay otra ventana de Modo Hambre abierta.",
                "Cerrala con Ctrl+C o cerrando la ventana,",
                "y volve a abrir el programa.",
            ],
        )
        input("\nPresiona ENTER para cerrar...")
        sys.exit(1)

    try:
        import waitress  # noqa: F401
    except ImportError:
        mostrar_aviso(
            "Falta la dependencia 'waitress'.",
            [
                "Instalala con doble clic en instalar_requerimientos.py",
                '(o con "pip install -r requirements.txt").',
            ],
        )
        input("\nPresiona ENTER para cerrar...")
        sys.exit(1)

    mostrar_mensaje("Arrancando el host...")
    servidor = threading.Thread(target=run_http_server, daemon=True)
    servidor.start()

    if not esperar_servidor():
        mostrar_aviso(
            "El host no se pudo levantar.",
            [f"Revisa si el puerto {PUERTO} esta ocupado:"],
            ["  netstat -ano | findstr :5000"],
        )
        input("\nPresiona ENTER para cerrar...")
        sys.exit(1)

    mostrar_aviso(
        "Host levantado con exito.",
        [
            f"Pagina para tus clientes:  {URL_LOCAL}",
            f"Panel de pedidos:         {URL_LOCAL}/admin.html",
            f"Archivo local de pedidos: {URL_LOCAL}/archivo.html",
            "",
            "El panel recibe los pedidos que hacen tus clientes",
            "en la web.",
        ],
    )
    if not CLAVE_PANEL_LIMPIA:
        mostrar_mensaje("  Sin clave del panel: en el host, el panel queda cerrado.")
    else:
        mostrar_mensaje("  El panel pide la clave del local para poder entrar.")
    mostrar_mensaje("")
    mostrar_mensaje("Presione Ctrl+C para apagar el host.")
    mostrar_mensaje("")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        mostrar_mensaje("")
        mostrar_mensaje("Apagando el host...")
        mostrar_mensaje("")
