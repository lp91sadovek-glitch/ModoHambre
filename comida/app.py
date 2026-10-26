import atexit
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

try:
    from psycopg_pool import ConnectionPool, PoolTimeout
except Exception:
    ConnectionPool = None

    class PoolTimeout(Exception):
        """Sin psycopg_pool nunca se tira; esta solo para que el except exista."""

BASE_DIR = Path(__file__).resolve().parent

# Render pone RENDER=true en el entorno. Ahi el panel nunca queda sin clave.
EN_RENDER = os.environ.get("RENDER", "").lower() == "true"

# ---------------------------------------------------------------------------
# CLAVE DEL PANEL
#
# El panel muestra los pedidos con nombre, telefono y direccion del cliente, asi
# que no puede quedar abierto en internet. El dueno escribe la clave y recien ahi
# puede verlos.
#
# La clave se busca en dos lugares, en este orden:
#   1. La variable de entorno CLAVE_PANEL de Render.
#   2. La linea "CLAVE_PANEL:" del archivo de texto (solo para probar en una
#      PC). Ese archivo no se sube al repositorio para que la clave no quede
#      a la vista de cualquiera.
# ---------------------------------------------------------------------------

CABECERA_CLAVE = "X-Clave-Panel"
ARCHIVO_CLAVE = "para abrir el hostlocal.txt"


def leer_clave_del_archivo():
    """Busca la linea 'CLAVE_PANEL:' en el archivo de texto (para probar en una PC)."""
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

# ---------------------------------------------------------------------------
# BASE DE DATOS NEON (Postgres)
#
# El menu y datos del cliente se guardan en Neon. Patron igual que la clave:
#   1. Variable de entorno DATABASE_URL (Render/entorno)
#   2. Archivo 'para abrir la base de datos.txt' (para probar en una PC)
# ---------------------------------------------------------------------------

ARCHIVO_DB = "para abrir la base de datos.txt"


# Palabras que aparecen en las URLs de ejemplo. Si una de estas esta en la
# URL, es que se copio el ejemplo y no la URL real, asi que mejor no intentar
# conectarse: se pierde el tiempo esperando un error de la base.
MARCAS_DE_EJEMPLO = ("USUARIO", "CLAVE@", "ep-xxx", "TU_USUARIO", "TU_CLAVE", "xxxx")


def url_de_conexion_valida(url):
    """Si la URL parece una de verdad y no el ejemplo de la guía."""
    if not url:
        return False
    if not url.startswith("postgresql://") and not url.startswith("postgres://"):
        return False
    if "@" not in url:
        return False
    if any(marca in url for marca in MARCAS_DE_EJEMPLO):
        return False
    return True


def leer_db_url_del_archivo():
    """Busca DATABASE_URL en archivo local.

    Se guide da dos formas de escribirla, porque el dueño la va a escribir como
    le quede comoda:

        DATABASE_URL: postgresql://...
        postgresql://...

    Las lineas que empiezan con # se ignoran, así se pueden dejar notas.
    """
    for carpeta in (BASE_DIR, BASE_DIR.parent):
        ruta = carpeta / ARCHIVO_DB
        if not ruta.exists():
            continue
        try:
            lineas = ruta.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for linea in lineas:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            if linea.upper().startswith("DATABASE_URL:"):
                url = linea.split(":", 1)[1].strip()
                if url_de_conexion_valida(url):
                    return url
            elif url_de_conexion_valida(linea):
                return linea
    return ""


def limpiar_url(url):
    """Neon da la URL de varias formas para copiar, y se pega como venga:

        postgresql://...
        'postgresql://...'
        psql 'postgresql://...'
        DATABASE_URL=postgresql://...

    Con comillas o con "psql" adelante la URL parecia invalida y el host
    mostraba siempre el menu de respaldo, sin decir por que.
    """
    url = (url or "").strip()
    for prefijo in ("DATABASE_URL=", "psql "):
        if url.startswith(prefijo):
            url = url[len(prefijo):].strip()
    return url.strip("'\"").strip()


DATABASE_URL = limpiar_url(os.environ.get("DATABASE_URL", ""))
if EN_RENDER and not url_de_conexion_valida(DATABASE_URL):
    # Se ve en los "Logs" de Render. Sin esto, la unica pista era que la web
    # mostraba los precios viejos del HTML.
    print("ATENCION: falta DATABASE_URL (o no es valida) en Environment de Render."
          " El menu sale del HTML de respaldo y los cambios del editor no se ven.",
          flush=True)
if not url_de_conexion_valida(DATABASE_URL):
    DATABASE_URL = leer_db_url_del_archivo()

# Avisos que se escriben una sola vez, para no llenar la consola. En la PC del
# local la consola es la unica forma de saber que algo pasa.
AVISO_BASE_MOSTRADO = 0.0
AVISO_PSYCOPG_MOSTRADO = False

# El menu se lee mucho mas veces de las que se escribe, asi que se guarda en
# memoria del servidor. Sin esto, cada visita de un cliente seria una consulta
# a Neon, y en el plan gratis el computo se acaba.
#
# Son dos minutos y medio? No: un minuto. Es el tiempo maximo que tarda un
# cambio del dueno en llegar a un cliente que ya tiene la pagina abierta.
SEGUNDOS_CACHE_MENU = 60
# Si la base no responde, no se reintenta en cada pedido: se espera un poco
# antes de volver a golpear, asi una caida de internet no se convierte en un
# intento de conexion por cada visita.
SEGUNDOS_CACHE_FALLIDO = 20

# El menu se guarda en memoria para no ir a Neon en cada visita. Hay DOS
#(menu del cliente y menu del editor) y van en lugares separados a proposito:
# el del cliente no muestra las comidas apagadas ni las categorias vacias, y el
# del editor si las tiene que ver. Con un solo lugar para los dos, con que el
# dueño abriera el panel, todos los clientes veian durante un minuto las
# comidas apagadas y los titulos vacios.
_CACHE_VACIA = {"valor": None, "vence": 0.0, "fallo": False}
_cache_menu = {
    "clientes": dict(_CACHE_VACIA),
    "editor": dict(_CACHE_VACIA),
}
_cache_lock = threading.Lock()

# Las fotos tambien quedan en memoria: una foto nunca cambia (otra foto es otro
# id), y sin esto cada cliente nuevo abria una conexion a Neon por cada foto
# del menu (26 conexiones por visita), lo que despierta la base y gasta la
# cuota gratis. Con fotos de 100-200 KB, 25 MB alcanzan para todo el menu.
MAXIMO_CACHE_FOTOS = 25 * 1024 * 1024
_cache_fotos = {}  # id -> (mime, bytes)

app = Flask(__name__, static_folder=".", static_url_path="")

# Limitar tamaño de subidas (imágenes). Sin esto, cualquiera que sepa la
# direccion del host puede mandar un archivo de 2 GB y quedarle sin memoria.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# Por si alguna pagina se abre desde otro dominio (por ejemplo, para probar).
# La clave va en una cabecera y no en cookies, asi que esto no la expone.
CORS(
    app,
    resources={r"/api/.*": {"origins": "*"}},
    allow_headers=["Content-Type", CABECERA_CLAVE],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)


def panel_permitido():
    """Si el pedido que llego puede tocar los datos del panel."""
    if not CLAVE_PANEL_LIMPIA:
        # Todavia no se configuro ninguna clave. Probando en una PC el panel
        # funciona igual, pero en Render queda cerrado para no dejar los
        # pedidos a la vista de cualquiera.
        return not EN_RENDER
    enviada = limpiar_clave(request.headers.get(CABECERA_CLAVE, ""))
    return bool(enviada) and secrets.compare_digest(enviada, CLAVE_PANEL_LIMPIA)


# ---------------------------------------------------------------------------
# FRENOS CONTRA ABUSOS
#
# Todo se cuenta en memoria y por conexion (la IP de quien pide). Render tiene
# un solo proceso, asi que alcanza; si se reinicia, los contadores arrancan de
# cero, que no es grave.
# ---------------------------------------------------------------------------

_frenos_lock = threading.Lock()
_ventanas = {}        # (tipo, quien) -> lista de momentos
_claves_falladas = {}  # ip -> {"claves": set, "bloqueado_hasta": momento}

MAXIMO_INTENTOS_CLAVE = 5
MINUTOS_BLOQUEO_CLAVE = 15


def ip_del_cliente():
    """La IP real de quien pide.

    Render pasa todo por Cloudflare, que pone la IP verdadera en
    CF-Connecting-IP y no deja que el visitante la cambie. X-Forwarded-For en
    cambio lo puede inventar cualquiera (mandando otro distinto en cada
    intento se esquivaria el bloqueo), por eso va solo como ultima opcion.
    """
    real = request.headers.get("CF-Connecting-IP", "").strip()
    if real:
        return real
    reenviada = request.headers.get("X-Forwarded-For", "")
    return (reenviada.split(",")[0].strip() if reenviada else request.remote_addr) or "?"


def dentro_del_limite(tipo, quien, maximo, segundos):
    """True si 'quien' hizo menos de 'maximo' cosas de este tipo en 'segundos'."""
    ahora = time.time()
    with _frenos_lock:
        momentos = [m for m in _ventanas.get((tipo, quien), []) if ahora - m < segundos]
        if len(momentos) >= maximo:
            _ventanas[(tipo, quien)] = momentos
            return False
        momentos.append(ahora)
        _ventanas[(tipo, quien)] = momentos
        # de vez en cuando se borra lo viejo, para que no crezca para siempre
        if len(_ventanas) > 5000:
            for clave in [c for c, v in _ventanas.items() if not v or ahora - v[-1] > 3600]:
                _ventanas.pop(clave, None)
    return True


def pedir_clave():
    """Devuelve la respuesta de error, o None si el pedido puede seguir.

    Maximo 5 claves equivocadas por conexion: despues de la quinta, esa
    conexion queda bloqueada 15 minutos (aunque pruebe la correcta), asi nadie
    puede probar claves sin parar hasta adivinarla. Se cuentan claves
    distintas: el panel manda varios pedidos con la misma clave, y una clave
    vieja guardada no tiene que bloquear al dueno de una.
    """
    ip = ip_del_cliente()
    ahora = time.time()
    with _frenos_lock:
        registro = _claves_falladas.get(ip)
        if registro and registro["bloqueado_hasta"] > ahora:
            minutos = int((registro["bloqueado_hasta"] - ahora) // 60) + 1
            return jsonify({
                "error": f"Demasiados intentos con la clave equivocada. Esperá {minutos} "
                         f"minuto{'s' if minutos != 1 else ''} y volvé a probar.",
                "codigo": "bloqueado",
                "minutos": minutos,
            }), 429

    if panel_permitido():
        with _frenos_lock:
            _claves_falladas.pop(ip, None)
        return None

    enviada = limpiar_clave(request.headers.get(CABECERA_CLAVE, ""))
    if not enviada:
        # sin clave todavia (el panel recien abierto): no cuenta como intento
        return jsonify({"error": "Falta la clave del panel", "codigo": "sin_clave"}), 401

    with _frenos_lock:
        registro = _claves_falladas.setdefault(ip, {"claves": set(), "bloqueado_hasta": 0})
        # se guarda solo un resumen de la clave probada, nunca la clave
        registro["claves"].add(hash(enviada))
        intentos = len(registro["claves"])
        if intentos >= MAXIMO_INTENTOS_CLAVE:
            registro["claves"] = set()
            registro["bloqueado_hasta"] = ahora + MINUTOS_BLOQUEO_CLAVE * 60
            print(f"Clave del panel: {MAXIMO_INTENTOS_CLAVE} intentos equivocados desde {ip}, "
                  f"bloqueada {MINUTOS_BLOQUEO_CLAVE} minutos.", flush=True)
            return jsonify({
                "error": f"Demasiados intentos con la clave equivocada. Esperá "
                         f"{MINUTOS_BLOQUEO_CLAVE} minutos y volvé a probar.",
                "codigo": "bloqueado",
                "minutos": MINUTOS_BLOQUEO_CLAVE,
            }), 429
    restantes = MAXIMO_INTENTOS_CLAVE - intentos
    return jsonify({
        "error": "Esa clave no es correcta.",
        "codigo": "sin_clave",
        "intentos_restantes": restantes,
    }), 401


# Flask sirve la carpeta entera como archivos de la pagina (static_folder="."),
# asi que sin este filtro cualquiera podia bajarse el codigo o los archivos de
# texto con las claves, sin clave. Solo salen los tipos de archivo que una
# pagina web necesita.
EXTENSIONES_PUBLICAS = {
    ".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
    ".ico", ".mp4", ".webm", ".woff", ".woff2", ".ttf",
    # manifest.webmanifest: lo que hace que en el iPhone la pagina se pueda
    # agregar a la pantalla de inicio como una app (y recibir avisos)
    ".webmanifest",
}
mimetypes.add_type("application/manifest+json", ".webmanifest")


@app.before_request
def no_mostrar_archivos_privados():
    path = request.path
    if path == "/" or path.startswith("/api/"):
        return None
    if Path(path).suffix.lower() not in EXTENSIONES_PUBLICAS:
        return jsonify({"error": "No encontrado"}), 404
    return None


@app.after_request
def no_cache(response):
    """Casi todo sale sin cache, pero el menu y las fotos si pueden guardarse.

    Los pedidos, el estado del local y el panel no se cachean nunca: son datos
    que cambian todo el tiempo y Cache-Control es lo unico que los mantiene
    frescos en los equipos del dueno y de los clientes.

    El menu y las imagenes al reves: no cambian solos, y como el menu esta en
    Neon (que se apaga a los 5 minutos y tarda un poco mas en despertar), cada
    consulta que se evita es computo que no se gasta de la cuota gratis.
    """
    path = request.path
    if path.startswith("/api/imagenes/") and response.status_code == 200:
        # La foto de un id nunca cambia: si el dueno sube otra, es otra id y
        # por lo tanto otra URL. Se puede guardar en el navegador para siempre.
        # Solo si salio bien: un 404 guardado "para siempre" dejaba la foto
        # rota un año en ese celular aunque la base volviera enseguida.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    if path == "/api/menu" and not response.headers.get("X-Menu-Respaldo"):
        # Corto a proposito: si el dueno cambia un precio, a los clientes les
        # llega el cambio en menos de un minuto.
        response.headers["Cache-Control"] = "public, max-age=60"
        return response
    response.headers["Cache-Control"] = "no-store"
    return response


# Neon/Postgres helpers
def get_pg_conn():
    """Abre la conexion con Neon, o devuelve None si no se pudo.

    Antes esto se comia todos los errores sin decir nada, y cuando el menu no
    aparecia no habia forma de saber si era la base, la URL o el internet. Ahora
    el error se escribe en la consola.
    """
    if not DATABASE_URL:
        return None
    if psycopg is None:
        avisar_falta_psycopg()
        return None
    try:
        # connect_timeout: si no hay internet, no queda colgado el pedido del
        # cliente esperando que el sistema operativo de por si un timeout.
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
        conn.autocommit = False
        return conn
    except Exception as error:
        avisar_error_de_base(error)
        return None


def avisar_falta_psycopg():
    global AVISO_PSYCOPG_MOSTRADO
    if AVISO_PSYCOPG_MOSTRADO:
        return
    AVISO_PSYCOPG_MOSTRADO = True
    print("")
    print("Falta el driver de Postgres (psycopg), asi que el menu no se puede")
    print("leer ni editar. Instala las dependencias con")
    print("  pip install -r requirements.txt")


def avisar_error_de_base(error):
    # Como mucho uno por minuto. Antes salia una sola vez en toda la vida del
    # programa, y despues del primer corte de internet ningun error nuevo
    # aparecia en la consola.
    global AVISO_BASE_MOSTRADO
    ahora = time.time()
    if ahora - AVISO_BASE_MOSTRADO < 60:
        return
    AVISO_BASE_MOSTRADO = ahora
    print("")
    print("No se pudo conectar con la base de datos de Neon:")
    print(f"  {type(error).__name__}: {error}")
    if not DATABASE_URL:
        print("  No hay URL de conexion. Revisa el archivo")
        print(f"  {ARCHIVO_DB}")
        print("  o la variable de entorno DATABASE_URL.")
    else:
        print("  La URL esta puesta. Revisa que sea la POOLED (la que tiene")
        print("  '-pooler' en el nombre del host) y que la base este viva.")
    print("  Mientras tanto el menu sale del HTML de respaldo.")


# Las conexiones a Neon se reusan. Render esta en Estados Unidos y Neon en San
# Pablo: abrir una conexion nueva (TCP + cifrado + clave) son varios viajes de
# ida y vuelta y tardaba mas de un segundo POR PEDIDO, asi que cada boton del
# panel tardaba varios segundos. Con el pool la conexion ya esta abierta.
#
# min_size=0 y max_idle: si nadie usa la base por 2 minutos las conexiones se
# cierran, y Neon se puede dormir (asi no se gasta la cuota gratis de mas).
_pool = None
_pool_lock = threading.Lock()

# Si la base no responde, durante estos segundos no se la vuelve a esperar:
# cada pedido contesta "sin base" al instante en vez de quedarse colgado.
SEGUNDOS_BASE_CAIDA = 15
_base_caida = {"hasta": 0.0}


def marcar_base_caida():
    _base_caida["hasta"] = time.time() + SEGUNDOS_BASE_CAIDA


def obtener_pool():
    global _pool
    if _pool is not None or ConnectionPool is None or not DATABASE_URL or psycopg is None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=0,
                max_size=6,
                max_idle=120,
                timeout=6,
                # prepare_threshold=None: el "-pooler" de Neon (pgbouncer) no
                # se lleva bien con las consultas preparadas.
                # keepalives y tcp_user_timeout: si Neon se durmio y la
                # conexion guardada quedo cortada, se nota en segundos y se
                # abre otra, en vez de quedarse esperando una respuesta que
                # no va a llegar.
                kwargs={"row_factory": dict_row, "connect_timeout": 10,
                        "prepare_threshold": None,
                        "keepalives": 1, "keepalives_idle": 30,
                        "keepalives_interval": 10, "keepalives_count": 3,
                        "tcp_user_timeout": 8000},
                open=True,
            )
            # Al cerrar el programa se cierra el pool enseguida, en vez de
            # esperar sus hilos 5 segundos cada uno.
            atexit.register(_pool.close, timeout=1)
    return _pool


def reiniciar_pool(viejo):
    """Tira el pool trabado y deja que el proximo pedido arme uno nuevo.

    Paso en Render: Neon estaba dormido, el pool fallo al abrir conexiones y
    quedo trabado para siempre (cada pedido esperaba 8 segundos y fallaba),
    aunque la base andaba bien. Con un pool nuevo se arregla solo.
    """
    global _pool
    with _pool_lock:
        if _pool is not viejo:
            return  # otro pedido ya lo reinicio
        _pool = None
    _reinicios_pool["cantidad"] += 1
    _reinicios_pool["ultimo"] = time.time()
    # El viejo se cierra aparte: cerrarlo puede tardar y nadie lo espera.
    threading.Thread(target=lambda: viejo.close(timeout=1), daemon=True).start()


_reinicios_pool = {"cantidad": 0, "ultimo": 0.0}


def recorrer_base(funcion, por_defecto=None, transaccion=True):
    """Toma una conexion, hace el trabajo, y la devuelve pase lo que pase.

    Con transaccion=True (lo que hace mas de una cosa, como el editor) se
    confirma todo junto o nada. Con transaccion=False cada consulta se guarda
    sola: es para lo que hace una sola consulta (los pedidos, el panel), y se
    ahorra el BEGIN y el COMMIT, que son dos viajes mas a San Pablo.
    """
    if obtener_pool() is None:
        return _recorrer_sin_pool(funcion, por_defecto)
    if time.time() < _base_caida["hasta"]:
        return por_defecto

    for intento in (1, 2):
        pool = obtener_pool()
        try:
            with pool.connection() as conn:
                conn.autocommit = not transaccion
                # Al salir del with sin error se hace commit; con error, rollback.
                return funcion(conn.cursor())
        except PoolTimeout as error:
            # No se pudo conseguir ninguna conexion. Puede ser que el pool se
            # haya trabado (la base anda): se arma uno nuevo y se prueba una
            # vez mas. Si con el nuevo tampoco, la base no responde: por un
            # rato se contesta "sin base" al instante, asi la pagina no se
            # cuelga esperando y el panel y el menu siguen andando.
            reiniciar_pool(pool)
            if intento == 2:
                marcar_base_caida()
                avisar_error_de_base(error)
                return por_defecto
        except psycopg.OperationalError as error:
            # Una conexion guardada que se corto (Neon se durmio, se reinicio
            # el pooler): se tira y se prueba una vez con otra.
            if intento == 2:
                avisar_error_de_base(error)
                return por_defecto
        except Exception as error:
            avisar_error_de_base(error)
            return por_defecto
    return por_defecto


def _recorrer_sin_pool(funcion, por_defecto):
    """Lo de siempre, por si falta psycopg_pool: una conexion por trabajo."""
    conn = get_pg_conn()
    if conn is None:
        return por_defecto
    try:
        resultado = funcion(conn.cursor())
        conn.commit()
        return resultado
    except Exception as error:
        try:
            conn.rollback()
        except Exception:
            pass
        avisar_error_de_base(error)
        return por_defecto
    finally:
        try:
            conn.close()
        except Exception:
            pass


TABLAS_NEON = (
    """
    CREATE TABLE IF NOT EXISTS categorias (
      id SERIAL PRIMARY KEY,
      nombre TEXT NOT NULL,
      icono TEXT,
      orden INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS imagenes (
      id SERIAL PRIMARY KEY,
      nombre TEXT NOT NULL,
      mime TEXT NOT NULL,
      contenido BYTEA NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comidas (
      id SERIAL PRIMARY KEY,
      categoria_id INTEGER REFERENCES categorias(id) ON DELETE CASCADE,
      nombre TEXT NOT NULL,
      descripcion TEXT,
      imagen INTEGER REFERENCES imagenes(id) ON DELETE SET NULL,
      precio INTEGER NOT NULL DEFAULT 0,
      tipo TEXT NOT NULL DEFAULT 'simple',
      orden INTEGER NOT NULL DEFAULT 0,
      activo BOOLEAN NOT NULL DEFAULT TRUE,
      ancla TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gustos (
      id SERIAL PRIMARY KEY,
      comida_id INTEGER NOT NULL REFERENCES comidas(id) ON DELETE CASCADE,
      nombre TEXT NOT NULL,
      precio INTEGER NOT NULL DEFAULT 0,
      orden INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clientes (
      id SERIAL PRIMARY KEY,
      telefono TEXT NOT NULL UNIQUE,
      nombre TEXT,
      apellido TEXT,
      direccion TEXT
    )
    """,
    # El menu se lee entero y siempre en el mismo orden. Sin estos indices,
    # Postgres ordena las filas cada vez que se pide el menu.
    "CREATE INDEX IF NOT EXISTS comidas_orden ON comidas (orden, id)",
    "CREATE INDEX IF NOT EXISTS comidas_categoria ON comidas (categoria_id)",
    "CREATE INDEX IF NOT EXISTS gustos_comida ON gustos (comida_id, orden, id)",
    "CREATE INDEX IF NOT EXISTS categorias_orden ON categorias (orden, id)",
    # Los pedidos. "oculto" es "sacado de la pantalla del panel": el pedido no
    # se borra, sigue en el registro. "migrado_de" quedo de cuando se pasaron
    # los pedidos viejos de la PC del local a Neon (marca de donde vino cada uno).
    """
    CREATE TABLE IF NOT EXISTS pedidos (
      id SERIAL PRIMARY KEY,
      items JSONB NOT NULL,
      total INTEGER NOT NULL,
      estado TEXT NOT NULL DEFAULT 'nuevo',
      envio TEXT NOT NULL DEFAULT 'local',
      cliente JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      oculto BOOLEAN NOT NULL DEFAULT FALSE,
      migrado_de TEXT UNIQUE
    )
    """,
    "CREATE INDEX IF NOT EXISTS pedidos_visibles ON pedidos (oculto, id)",
    # Seguimiento del pedido por el cliente: "seguimiento" es un codigo al azar
    # que solo tiene el navegador que hizo el pedido (sin el, nadie puede ver
    # el estado de un pedido ajeno). "avisos" es la suscripcion a las
    # notificaciones del celular, si el cliente las acepto.
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS seguimiento TEXT",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS avisos JSONB",
    # A que hora el local toco "Recibir" y "Listo": el cliente lo ve en la
    # linea de tiempo de su pedido, como en las apps de delivery.
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS recibido_at TIMESTAMPTZ",
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS listo_at TIMESTAMPTZ",
    # Y cuando se entrego (a domicilio) o lo retiraron (en el local).
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS entregado_at TIMESTAMPTZ",
    # Si el cliente cancelo el pedido (solo puede antes de que el local lo reciba).
    "ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS cancelado_at TIMESTAMPTZ",
    # Los comentarios del formulario de contacto (los ve el dueno en el panel).
    """
    CREATE TABLE IF NOT EXISTS comentarios (
      id SERIAL PRIMARY KEY,
      nombre TEXT NOT NULL,
      email TEXT,
      telefono TEXT,
      asunto TEXT,
      mensaje TEXT NOT NULL,
      leido BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # Ajustes sueltos del local, por ahora solo si esta abierto o cerrado.
    """
    CREATE TABLE IF NOT EXISTS ajustes (
      clave TEXT PRIMARY KEY,
      valor TEXT NOT NULL
    )
    """,
)


def init_db_neon():
    """Crea las tablas del menu si no existen. Corre al arrancar, siempre.

    Si la base esta dormida (Neon la apaga a los 5 minutos) la primera
    consulta tarda un poco mas, pero por eso usa la version POOLED de la URL.
    """
    def trabajo(cur):
        for sentencia in TABLAS_NEON:
            cur.execute(sentencia)

    recorrer_base(trabajo)


init_db_neon()


# ---------------------------------------------------------------------------
# EL MENU EN NEON
#
# Aca va todo lo que el dueno puede cambiar desde el panel: categorias,
# comidas, gustos y fotos. Lo que los clientes ven sale de /api/menu.
#
# Los pedidos tambien estan en Neon (mas abajo). Ojo con la cuota gratis:
# mientras el panel esta abierto consulta la base cada pocos segundos, asi que
# la base no se duerme. Cerrar el panel cuando el local cierra.
# ---------------------------------------------------------------------------


def olvidar_menu():
    """Vacía el menu guardado en memoria.

    Se llama despues de cada cambio del dueno, asi el cambio se ve al
    instante y no al minuto siguiente. Se vacian las DOS vistas: un cambio
    afecta al menu del cliente y al del editor por igual.
    """
    with _cache_lock:
        for vista in _cache_menu.values():
            vista["valor"] = None
            vista["vence"] = 0.0
            vista["fallo"] = False


def _consultar_menu(cur, solo_activas):
    """Lee el menu entero con tres consultas, no una por comida.

    La version anterior hacia una consulta por categoria y otra por comida (35
    viajes de ida y vuelta a Neon para un menu de 8 categorias). Con una base
    que esta a un click de distancias y a veces dormida, eso se nota. Ahora son
    tres consultas fijas y el ordenado se hace aca.
    """
    cur.execute("SELECT id, nombre, icono, orden FROM categorias ORDER BY orden, id")
    categorias = [dict(fila) for fila in cur.fetchall()]
    if not categorias:
        return []

    cur.execute(
        "SELECT id, categoria_id, nombre, descripcion, imagen, precio, tipo, orden, activo,"
        " ancla"
        "  FROM comidas"
        " WHERE categoria_id = ANY(%s)"
        " ORDER BY orden, id",
        ([categoria["id"] for categoria in categorias],),
    )
    comidas = [dict(fila) for fila in cur.fetchall()]

    ids_comidas = [comida["id"] for comida in comidas] or [0]
    cur.execute(
        "SELECT id, comida_id, nombre, precio, orden"
        "  FROM gustos"
        " WHERE comida_id = ANY(%s)"
        " ORDER BY orden, id",
        (ids_comidas,),
    )
    por_id_comida = {}
    for fila in cur.fetchall():
        fila = dict(fila)
        por_id_comida.setdefault(fila["comida_id"], []).append(fila)

    for comida in comidas:
        comida["gustos"] = por_id_comida.get(comida["id"], [])
        # La URL de la foto la arma el servidor: el navegador no tiene que
        # saber que las fotos viven en la base.
        comida["imagen_url"] = (
            f"/api/imagenes/{comida['imagen']}" if comida["imagen"] else None
        )

    por_id_categoria = {}
    for comida in comidas:
        por_id_categoria.setdefault(comida["categoria_id"], []).append(comida)

    for categoria in categorias:
        lista = por_id_categoria.get(categoria["id"], [])
        if solo_activas:
            lista = [comida for comida in lista if comida["activo"]]
        categoria["comidas"] = lista

    if solo_activas:
        # Una categoria sin comidas visibles no se muestra: es mejor que el
        # cliente no vea un titulo que al abrirlo no tenga nada.
        categorias = [c for c in categorias if c["comidas"]]

    return categorias


def obtener_menu(solo_activas=True, usar_cache=True):
    """Devuelve (categorias, vino_de_la_base).

    El False del segundo valor es la senal para que la pagina del cliente use
    el menu de respaldo escrito en el HTML: asi, si Neon esta caido o la PC se
    queda sin internet, los clientes igual ven el menu.
    """
    vista = _cache_menu["editor" if not solo_activas else "clientes"]

    with _cache_lock:
        if usar_cache and time.time() < vista["vence"]:
            # Tambien se guarda un fallo (por SEGUNDOS_CACHE_FALLIDO): con la
            # base caida, cada visita no tiene que esperar su propio error.
            if vista["fallo"]:
                return [], False
            return vista["valor"], True

    categorias = recorrer_base(
        lambda cur: _consultar_menu(cur, solo_activas), por_defecto=None, transaccion=False
    )

    fallo = categorias is None
    with _cache_lock:
        vista["valor"] = None if fallo else categorias
        vista["fallo"] = fallo
        vista["vence"] = time.time() + (SEGUNDOS_CACHE_FALLIDO if fallo else SEGUNDOS_CACHE_MENU)
    return categorias or [], not fallo


# --- ayudas para lo que llega del editor del dueno ---


def texto_limpio(valor, maximo=200, requerido=False):
    """Quita espacios de mas y corta, para no guardar textos de 5000 letras."""
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if requerido and not texto:
        return None
    return texto[:maximo]


def precio_valido(valor):
    """Acepta 850, '850', '$850', '1.500' y devuelve un entero, o None si no es.

    Los precios del local son pesos enteros, sin centavos. Por eso '1.500' son
    mil quinientos y no uno con cinco, que es como lo escribe la gente.

    Devuelve None (un error) cuando no hay ningún número que se pueda
    entender. Devolver 0 en ese caso sería peor: convertiría una errata en una
    comida gratis.
    """
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        numero = valor
    elif isinstance(valor, float):
        numero = round(valor)
    else:
        texto = str(valor or "").strip()
        crudo = re.sub(r"[^\d.,]", "", texto)
        if not crudo:
            # Sin ningún dígito: si tampoco se escribió nada, es un precio sin
            # cargar todavía (0); si se escribió algo, no se entendió.
            return 0 if not texto else None
        while True:
            if "," in crudo and "." in crudo:
                separador = "," if crudo.rfind(",") > crudo.rfind(".") else "."
            elif "," in crudo:
                separador = ","
            else:
                separador = "."
            if separador not in crudo:
                break
            entero, _, decimales = crudo.rpartition(separador)
            if len(decimales) == 3 and entero:
                # Eran miles: "1.500" son 1500 y "1.234.567" son 1234567.
                crudo = re.sub(r"[.,]", "", entero) + decimales
                continue
            if len(decimales) in (1, 2) and entero:
                crudo = re.sub(r"[.,]", "", entero) + "." + decimales
            break
        try:
            numero = round(float(crudo))
        except ValueError:
            return None
    if numero < 0 or numero > 10_000_000:
        return None
    return numero


def entero_valido(valor, por_defecto=0):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return por_defecto


def id_o_nada(valor):
    """Un id de la base (entero positivo), o None si no vino o no es un id."""
    if isinstance(valor, bool):
        return None
    numero = entero_valido(valor, None)
    return numero if numero and numero > 0 else None


def revisar_ids_de_comida(cur, categoria_id, imagen_id):
    """Devuelve un texto de error si la categoria o la foto no existen.

    Sin esto, una categoria borrada mientras el dueño tenia la ventana abierta
    hacia fallar la clave foranea y el editor decia "no se pudo leer la base",
    que no era el problema.
    """
    if categoria_id is not None:
        cur.execute("SELECT 1 FROM categorias WHERE id = %s", (categoria_id,))
        if cur.fetchone() is None:
            return "Esa categoria ya no existe. Recarga la pagina."
    if imagen_id is not None:
        cur.execute("SELECT 1 FROM imagenes WHERE id = %s", (imagen_id,))
        if cur.fetchone() is None:
            return "Esa foto ya no existe. Volve a elegirla."
    return None


def borrar_fotos_sin_uso(cur, ids):
    """Borra las fotos de esa lista que ya no usa ninguna comida.

    Cuando el dueño cambia la foto de una comida o la borra, la foto vieja
    quedaba en la base para siempre, ocupando lugar de los 0,5 GB gratis.
    Solo se miran las fotos que se acaban de soltar: una foto recien subida
    que todavia no se asigno no se toca.
    """
    ids = [i for i in set(ids) if i]
    if not ids:
        return
    cur.execute(
        "DELETE FROM imagenes WHERE id = ANY(%s)"
        " AND NOT EXISTS (SELECT 1 FROM comidas WHERE comidas.imagen = imagenes.id)",
        (ids,),
    )
    with _cache_lock:
        for img_id in ids:
            _cache_fotos.pop(img_id, None)


def cuerpo_del_dueno():
    """Lo que mando el editor, o un diccionario vacio si no se entiende."""
    return request.get_json(silent=True) or {}


def sin_base():
    return jsonify({"error": "No se pudo leer la base de datos. Revisa la consola."}), 503


@app.errorhandler(413)
def archivo_muy_grande(_error):
    # Sin esto Flask devolvia una pagina HTML y el editor no podia leer el error.
    return jsonify({"error": "El archivo es muy grande (maximo 16 MB)"}), 413


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/menu")
def api_menu():
    """El menu que ven los clientes. Publico: no lleva clave, es el menu."""
    categorias, de_la_base = obtener_menu(solo_activas=True)
    respuesta = jsonify({"categorias": categorias, "desde_base": de_la_base})
    if not de_la_base:
        # Para que la pagina sepa que tiene que mostrar el menu del HTML.
        respuesta.headers["X-Menu-Respaldo"] = "1"
    return respuesta


@app.route("/api/imagenes/<int:img_id>")
def api_imagen(img_id):
    """Devuelve la foto. Publica: las ven los clientes, no tienen datos secretos."""
    with _cache_lock:
        guardada = _cache_fotos.get(img_id)
    if guardada:
        return Response(guardada[1], mimetype=guardada[0])

    def trabajo(cur):
        cur.execute("SELECT mime, contenido FROM imagenes WHERE id = %s", (img_id,))
        return cur.fetchone()

    fila = recorrer_base(trabajo, transaccion=False)
    if fila is None:
        # Puede ser que la foto no exista o que la base este caida. En los dos
        # casos el navegador va a mostrar el texto alt, asi que no se rompe nada.
        return jsonify({"error": "Foto no encontrada"}), 404
    contenido = bytes(fila["contenido"])
    with _cache_lock:
        ocupado = sum(len(datos) for _, datos in _cache_fotos.values())
        if ocupado + len(contenido) <= MAXIMO_CACHE_FOTOS:
            _cache_fotos[img_id] = (fila["mime"], contenido)
    return Response(contenido, mimetype=fila["mime"])


# ---------------------------------------------------------------------------
# EDITAR EL MENU (todo esto lo hace el dueno, y pide la clave)
# ---------------------------------------------------------------------------


@app.route("/api/admin/menu")
def api_admin_menu():
    error = pedir_clave()
    if error:
        return error
    categorias, _ = obtener_menu(solo_activas=False, usar_cache=False)
    return jsonify({"categorias": categorias})


@app.route("/api/admin/categorias", methods=["POST"])
def api_crear_categoria():
    error = pedir_clave()
    if error:
        return error
    datos = cuerpo_del_dueno()
    nombre = texto_limpio(datos.get("nombre"), 80, requerido=True)
    if not nombre:
        return jsonify({"error": "Falta el nombre de la categoria"}), 400

    def trabajo(cur):
        # Se va al final sola, asi el dueno no tiene que acordarse del orden.
        cur.execute("SELECT COALESCE(MAX(orden), 0) + 10 AS siguiente FROM categorias")
        siguiente = cur.fetchone()["siguiente"]
        cur.execute(
            "INSERT INTO categorias (nombre, icono, orden) VALUES (%s, %s, %s)"
            " RETURNING id, nombre, icono, orden",
            (nombre, texto_limpio(datos.get("icono"), 8), siguiente),
        )
        return dict(cur.fetchone())

    nueva = recorrer_base(trabajo)
    if nueva is None:
        return sin_base()
    olvidar_menu()
    return jsonify(nueva), 201


@app.route("/api/admin/categorias/<int:categoria_id>", methods=["PUT"])
def api_editar_categoria(categoria_id):
    error = pedir_clave()
    if error:
        return error
    datos = cuerpo_del_dueno()

    def trabajo(cur):
        campos = []
        valores = []
        if "nombre" in datos:
            nombre = texto_limpio(datos.get("nombre"), 80, requerido=True)
            if not nombre:
                return "Falta el nombre de la categoria"
            campos.append("nombre = %s")
            valores.append(nombre)
        if "icono" in datos:
            campos.append("icono = %s")
            valores.append(texto_limpio(datos.get("icono"), 8))
        if "orden" in datos:
            campos.append("orden = %s")
            valores.append(entero_valido(datos.get("orden")))
        if not campos:
            return "No se mando ningun cambio"
        valores.append(categoria_id)
        cur.execute(
            f"UPDATE categorias SET {', '.join(campos)} WHERE id = %s"
            " RETURNING id, nombre, icono, orden",
            valores,
        )
        fila = cur.fetchone()
        return dict(fila) if fila else "Esa categoria ya no existe"

    resultado = recorrer_base(trabajo)
    if resultado is None:
        return sin_base()
    if isinstance(resultado, str):
        return jsonify({"error": resultado}), 400
    olvidar_menu()
    return jsonify(resultado)


@app.route("/api/admin/categorias/<int:categoria_id>", methods=["DELETE"])
def api_borrar_categoria(categoria_id):
    error = pedir_clave()
    if error:
        return error

    def trabajo(cur):
        cur.execute("SELECT imagen FROM comidas WHERE categoria_id = %s", (categoria_id,))
        fotos = [fila["imagen"] for fila in cur.fetchall()]
        # Las comidas y los gustos se van con la categoria (ON DELETE CASCADE).
        cur.execute("DELETE FROM categorias WHERE id = %s RETURNING id", (categoria_id,))
        if cur.fetchone() is None:
            return False
        borrar_fotos_sin_uso(cur, fotos)
        return True

    borrada = recorrer_base(trabajo)
    if borrada is None:
        return sin_base()
    if not borrada:
        return jsonify({"error": "Esa categoria ya no existe"}), 404
    olvidar_menu()
    return jsonify({"ok": True})


def lista_de_ids():
    """La lista de ids que manda el editor para reordenar, o None si no sirve."""
    ids = cuerpo_del_dueno().get("ids")
    if not isinstance(ids, list) or not ids:
        return None
    if not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        return None
    return ids


def guardar_orden(tabla, ids):
    """Le pone orden 10, 20, 30... a las filas, en el orden de la lista.

    Es una sola consulta para toda la lista, no una por fila: con la base en
    Sao Paulo cada viaje de ida y vuelta se nota.
    """
    def trabajo(cur):
        cur.execute(
            f"UPDATE {tabla} SET orden = nuevo.posicion * 10"
            "  FROM unnest(%s::int[]) WITH ORDINALITY AS nuevo(id, posicion)"
            f" WHERE {tabla}.id = nuevo.id",
            (ids,),
        )
        # Se devuelve un numero y no None: recorrer_base usa None para decir
        # "la base no anduvo", y el editor mostraba un error que no era real.
        return cur.rowcount

    return recorrer_base(trabajo)


@app.route("/api/admin/categorias/reordenar", methods=["POST"])
def api_reordenar_categorias():
    """Manda el orden completo de las categorias, de arriba abajo."""
    error = pedir_clave()
    if error:
        return error
    ids = lista_de_ids()
    if ids is None:
        return jsonify({"error": "La lista de categorias no es correcta"}), 400
    movidas = guardar_orden("categorias", ids)
    if movidas is None:
        return sin_base()
    olvidar_menu()
    return jsonify({"ok": True, "movidas": movidas})


@app.route("/api/admin/comidas", methods=["POST"])
def api_crear_comida():
    error = pedir_clave()
    if error:
        return error
    datos = cuerpo_del_dueno()
    nombre = texto_limpio(datos.get("nombre"), 120, requerido=True)
    if not nombre:
        return jsonify({"error": "Falta el nombre de la comida"}), 400
    precio = precio_valido(datos.get("precio", 0))
    if precio is None:
        return jsonify({"error": "El precio no es un numero"}), 400
    # Sin categoria la comida quedaba guardada pero no se veia en ningun lado.
    categoria_id = id_o_nada(datos.get("categoria_id"))
    if categoria_id is None:
        return jsonify({"error": "Falta elegir la categoria"}), 400
    imagen_id = id_o_nada(datos.get("imagen"))

    def trabajo(cur):
        problema = revisar_ids_de_comida(cur, categoria_id, imagen_id)
        if problema:
            return problema
        cur.execute(
            "SELECT COALESCE(MAX(orden), 0) + 10 AS siguiente"
            "  FROM comidas WHERE categoria_id = %s",
            (categoria_id,),
        )
        siguiente = cur.fetchone()["siguiente"]
        cur.execute(
            "INSERT INTO comidas (categoria_id, nombre, descripcion, imagen, precio,"
            " tipo, orden, activo)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING id, categoria_id, nombre, descripcion, imagen, precio, tipo,"
            " orden, activo, ancla",
            (
                categoria_id,
                nombre,
                texto_limpio(datos.get("descripcion"), 400),
                imagen_id,
                precio,
                "gustos" if datos.get("tipo") == "gustos" else "simple",
                siguiente,
                bool(datos.get("activo", True)),
            ),
        )
        return dict(cur.fetchone())

    nueva = recorrer_base(trabajo)
    if nueva is None:
        return sin_base()
    if isinstance(nueva, str):
        return jsonify({"error": nueva}), 400
    nueva["imagen_url"] = f"/api/imagenes/{nueva['imagen']}" if nueva["imagen"] else None
    nueva["gustos"] = []
    olvidar_menu()
    return jsonify(nueva), 201


@app.route("/api/admin/comidas/<int:comida_id>", methods=["PUT"])
def api_editar_comida(comida_id):
    error = pedir_clave()
    if error:
        return error
    datos = cuerpo_del_dueno()

    def trabajo(cur):
        campos = []
        valores = []
        categoria_id = None
        if "categoria_id" in datos:
            categoria_id = id_o_nada(datos.get("categoria_id"))
            if categoria_id is None:
                return "Falta elegir la categoria"
            campos.append("categoria_id = %s")
            valores.append(categoria_id)
        imagen_id = None
        if "imagen" in datos:
            imagen_id = id_o_nada(datos.get("imagen"))
            campos.append("imagen = %s")
            valores.append(imagen_id)
        problema = revisar_ids_de_comida(cur, categoria_id, imagen_id)
        if problema:
            return problema
        if "nombre" in datos:
            nombre = texto_limpio(datos.get("nombre"), 120, requerido=True)
            if not nombre:
                return "Falta el nombre de la comida"
            campos.append("nombre = %s")
            valores.append(nombre)
        if "descripcion" in datos:
            campos.append("descripcion = %s")
            valores.append(texto_limpio(datos.get("descripcion"), 400))
        if "precio" in datos:
            precio = precio_valido(datos.get("precio"))
            if precio is None:
                return "El precio no es un numero"
            campos.append("precio = %s")
            valores.append(precio)
        if "tipo" in datos:
            campos.append("tipo = %s")
            valores.append("gustos" if datos.get("tipo") == "gustos" else "simple")
        if "orden" in datos:
            campos.append("orden = %s")
            valores.append(entero_valido(datos.get("orden")))
        if "activo" in datos:
            campos.append("activo = %s")
            valores.append(bool(datos.get("activo")))
        if not campos:
            return "No se mando ningun cambio"
        cur.execute("SELECT imagen FROM comidas WHERE id = %s", (comida_id,))
        antes = cur.fetchone()
        if not antes:
            return "Esa comida ya no existe"
        valores.append(comida_id)
        cur.execute(
            f"UPDATE comidas SET {', '.join(campos)} WHERE id = %s"
            " RETURNING id, categoria_id, nombre, descripcion, imagen, precio, tipo,"
            " orden, activo, ancla",
            valores,
        )
        fila = cur.fetchone()
        if "imagen" in datos and antes["imagen"] != fila["imagen"]:
            borrar_fotos_sin_uso(cur, [antes["imagen"]])
        cur.execute(
            "SELECT id, comida_id, nombre, precio, orden FROM gustos"
            " WHERE comida_id = %s ORDER BY orden, id",
            (comida_id,),
        )
        fila = dict(fila)
        fila["gustos"] = [dict(gusto) for gusto in cur.fetchall()]
        return fila

    resultado = recorrer_base(trabajo)
    if resultado is None:
        return sin_base()
    if isinstance(resultado, str):
        return jsonify({"error": resultado}), 400
    resultado["imagen_url"] = (
        f"/api/imagenes/{resultado['imagen']}" if resultado["imagen"] else None
    )
    olvidar_menu()
    return jsonify(resultado)


@app.route("/api/admin/comidas/<int:comida_id>", methods=["DELETE"])
def api_borrar_comida(comida_id):
    error = pedir_clave()
    if error:
        return error

    def trabajo(cur):
        cur.execute("DELETE FROM comidas WHERE id = %s RETURNING imagen", (comida_id,))
        fila = cur.fetchone()
        if fila is None:
            return False
        borrar_fotos_sin_uso(cur, [fila["imagen"]])
        return True

    borrada = recorrer_base(trabajo)
    if borrada is None:
        return sin_base()
    if not borrada:
        return jsonify({"error": "Esa comida ya no existe"}), 404
    olvidar_menu()
    return jsonify({"ok": True})


def _gusto_desde(cur, datos, gusto_id=None):
    """Arma un INSERT o un UPDATE de un gusto. Devuelve la fila o un texto de error."""
    if gusto_id is None:
        nombre = texto_limpio(datos.get("nombre"), 120, requerido=True)
        if not nombre:
            return "Falta el nombre del gusto"
    else:
        # Al editar, el nombre es opcional: si el dueño solo quiere cambiar el
        # precio, no tiene que reescribir el nombre. Si no viene ninguno, se
        # deja el que ya estaba.
        nombre = texto_limpio(datos.get("nombre"), 120)

    # Al editar, si no vino el precio se deja el que estaba (None en el UPDATE).
    # Antes se tomaba como 0: cambiarle solo el nombre a un gusto lo dejaba gratis.
    if gusto_id is not None and "precio" not in datos:
        precio = None
    else:
        precio = precio_valido(datos.get("precio", 0))
        if precio is None:
            return "El precio no es un numero"

    if gusto_id is None:
        comida_id = datos.get("comida_id")
        cur.execute(
            "SELECT COALESCE(MAX(orden), 0) + 10 AS siguiente"
            "  FROM gustos WHERE comida_id = %s",
            (comida_id,),
        )
        siguiente = cur.fetchone()["siguiente"]
        cur.execute(
            "INSERT INTO gustos (comida_id, nombre, precio, orden) VALUES (%s, %s, %s, %s)"
            " RETURNING id, comida_id, nombre, precio, orden",
            (comida_id, nombre, precio, siguiente),
        )
    else:
        cur.execute(
            "UPDATE gustos SET nombre = COALESCE(NULLIF(%s, ''), nombre),"
            " precio = COALESCE(%s, precio)"
            " WHERE id = %s"
            " RETURNING id, comida_id, nombre, precio, orden",
            (nombre, precio, gusto_id),
        )
    fila = cur.fetchone()
    return dict(fila) if fila else "Ese gusto ya no existe"


@app.route("/api/admin/comidas/<int:comida_id>/gustos", methods=["POST"])
def api_crear_gusto(comida_id):
    error = pedir_clave()
    if error:
        return error
    datos = cuerpo_del_dueno()
    datos["comida_id"] = comida_id

    def trabajo(cur):
        cur.execute("SELECT id FROM comidas WHERE id = %s", (comida_id,))
        if cur.fetchone() is None:
            return "Esa comida ya no existe"
        resultado = _gusto_desde(cur, datos)
        if isinstance(resultado, str):
            return resultado
        # En cuanto tiene un gusto, la comida pasa sola a "con gusto para
        # elegir". Antes esto lo mandaba el editor del dueno en cada guardado,
        # pero si el gusto se agrega por otro lado (o si el guardado se corta a
        # la mitad) la comida quedaba con gustos y sin la marca, y los clientes
        # veian un solo precio en vez de la lista para elegir.
        cur.execute(
            "UPDATE comidas SET tipo = 'gustos' WHERE id = %s AND tipo <> 'gustos'",
            (comida_id,),
        )
        return resultado

    resultado = recorrer_base(trabajo)
    if resultado is None:
        return sin_base()
    if isinstance(resultado, str):
        return jsonify({"error": resultado}), 400
    olvidar_menu()
    return jsonify(resultado), 201


@app.route("/api/admin/gustos/<int:gusto_id>", methods=["PUT"])
def api_editar_gusto(gusto_id):
    error = pedir_clave()
    if error:
        return error
    datos = cuerpo_del_dueno()

    def trabajo(cur):
        return _gusto_desde(cur, datos, gusto_id)

    resultado = recorrer_base(trabajo)
    if resultado is None:
        return sin_base()
    if isinstance(resultado, str):
        return jsonify({"error": resultado}), 400
    olvidar_menu()
    return jsonify(resultado)


@app.route("/api/admin/gustos/<int:gusto_id>", methods=["DELETE"])
def api_borrar_gusto(gusto_id):
    error = pedir_clave()
    if error:
        return error

    def trabajo(cur):
        cur.execute("DELETE FROM gustos WHERE id = %s RETURNING id", (gusto_id,))
        return cur.fetchone() is not None

    borrado = recorrer_base(trabajo)
    if borrado is None:
        return sin_base()
    if not borrado:
        return jsonify({"error": "Ese gusto ya no existe"}), 404
    olvidar_menu()
    return jsonify({"ok": True})


@app.route("/api/admin/comidas/reordenar", methods=["POST"])
def api_reordenar_comidas():
    """Manda el orden completo de las comidas de una categoria, de arriba abajo.

    El editor manda la lista de ids en el orden que quiere y la base se queda
    con ese. Es una sola consulta en vez de una por comida movida.
    """
    error = pedir_clave()
    if error:
        return error
    ids = lista_de_ids()
    if ids is None:
        return jsonify({"error": "La lista de comidas no es correcta"}), 400

    movidas = guardar_orden("comidas", ids)
    if movidas is None:
        return sin_base()
    olvidar_menu()
    return jsonify({"ok": True, "movidas": movidas})


# --- las fotos ---

# La base gratis da 0,5 GB. Achicar y convertir a WebP deja cada foto en
# 100-200 KB en vez de los 2-3 MB que pesan ahora las del repo, asi entran
# cientos de fotos sin acercarse al limite.
ANCHO_MAXIMO_FOTO = 900
CALIDAD_WEBP = 80

MIMES_PERMITIDOS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def achicar_foto(datos, mime):
    """Convierte la foto a WebP y la achica. Devuelve (bytes, mime, nombre).

    Si Pillow no esta instalado se guarda la foto como vino: peor, pero anda.
    """
    try:
        import io

        from PIL import Image, ImageOps
    except ImportError:
        # Se sube la foto como vino. Funciona igual, solo que pesa mas.
        return datos, mime, "foto" + MIMES_PERMITIDOS.get(mime, ".bin")

    with Image.open(io.BytesIO(datos)) as imagen:
        # Many phones save the rotation in EXIF instead of rotating the pixels;
        # without this the photos come out sideways.
        imagen = ImageOps.exif_transpose(imagen)
        if imagen.mode not in ("RGB", "RGBA"):
            imagen = imagen.convert("RGBA" if "A" in imagen.getbands() else "RGB")
        # thumbnail only shrinks, it never enlarges, so a small photo is not blurred
        imagen.thumbnail((ANCHO_MAXIMO_FOTO, ANCHO_MAXIMO_FOTO), Image.LANCZOS)
        salida = io.BytesIO()
        imagen.save(salida, format="WEBP", quality=CALIDAD_WEBP, method=4)
    return salida.getvalue(), "image/webp", "foto.webp"


@app.route("/api/admin/imagenes", methods=["POST"])
def api_subir_imagen():
    """Sube una foto y devuelve el id con el que hay que guardarla en la comida."""
    error = pedir_clave()
    if error:
        return error

    archivo = request.files.get("archivo") or request.files.get("foto")
    if archivo is None or not archivo.filename:
        return jsonify({"error": "No se eligio ninguna foto"}), 400

    # secure_filename: el nombre lo manda el navegador y va a terminar en una
    # cabecera HTTP, asi que no puede quedar con saltos ni con comillas.
    from werkzeug.utils import secure_filename

    nombre = secure_filename(archivo.filename) or "foto"
    if len(nombre) > 80:
        nombre = nombre[:80]

    datos = archivo.read()
    if not datos:
        return jsonify({"error": "La foto vino vacia"}), 400

    mime = (archivo.mimetype or "").lower()
    if mime and mime not in MIMES_PERMITIDOS:
        return jsonify({"error": "Solo se aceptan fotos JPG, PNG, WEBP o GIF"}), 400

    try:
        contenido, mime_final, nombre_final = achicar_foto(datos, mime)
    except Exception:
        # Un archivo que no es una foto (o una foto rota) hacia saltar un error
        # 500 sin explicacion.
        return jsonify({"error": "Ese archivo no es una foto que se pueda abrir"}), 400
    if len(contenido) > 4 * 1024 * 1024:
        return jsonify({"error": "La foto sigue siendo muy grande. Probá con otra."}), 400

    def trabajo(cur):
        cur.execute(
            "INSERT INTO imagenes (nombre, mime, contenido) VALUES (%s, %s, %s)"
            " RETURNING id, nombre, mime",
            (nombre_final, mime_final, contenido),
        )
        fila = dict(cur.fetchone())
        fila["bytes"] = len(contenido)
        return fila

    nueva = recorrer_base(trabajo)
    if nueva is None:
        return sin_base()
    nueva["url"] = f"/api/imagenes/{nueva['id']}"
    # La foto es nueva, asi que no hay nada que invalidar del menu: el dueno
    # todavia no la asigno a ninguna comida.
    return jsonify(nueva), 201


@app.route("/api/admin/imagenes/<int:img_id>", methods=["DELETE"])
def api_borrar_imagen(img_id):
    """Saca una foto que ya no usa ninguna comida.

    Las comidas que la tenian quedan con la foto vacia (ON DELETE SET NULL), no
    se borran.
    """
    error = pedir_clave()
    if error:
        return error

    def trabajo(cur):
        cur.execute("SELECT nombre FROM imagenes WHERE id = %s", (img_id,))
        fila = cur.fetchone()
        if not fila:
            # Se devuelve una tupla, no un texto suelto: antes se devolvia el
            # nombre, y como el nombre tambien es un texto, el que no encontraba
            # la foto y el que si la borraba quedaban indistinguibles. El
            # dueño nunca pudo borrar una foto y le salia un 404 con el nombre
            # del archivo en vez de un mensaje.
            return False, None
        cur.execute("DELETE FROM imagenes WHERE id = %s", (img_id,))
        return True, fila["nombre"]

    resultado = recorrer_base(trabajo)
    if resultado is None:
        return sin_base()
    borrada, nombre = resultado
    if not borrada:
        return jsonify({"error": "Esa foto ya no existe"}), 404
    with _cache_lock:
        _cache_fotos.pop(img_id, None)
    olvidar_menu()
    return jsonify({"ok": True, "nombre": nombre})



# ---------------------------------------------------------------------------
# ESTADO DEL LOCAL
#
# El dueno abre o cierra el local con un boton del panel. Se guarda en Neon,
# asi que vale para todos: si el local esta cerrado, la web no acepta pedidos.
# Antes esto dependia de que la PC del local estuviera prendida mandando
# "latidos"; ahora no hace falta ninguna PC prendida.
# ---------------------------------------------------------------------------


# Si el local esta abierto se guarda tambien en memoria, asi cada pedido de un
# cliente no tiene que ir a preguntarlo a Neon (un viaje a San Pablo menos por
# pedido). El boton del panel lo cambia en memoria al instante; los 30
# segundos son por si alguna vez hay mas de un proceso en Render.
SEGUNDOS_CACHE_ESTADO = 30
_cache_estado = {"abierto": None, "vence": 0.0}


def local_abierto(usar_cache=True):
    """True/False si el local acepta pedidos, o None si la base no contesta.

    Sin nada guardado, esta abierto. None no es "cerrado": el panel lo usa para
    mostrar "sin datos" (y dejar abrir el local igual), y un pedido con None se
    intenta guardar, porque si la base no anda el error real llega al guardar.
    """
    with _cache_lock:
        if usar_cache and time.time() < _cache_estado["vence"]:
            return _cache_estado["abierto"]

    def trabajo(cur):
        cur.execute("SELECT valor FROM ajustes WHERE clave = 'local_abierto'")
        fila = cur.fetchone()
        # Se envuelve en una lista: recorrer_base usa None para "la base no anduvo".
        return [fila["valor"] if fila else None]

    resultado = recorrer_base(trabajo, transaccion=False)
    if resultado is None:
        # Si la base no contesta se usa lo ultimo que se supo (si se supo algo).
        with _cache_lock:
            return _cache_estado["abierto"]
    abierto = resultado[0] != "no"
    recordar_estado_local(abierto)
    return abierto


def recordar_estado_local(abierto):
    with _cache_lock:
        _cache_estado["abierto"] = abierto
        _cache_estado["vence"] = time.time() + SEGUNDOS_CACHE_ESTADO


@app.route("/api/local/estado", methods=["GET", "POST"])
def estado_local():
    """GET: si el local esta abierto (publico). POST: el dueno lo abre o cierra."""
    if request.method == "POST":
        error = pedir_clave()
        if error:
            return error
        abierto = bool(cuerpo_del_dueno().get("abierto"))

        def trabajo(cur):
            cur.execute(
                "INSERT INTO ajustes (clave, valor) VALUES ('local_abierto', %s)"
                " ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
                ("si" if abierto else "no",),
            )
            return True

        if recorrer_base(trabajo, transaccion=False) is None:
            return sin_base()
        recordar_estado_local(abierto)
        return jsonify({"abierto": abierto})

    # ?despertar=1 lo manda la pagina del cliente cuando abre el formulario del
    # pedido: va a Neon de verdad, asi la base y la conexion ya estan
    # despiertas cuando el cliente toca "Confirmar" (si Neon estaba dormido,
    # despertarlo tarda un par de segundos y antes los esperaba el cliente).
    despertar = request.args.get("despertar") == "1"
    return jsonify({"abierto": local_abierto(usar_cache=not despertar)})


@app.route("/api/salud")
def salud():
    """Para ver que el sitio esta vivo, sin tocar la base de datos.

    "varios_a_la_vez" dice si gunicorn tomo la configuracion con hilos: si da
    false, atiende de a un pedido por vez y todo se pone en fila. Tambien sirve
    para que un servicio como UptimeRobot visite el sitio y Render no se duerma.
    """
    respuesta = {"ok": True, "varios_a_la_vez": bool(request.environ.get("wsgi.multithread"))}
    if request.args.get("base") == "1":
        respuesta["base"] = probar_base()
    return jsonify(respuesta)


# /api/salud?base=1 prueba la conexion a Neon y dice por que falla. Sirve para
# saber que pasa sin entrar a los logs de Render. Nunca muestra la clave ni el
# nombre del servidor de la base; como mucho una prueba cada 20 segundos.
_ultima_prueba = {"momento": 0.0, "resultado": None}


def probar_base():
    ahora = time.time()
    if ahora - _ultima_prueba["momento"] < 20 and _ultima_prueba["resultado"]:
        return _ultima_prueba["resultado"]
    region = next((parte for parte in DATABASE_URL.split(".")
                   if parte.count("-") == 2 and parte[-1:].isdigit()), "?")
    resultado = {"region": region, "hay_url": bool(DATABASE_URL)}
    if not DATABASE_URL or psycopg is None:
        resultado["estado"] = "sin URL" if not DATABASE_URL else "falta psycopg"
    else:
        inicio = time.time()
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=8, prepare_threshold=None) as conn:
                conn.execute("SELECT 1")
            resultado["estado"] = "ok"
        except Exception as error:
            mensaje = str(error).replace(DATABASE_URL, "<url>")
            mensaje = re.sub(r"ep-[a-z0-9-]+", "<servidor>", mensaje)
            mensaje = re.sub(r"\d+\.\d+\.\d+\.\d+", "<ip>", mensaje)
            resultado["estado"] = f"{type(error).__name__}: {mensaje[:200]}"
        resultado["segundos"] = round(time.time() - inicio, 2)
    # Como esta el pool que usan los pedidos (puede andar la conexion directa
    # y estar trabado el pool, como paso una vez).
    if _pool is not None:
        try:
            stats = _pool.get_stats()
            resultado["pool"] = {clave: stats.get(clave, 0) for clave in (
                "pool_size", "pool_available", "requests_waiting",
                "connections_errors", "requests_errors", "connections_lost")}
        except Exception:
            pass
    resultado["pool_reiniciado"] = _reinicios_pool["cantidad"]
    resultado["base_caida_por"] = max(0, round(_base_caida["hasta"] - time.time()))
    _ultima_prueba.update(momento=ahora, resultado=resultado)
    return resultado


@app.route("/api/panel/estado")
def estado_panel():
    """Solo para comprobar la clave. Si esta mal, responde 401."""
    error = pedir_clave()
    if error:
        return error
    return jsonify({"ok": True, "con_clave": bool(CLAVE_PANEL_LIMPIA)})


# ---------------------------------------------------------------------------
# PEDIDOS
#
# Viven en Neon, en la tabla pedidos. "Sacar de la pantalla" no los borra: los
# marca como ocultos, asi el panel queda limpio y el registro de pedidos
# (archivo.html) los sigue mostrando todos.
# ---------------------------------------------------------------------------

# La fecha sale en el mismo formato que usaba SQLite (UTC, "AAAA-MM-DD HH:MM:SS"),
# que es el que entienden el panel y el registro.
# El codigo de seguimiento y la suscripcion no salen nunca: el panel solo
# necesita saber si el cliente tiene los avisos activados.
COLUMNAS_PEDIDO = (
    "id, items, total, estado, envio, cliente, oculto, (avisos IS NOT NULL) AS con_avisos,"
    " to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS created_at"
)
MAXIMO_PLATOS_POR_PEDIDO = 100


def numero_o(valor, por_defecto):
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return por_defecto


def platos_del_pedido(items):
    """Deja solo los datos que el panel usa, con tipos correctos.

    Antes se guardaba lo que mandara el navegador tal cual: un precio escrito
    como texto rompia la suma con un error 500.
    """
    platos = []
    for item in items[:MAXIMO_PLATOS_POR_PEDIDO]:
        if not isinstance(item, dict):
            continue
        nombre = texto_limpio(item.get("name"), 160)
        if not nombre:
            continue
        platos.append({
            "name": nombre,
            "price": max(numero_o(item.get("price"), 0), 0),
            "quantity": min(max(numero_o(item.get("quantity"), 1), 1), 999),
            "image": texto_limpio(item.get("image"), 300),
        })
    return platos


# --- los precios los pone el servidor, no el navegador ---
#
# Antes se guardaba el precio que mandaba la pagina: alguien que supiera un
# poco podia pedir una pizza a $1, y un carrito armado con el menu viejo (o con
# el menu de respaldo del HTML) se cobraba con precios viejos. Ahora cada plato
# se busca en el menu de la base y se cobra lo que dice el editor.


def _clave_de_nombre(texto):
    """Para comparar nombres sin que importen mayusculas, tildes ni espacios."""
    texto = unicodedata.normalize("NFD", str(texto or "").lower())
    texto = "".join(letra for letra in texto if unicodedata.category(letra) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def nombre_con_gusto(comida, gusto):
    """El mismo nombre que arma la pagina (platos-menu.js, nombreConGusto):
    "Empanadas de carne, pollo..." + "Carne" -> "Empanada de carne"."""
    sabor = re.sub(r"^de\s+", "", str(gusto.get("nombre") or "").strip(), flags=re.I)
    nombre = str(comida.get("nombre") or "").strip()
    minuscula = nombre.lower()
    corte = -1
    for otro in comida.get("gustos") or []:
        palabra = re.sub(r"^de\s+", "", str(otro.get("nombre") or "").strip(), flags=re.I).lower()
        donde = minuscula.find(palabra) if palabra else -1
        if donde > 0 and (corte == -1 or donde < corte):
            corte = donde
    if corte == -1:
        return f"{nombre} ({sabor})"
    base = re.sub(r"\s+de\s*$", "", nombre[:corte], flags=re.I).rstrip(" ,")
    if re.fullmatch(r"\S+s", base, flags=re.I):
        base = base[:-1]
    return f"{base} de {sabor[:1].lower()}{sabor[1:]}"


def precios_del_menu():
    """{nombre: precio} de todo lo que hoy se puede pedir, o None sin base."""
    categorias, de_la_base = obtener_menu(solo_activas=True)
    if not de_la_base:
        return None
    precios = {}
    for categoria in categorias:
        for comida in categoria.get("comidas") or []:
            gustos = comida.get("gustos") or []
            if comida.get("tipo") == "gustos" and gustos:
                for gusto in gustos:
                    precios[_clave_de_nombre(nombre_con_gusto(comida, gusto))] = int(gusto.get("precio") or 0)
            else:
                precios[_clave_de_nombre(comida.get("nombre"))] = int(comida.get("precio") or 0)
    return precios


def lista_de_pedidos(cur, condicion=""):
    cur.execute(f"SELECT {COLUMNAS_PEDIDO} FROM pedidos {condicion} ORDER BY id DESC")
    return [dict(fila) for fila in cur.fetchall()]


@app.route("/api/orders", methods=["GET", "POST", "DELETE"])
def orders():
    # El POST es el que usan los clientes para pedir, va sin clave. Todo lo demas
    # (mirar pedidos, sacarlos de la pantalla) es del dueno.
    if request.method != "POST":
        error = pedir_clave()
        if error:
            return error

    if request.method == "DELETE":
        # "hasta": el panel manda el ultimo pedido que tiene en pantalla, asi
        # uno que entro recien no se saca sin que nadie lo haya visto.
        hasta = id_o_nada(request.args.get("hasta"))

        def trabajo(cur):
            if hasta is None:
                cur.execute("UPDATE pedidos SET oculto = TRUE WHERE NOT oculto")
            else:
                cur.execute(
                    "UPDATE pedidos SET oculto = TRUE WHERE NOT oculto AND id <= %s", (hasta,)
                )
            return cur.rowcount

        sacados = recorrer_base(trabajo, transaccion=False)
        if sacados is None:
            return sin_base()
        return jsonify({"ok": True, "eliminados": sacados})

    if request.method == "GET":
        pedidos = recorrer_base(
            lambda cur: lista_de_pedidos(cur, "WHERE NOT oculto"), transaccion=False
        )
        if pedidos is None:
            return sin_base()
        return jsonify(pedidos)

    data = request.get_json(silent=True) or {}

    # Si el local esta cerrado el pedido no se guarda: no hay nadie para
    # prepararlo, asi que es mejor avisarle al cliente antes de que pague.
    if local_abierto() is False:
        return jsonify({
            "error": "El local esta cerrado ahora mismo. No se pudo enviar el pedido.",
            "codigo": "local_cerrado",
        }), 503

    # Contra pedidos falsos en cantidad:
    # 1. "sitio_web" es un campo escondido del formulario: una persona no lo ve
    #    y lo deja vacio, pero los programas que llenan formularios solos lo
    #    completan. Si viene lleno, se hace como que salio bien y no se guarda.
    if str(data.get("sitio_web") or "").strip():
        return jsonify({"ok": True, "order_id": 0, "total": 0})
    # 2. Como mucho 2 pedidos cada 10 minutos desde la misma conexion (el
    #    segundo, por si alguien se olvido de agregar algo).
    if not dentro_del_limite("pedido", ip_del_cliente(), 2, 600):
        return jsonify({
            "error": "Hiciste muchos pedidos seguidos. Esperá unos minutos y volvé a intentar.",
            "codigo": "demasiados",
        }), 429

    items = data.get("items", [])
    platos = platos_del_pedido(items) if isinstance(items, list) else []
    if not platos:
        return jsonify({"error": "Se requiere al menos un plato"}), 400

    # Cada plato se cobra con el precio del menu de la base.
    precios = precios_del_menu()
    if precios is None:
        return jsonify({"error": "No se pudo leer el menú. Intentá de nuevo en unos segundos."}), 503
    faltan = [plato["name"] for plato in platos if _clave_de_nombre(plato["name"]) not in precios]
    if faltan:
        # Un carrito viejo, o un plato que el local saco del menu.
        return jsonify({
            "error": "Algunos productos ya no están en el menú: " + ", ".join(faltan[:3]) +
                     ". Actualizá la página y armá el pedido de nuevo.",
            "codigo": "menu_cambio",
            "faltan": faltan,
        }), 409
    for plato in platos:
        plato["price"] = precios[_clave_de_nombre(plato["name"])]

    envio = data.get("envio", "local")
    if envio not in ("domicilio", "local"):
        return jsonify({"error": "Tipo de envío inválido"}), 400

    cliente = data.get("cliente", {})
    if not isinstance(cliente, dict):
        return jsonify({"error": "Datos del cliente inválidos"}), 400
    cliente = {
        campo: texto_limpio(cliente.get(campo), 120)
        for campo in ("nombre", "apellido", "telefono", "calle", "numero", "entre", "direccion")
        if cliente.get(campo)
    }

    total = sum(plato["price"] * plato["quantity"] for plato in platos)

    # El telefono "limpio" (solo digitos, sin +54 ni 0 ni 9) sirve para
    # reconocer al cliente aunque lo escriba distinto cada vez. Con eso el panel
    # muestra si ya pidio antes y arma el link de WhatsApp.
    telefono = telefono_normalizado(cliente.get("telefono"))
    if len(telefono) >= 6:
        cliente["telefono_normalizado"] = telefono
        # 3. Y como mucho 2 cada 10 minutos con el mismo telefono, aunque
        #    cambie de conexion.
        if not dentro_del_limite("pedido_tel", telefono, 2, 600):
            return jsonify({
                "error": "Hiciste muchos pedidos seguidos. Esperá unos minutos y volvé a intentar.",
                "codigo": "demasiados",
            }), 429

    # El codigo con el que el navegador del cliente sigue su pedido.
    seguimiento = secrets.token_urlsafe(16)

    def trabajo(cur):
        # En la misma consulta se cuenta cuantos pedidos hizo antes ese mismo
        # telefono, asi no es un viaje mas a la base.
        cur.execute(
            "INSERT INTO pedidos (items, total, envio, seguimiento, cliente)"
            " VALUES (%s::jsonb, %s, %s, %s, jsonb_set(%s::jsonb, '{pedidos_anteriores}',"
            "   to_jsonb((SELECT count(*) FROM pedidos"
            "              WHERE %s <> '' AND cliente->>'telefono_normalizado' = %s))))"
            " RETURNING id",
            (json.dumps(platos, ensure_ascii=False), total, envio, seguimiento,
             json.dumps(cliente, ensure_ascii=False),
             cliente.get("telefono_normalizado", ""), cliente.get("telefono_normalizado", "")),
        )
        return cur.fetchone()["id"]

    order_id = recorrer_base(trabajo, transaccion=False)
    if order_id is None:
        return jsonify({"error": "No se pudo guardar el pedido. Intentá de nuevo."}), 503

    # Se recuerda quién es el cliente, para que el panel sepa si ya había pedido
    # antes. Va en otro hilo y nunca puede hacer fallar el pedido, que ya quedó
    # guardado.
    threading.Thread(target=recordar_cliente, args=(cliente,), daemon=True).start()

    return jsonify({"ok": True, "order_id": order_id, "total": total,
                    "envio": envio, "seguimiento": seguimiento})


@app.route("/api/orders/<int:order_id>/estado", methods=["POST"])
def update_estado(order_id):
    error = pedir_clave()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    estado = data.get("estado")
    # "entregado" es el ultimo paso: el pedido llego a domicilio o lo retiraron.
    if estado not in ("nuevo", "recibido", "listo", "entregado"):
        return jsonify({"error": "Estado inválido"}), 400

    def trabajo(cur):
        cur.execute("SELECT estado FROM pedidos WHERE id = %s", (order_id,))
        actual = cur.fetchone()
        if actual and actual["estado"] == "cancelado":
            return -1  # el cliente lo cancelo: ya no se mueve
        # La hora de cada paso se guarda la primera vez que pasa (si se toca
        # "Listo" sin "Recibir", cuenta como recibido en ese momento). Si se
        # vuelve a "nuevo", se borran.
        cur.execute(
            "UPDATE pedidos SET estado = %s,"
            " recibido_at = CASE WHEN %s IN ('recibido', 'listo', 'entregado')"
            "   THEN COALESCE(recibido_at, now()) END,"
            " listo_at = CASE WHEN %s IN ('listo', 'entregado') THEN COALESCE(listo_at, now()) END,"
            " entregado_at = CASE WHEN %s = 'entregado' THEN COALESCE(entregado_at, now()) END"
            " WHERE id = %s",
            (estado, estado, estado, estado, order_id),
        )
        return cur.rowcount

    cambiados = recorrer_base(trabajo, transaccion=False)
    if cambiados is None:
        return sin_base()
    if cambiados == 0:
        return jsonify({"error": "Pedido no encontrado"}), 404
    if cambiados == -1:
        return jsonify({"error": "El cliente canceló este pedido.", "codigo": "cancelado"}), 409
    if estado in ("recibido", "listo"):
        # La notificacion al celular del cliente va en otro hilo: el panel no
        # tiene que esperar a que la mande.
        threading.Thread(target=avisar_al_cliente, args=(order_id, estado), daemon=True).start()
    return jsonify({"ok": True, "order_id": order_id, "estado": estado})


# ---------------------------------------------------------------------------
# SEGUIMIENTO DEL PEDIDO Y AVISOS AL CLIENTE
#
# Cuando el dueno toca "Recibir" o "Listo" en el panel, al cliente le llega el
# aviso de dos formas:
#   1. La pagina donde pidio pregunta el estado cada pocos segundos
#      (/api/seguimiento) y lo muestra en una tarjetita. Anda en cualquier
#      celular mientras la pagina este abierta.
#   2. Si el cliente acepto "avisarme aunque cierre la pagina", le llega una
#      notificacion del celular (Web Push), como las de cualquier app.
#
# Para las notificaciones hacen falta dos claves (VAPID). Se crean solas la
# primera vez y se guardan en la base, asi no hay que configurar nada en Render.
# ---------------------------------------------------------------------------

try:
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush
except Exception:
    webpush = None

# Lo que dice el aviso en cada estado. La pagina del cliente (seguimiento.js)
# muestra los mismos textos.
TEXTOS_AVISO = {
    "recibido": ("🍽️ ¡Recibimos tu pedido!", "Pedido #{id}: ya lo estamos preparando."),
    "listo_local": ("✅ ¡Tu pedido está listo!", "Pedido #{id}: ya podés pasar a retirarlo por el local."),
    "listo_domicilio": ("🛵 ¡Tu pedido va en camino!",
                        "Pedido #{id}: está listo y lo estamos llevando a tu domicilio."),
}

_claves_vapid = {"privada": None, "publica": None}


def claves_vapid():
    """Devuelve (Vapid02, clave_publica) o (None, None). Las crea si no existen."""
    if webpush is None:
        return None, None
    if _claves_vapid["privada"] is not None:
        return _claves_vapid["privada"], _claves_vapid["publica"]

    nueva = Vapid02()
    nueva.generate_keys()
    pem_nueva = nueva.private_pem().decode()

    def trabajo(cur):
        # Si ya habia una guardada, gana esa: las suscripciones de los
        # clientes quedan atadas a la clave con la que se hicieron.
        cur.execute(
            "INSERT INTO ajustes (clave, valor) VALUES ('vapid_privada', %s)"
            " ON CONFLICT (clave) DO NOTHING",
            (pem_nueva,),
        )
        cur.execute("SELECT valor FROM ajustes WHERE clave = 'vapid_privada'")
        return cur.fetchone()["valor"]

    pem = recorrer_base(trabajo)
    if not pem:
        return None, None
    privada = Vapid02.from_pem(pem.encode())
    import base64

    from cryptography.hazmat.primitives import serialization

    crudo = privada.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    publica = base64.urlsafe_b64encode(crudo).decode().rstrip("=")
    _claves_vapid.update(privada=privada, publica=publica)
    return privada, publica


def avisar_al_cliente(order_id, estado):
    """Manda la notificacion al celular del cliente, si la pidio. Nunca falla."""
    try:
        privada, _ = claves_vapid()
        if privada is None:
            return

        def leer(cur):
            cur.execute("SELECT avisos, envio FROM pedidos WHERE id = %s", (order_id,))
            return cur.fetchone()

        fila = recorrer_base(leer, transaccion=False)
        if not fila or not fila["avisos"]:
            return
        clave = estado if estado == "recibido" else f"listo_{fila['envio']}"
        titulo, cuerpo = TEXTOS_AVISO.get(clave, TEXTOS_AVISO["listo_local"])
        datos = json.dumps({
            "titulo": titulo,
            "cuerpo": cuerpo.format(id=order_id),
            "etiqueta": f"pedido-{order_id}",
        }, ensure_ascii=False)
        try:
            webpush(
                subscription_info=fila["avisos"],
                data=datos,
                vapid_private_key=privada,
                vapid_claims={"sub": "https://modohambre.onrender.com"},
                timeout=10,
                ttl=60 * 60,
            )
        except WebPushException as error:
            # 404/410: el cliente desactivo los avisos o borro el navegador.
            # Se olvida la suscripcion para no seguir intentando.
            codigo = getattr(getattr(error, "response", None), "status_code", None)
            if codigo in (404, 410):
                recorrer_base(
                    lambda cur: cur.execute(
                        "UPDATE pedidos SET avisos = NULL WHERE id = %s", (order_id,)
                    ),
                    transaccion=False,
                )
            else:
                print(f"No se pudo avisar al cliente del pedido #{order_id}: {error}", flush=True)
    except Exception as error:
        print(f"No se pudo avisar al cliente del pedido #{order_id}: {error}", flush=True)


@app.route("/api/seguimiento/<int:order_id>")
def seguimiento_pedido(order_id):
    """El estado de un pedido, para el cliente que lo hizo (con su codigo)."""
    codigo = request.args.get("t", "")
    if not codigo:
        return jsonify({"error": "Falta el codigo"}), 400

    def trabajo(cur):
        cur.execute(
            "SELECT id, estado, envio, total, items,"
            " cliente->>'calle' AS calle, cliente->>'numero' AS numero, cliente->>'entre' AS entre,"
            # en segundos desde 1970: el navegador lo pasa a la hora del celular
            " extract(epoch FROM created_at)::bigint AS enviado,"
            " extract(epoch FROM recibido_at)::bigint AS recibido,"
            " extract(epoch FROM listo_at)::bigint AS listo,"
            " extract(epoch FROM entregado_at)::bigint AS entregado,"
            " extract(epoch FROM cancelado_at)::bigint AS cancelado"
            " FROM pedidos WHERE id = %s AND seguimiento = %s",
            (order_id, codigo),
        )
        return [cur.fetchone()]

    resultado = recorrer_base(trabajo, transaccion=False)
    if resultado is None:
        return sin_base()
    if resultado[0] is None:
        return jsonify({"error": "Pedido no encontrado"}), 404
    pedido = dict(resultado[0])
    pedido["items"] = [
        {"name": item.get("name"), "quantity": item.get("quantity"), "price": item.get("price")}
        for item in (pedido.get("items") or [])
    ]
    return jsonify(pedido)


@app.route("/api/seguimiento/<int:order_id>/cancelar", methods=["POST"])
def cancelar_pedido(order_id):
    """El cliente cancela su pedido (con su codigo de seguimiento).

    Solo mientras el local no lo recibio: despues ya se esta preparando, y
    el cliente tiene que hablar con el local.
    """
    codigo = str((request.get_json(silent=True) or {}).get("t") or "")
    if not codigo:
        return jsonify({"error": "Falta el codigo"}), 400

    def trabajo(cur):
        cur.execute(
            "UPDATE pedidos SET estado = 'cancelado', cancelado_at = now()"
            " WHERE id = %s AND seguimiento = %s AND estado = 'nuevo' RETURNING id",
            (order_id, codigo),
        )
        if cur.fetchone():
            return "ok"
        cur.execute("SELECT estado FROM pedidos WHERE id = %s AND seguimiento = %s", (order_id, codigo))
        fila = cur.fetchone()
        return fila["estado"] if fila else "no_existe"

    resultado = recorrer_base(trabajo, transaccion=False)
    if resultado is None:
        return sin_base()
    if resultado == "ok" or resultado == "cancelado":
        return jsonify({"ok": True, "estado": "cancelado"})
    if resultado == "no_existe":
        return jsonify({"error": "Pedido no encontrado"}), 404
    return jsonify({
        "error": "El local ya recibió tu pedido y lo está preparando. Si necesitás cancelarlo, escribinos por WhatsApp.",
        "codigo": "ya_recibido",
        "estado": resultado,
    }), 409


@app.route("/api/avisos/clave")
def clave_de_avisos():
    """La clave publica que el navegador necesita para suscribirse."""
    _, publica = claves_vapid()
    if not publica:
        return jsonify({"error": "Los avisos no estan disponibles"}), 503
    return jsonify({"clave": publica})


@app.route("/api/seguimiento/<int:order_id>/avisos", methods=["POST"])
def activar_avisos(order_id):
    """Guarda la suscripcion del navegador del cliente para ese pedido."""
    datos = cuerpo_del_dueno()
    codigo = str(datos.get("t") or "")
    suscripcion = datos.get("suscripcion")
    valida = (
        isinstance(suscripcion, dict)
        and str(suscripcion.get("endpoint", "")).startswith("https://")
        and isinstance(suscripcion.get("keys"), dict)
        and suscripcion["keys"].get("p256dh")
        and suscripcion["keys"].get("auth")
        and len(json.dumps(suscripcion)) < 2000
    )
    if not codigo or not valida:
        return jsonify({"error": "Datos de aviso invalidos"}), 400
    limpia = {
        "endpoint": suscripcion["endpoint"],
        "keys": {"p256dh": suscripcion["keys"]["p256dh"], "auth": suscripcion["keys"]["auth"]},
    }

    def trabajo(cur):
        cur.execute(
            "UPDATE pedidos SET avisos = %s::jsonb WHERE id = %s AND seguimiento = %s",
            (json.dumps(limpia), order_id, codigo),
        )
        return cur.rowcount

    cambiados = recorrer_base(trabajo, transaccion=False)
    if cambiados is None:
        return sin_base()
    if cambiados == 0:
        return jsonify({"error": "Pedido no encontrado"}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# COMENTARIOS DEL FORMULARIO DE CONTACTO
#
# Antes el formulario decia "comentario enviado" pero no mandaba nada a ningun
# lado. Ahora se guardan en la base y el dueno los ve abajo de todo en el panel.
# ---------------------------------------------------------------------------

ASUNTOS_VALIDOS = ("consulta", "sugerencia", "felicitacion", "otro")


@app.route("/api/comentarios", methods=["GET", "POST"])
def comentarios():
    if request.method == "GET":
        error = pedir_clave()
        if error:
            return error

        def leer(cur):
            cur.execute(
                "SELECT id, nombre, email, telefono, asunto, mensaje, leido,"
                " to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS created_at"
                " FROM comentarios ORDER BY id DESC LIMIT 50"
            )
            return [dict(fila) for fila in cur.fetchall()]

        lista = recorrer_base(leer, transaccion=False)
        if lista is None:
            return sin_base()
        return jsonify(lista)

    datos = request.get_json(silent=True) or {}
    if str(datos.get("sitio_web") or "").strip():
        return jsonify({"ok": True})  # el campo trampa vino lleno: un programa
    # Como mucho 3 comentarios cada 10 minutos desde la misma conexion.
    if not dentro_del_limite("comentario", ip_del_cliente(), 3, 600):
        return jsonify({"error": "Mandaste varios comentarios seguidos. Esperá unos minutos."}), 429
    nombre = texto_limpio(datos.get("nombre"), 80, requerido=True)
    mensaje = str(datos.get("mensaje") or "").strip()[:500]
    if not nombre or not mensaje:
        return jsonify({"error": "Faltan el nombre o el mensaje."}), 400
    asunto = datos.get("asunto") if datos.get("asunto") in ASUNTOS_VALIDOS else None

    def guardar(cur):
        cur.execute(
            "INSERT INTO comentarios (nombre, email, telefono, asunto, mensaje)"
            " VALUES (%s, %s, %s, %s, %s)",
            (nombre, texto_limpio(datos.get("email"), 120), texto_limpio(datos.get("telefono"), 40),
             asunto, mensaje),
        )
        return True

    if recorrer_base(guardar, transaccion=False) is None:
        return jsonify({"error": "No se pudo enviar el comentario. Intentá de nuevo."}), 503
    return jsonify({"ok": True}), 201


@app.route("/api/comentarios/<int:comentario_id>", methods=["POST", "DELETE"])
def comentario(comentario_id):
    """POST: marcar como leido. DELETE: borrarlo. Solo el dueno."""
    error = pedir_clave()
    if error:
        return error

    def trabajo(cur):
        if request.method == "DELETE":
            cur.execute("DELETE FROM comentarios WHERE id = %s", (comentario_id,))
        else:
            cur.execute("UPDATE comentarios SET leido = TRUE WHERE id = %s", (comentario_id,))
        return cur.rowcount

    cambiados = recorrer_base(trabajo, transaccion=False)
    if cambiados is None:
        return sin_base()
    return jsonify({"ok": bool(cambiados)})


@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):
    """Saca el pedido de la pantalla. Sigue en el registro de pedidos."""
    error = pedir_clave()
    if error:
        return error

    def trabajo(cur):
        cur.execute("UPDATE pedidos SET oculto = TRUE WHERE id = %s", (order_id,))
        return cur.rowcount

    sacados = recorrer_base(trabajo, transaccion=False)
    if sacados is None:
        return sin_base()
    if sacados == 0:
        return jsonify({"error": "Pedido no encontrado"}), 404
    return jsonify({"ok": True, "order_id": order_id})


@app.route("/api/archivo")
def archivo_pedidos():
    """El registro completo: todos los pedidos, tambien los sacados de la pantalla."""
    error = pedir_clave()
    if error:
        return error
    pedidos = recorrer_base(lista_de_pedidos, transaccion=False)
    if pedidos is None:
        return sin_base()
    return jsonify(pedidos)


# ---------------------------------------------------------------------------
# DATOS DEL CLIENTE
#
# La llave es el teléfono: es lo único que el cliente escribe siempre y que no
# cambia entre un pedido y otro. Con eso el panel puede decir "este ya pidió
# antes" y mostrarle el nombre y la dirección sin que los vuelva a escribir.
# ---------------------------------------------------------------------------


def _sin_marcas_de_telefono(digitos):
    """Saca los prefijos que no son parte del número, en cualquier orden.

    Se repite hasta que ya no cambie porque las marcas se pueden escribir en
    cualquier orden: "+54 9 011 15-..." tiene el 54, después el 9 y después el
    0, así que con una sola pasada no alcanza.
    """
    while True:
        antes = digitos

        if digitos.startswith("00"):          # prefijo internacional
            digitos = digitos[2:]
        if digitos.startswith("54"):          # el país
            digitos = digitos[2:]
        while digitos.startswith("0"):        # el 0 del 011
            digitos = digitos[1:]

        # El 9 de los celulares ("+54 9 221 ..."): se saca si delante queda una
        # caracteristica, y en Argentina todas arrancan con 1, 2 o 3 (11, 221,
        # 351...). Antes solo se sacaba delante de un 1, y un celular de La
        # Plata escrito con +54 9 parecia otro cliente.
        if digitos.startswith("9") and len(digitos) > 6:
            resto = digitos[1:]
            while resto.startswith("0"):
                resto = resto[1:]
            if resto[:1] in ("1", "2", "3"):
                digitos = resto

        if digitos == antes:
            return digitos


def telefono_normalizado(telefono):
    """Solo los dígitos, para que el mismo teléfono se guarde una sola vez.

    La gente escribe el teléfono de todas formas posibles: con guiones, con
    espacios, con +54, con el 0 adelante, con el 9 de international. Si no se
    limpian, cada cliente que cambiaba la forma de escribirlo aparecía como uno
    nuevo y el panel decía "primera vez que pide" a gente que ya había pedido.

    Solo se sacan las partes que NO pueden ser parte del número: el 00 y el 54
    del prefijo internacional, el 0 adelante del 011, el 9 de los celulares y
    el 15 de los celulares viejos. El 15 se saca solo cuando sobra: en
    Argentina la característica más el número son siempre 10 dígitos, así que
    si quedan 12 y hay un 15 justo después de la característica, ese 15 no es
    parte del número. Sin esto el link de WhatsApp del panel no andaba.

    Todas las formas de escribir el mismo teléfono dan el mismo número:
        11 1234-5678          -> 1112345678
        +54 9 11 1234-5678    -> 1112345678
        (011) 15-1234-5678    -> 1112345678
        +54 9 221 501-2289    -> 2215012289
        (0221) 15-501-2289    -> 2215012289
    """
    digitos = _sin_marcas_de_telefono(re.sub(r"[^\d]", "", str(telefono or "")))
    if len(digitos) == 12:
        # la característica tiene 2 (11), 3 (221) o 4 (2966) dígitos
        for largo in (2, 3, 4):
            if digitos[largo:largo + 2] == "15":
                return digitos[:largo] + digitos[largo + 2:]
    return digitos


def direccion_del_cliente(cliente):
    """Junta la dirección que manda el formulario en una sola línea.

    El formulario de la web manda la dirección en tres campos separados
    (calle, numero y entre), no en uno. Si se guardara cada uno por su lado,
    el panel mostraría "calle" sin el número al lado.
    """
    if cliente.get("direccion"):
        return texto_limpio(cliente.get("direccion"), 200)

    calle = texto_limpio(cliente.get("calle"), 120)
    numero = texto_limpio(cliente.get("numero"), 20)
    entre = texto_limpio(cliente.get("entre"), 80)
    # "N°" entre la calle y el numero: con calles que son numeros (12 2932838)
    # no se entendia donde terminaba una y empezaba el otro.
    direccion = " N° ".join(parte for parte in (calle, numero) if parte)
    if entre:
        direccion += f" (entre {entre})"
    return direccion[:200]


def recordar_cliente(cliente):
    """Guarda o actualiza la ficha del cliente. Nunca tira una excepción.

    Se llama después de que el pedido ya quedó guardado, así que cualquier
    problema acá solo significa que no se guardó la ficha, no el pedido.
    """
    if not isinstance(cliente, dict):
        return
    telefono = telefono_normalizado(cliente.get("telefono"))
    if len(telefono) < 6:
        # Sin teléfono no hay forma de encontrar al cliente después. Se acepta
        # igual el pedido: el dueño lo ve en el panel del pedido.
        return

    def trabajo(cur):
        cur.execute(
            "INSERT INTO clientes (telefono, nombre, apellido, direccion)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (telefono) DO UPDATE SET"
            "   nombre = COALESCE(NULLIF(EXCLUDED.nombre, ''), clientes.nombre),"
            "   apellido = COALESCE(NULLIF(EXCLUDED.apellido, ''), clientes.apellido),"
            "   direccion = COALESCE(NULLIF(EXCLUDED.direccion, ''), clientes.direccion)",
            (
                telefono,
                texto_limpio(cliente.get("nombre"), 80),
                texto_limpio(cliente.get("apellido"), 80),
                direccion_del_cliente(cliente),
            ),
        )

    try:
        recorrer_base(trabajo, transaccion=False)
    except Exception:
        pass  # recorrer_base ya avisa por consola


@app.route("/api/admin/clientes/<telefono>")
def api_buscar_cliente(telefono):
    """La ficha de un cliente, para el panel. Solo el dueño, con clave."""
    error = pedir_clave()
    if error:
        return error
    telefono = telefono_normalizado(telefono)
    if not telefono:
        return jsonify({"error": "Falta el teléfono"}), 400

    def trabajo(cur):
        cur.execute(
            "SELECT telefono, nombre, apellido, direccion FROM clientes WHERE telefono = %s",
            (telefono,),
        )
        # Se envuelve en una lista porque recorrer_base usa None para "la base
        # no anduvo": un cliente que no existe daba error 503 en vez de
        # "primera vez que pide".
        return [cur.fetchone()]

    resultado = recorrer_base(trabajo)
    if resultado is None:
        return jsonify({"error": "Base de datos no disponible"}), 503
    ficha = resultado[0]
    # No encontrado no es un error: el panel simplemente dice que es la primera
    # vez que ese cliente pide.
    return jsonify({"cliente": dict(ficha) if ficha else None})


# En Render la pagina la levanta gunicorn ("gunicorn app:app"). Esto es solo para
# probar en una computadora: "python app.py" y se abre en http://localhost:5000.
if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", "5000"))
    # Sin PORT (o sea, en una PC) se escucha solo en esta maquina: asi nadie del
    # mismo wifi entra al panel si no hay clave puesta.
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    print(f"Modo Hambre en http://localhost:{puerto}  (panel: /admin.html)", flush=True)
    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=puerto)
    else:
        serve(app, host=host, port=puerto, threads=8)
