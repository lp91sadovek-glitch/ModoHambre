import atexit
import json
import os
import re
import secrets
import threading
import time
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
    from psycopg_pool import ConnectionPool
except Exception:
    ConnectionPool = None

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


def pedir_clave():
    """Devuelve la respuesta de error, o None si el pedido puede seguir."""
    if panel_permitido():
        return None
    return jsonify({"error": "Falta la clave del panel", "codigo": "sin_clave"}), 401


# Flask sirve la carpeta entera como archivos de la pagina (static_folder="."),
# asi que sin este filtro cualquiera podia bajarse el codigo o los archivos de
# texto con las claves, sin clave. Solo salen los tipos de archivo que una
# pagina web necesita.
EXTENSIONES_PUBLICAS = {
    ".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
    ".ico", ".mp4", ".webm", ".woff", ".woff2", ".ttf",
}


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
                timeout=10,
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


def recorrer_base(funcion, por_defecto=None, transaccion=True):
    """Toma una conexion, hace el trabajo, y la devuelve pase lo que pase.

    Con transaccion=True (lo que hace mas de una cosa, como el editor) se
    confirma todo junto o nada. Con transaccion=False cada consulta se guarda
    sola: es para lo que hace una sola consulta (los pedidos, el panel), y se
    ahorra el BEGIN y el COMMIT, que son dos viajes mas a San Pablo.
    """
    pool = obtener_pool()
    if pool is None:
        return _recorrer_sin_pool(funcion, por_defecto)

    for intento in (1, 2):
        try:
            with pool.connection() as conn:
                conn.autocommit = not transaccion
                # Al salir del with sin error se hace commit; con error, rollback.
                return funcion(conn.cursor())
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
    """Si el local acepta pedidos. Sin nada guardado, esta abierto."""
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
        # Si la base no contesta no se puede saber; el pedido igual va a fallar
        # al guardarse y el cliente recibe ese error, que es el verdadero.
        return True
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
    return jsonify({"ok": True, "varios_a_la_vez": bool(request.environ.get("wsgi.multithread"))})


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
COLUMNAS_PEDIDO = (
    "id, items, total, estado, envio, cliente, oculto,"
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
    if not local_abierto():
        return jsonify({
            "error": "El local esta cerrado ahora mismo. No se pudo enviar el pedido.",
            "codigo": "local_cerrado",
        }), 503

    items = data.get("items", [])
    platos = platos_del_pedido(items) if isinstance(items, list) else []
    if not platos:
        return jsonify({"error": "Se requiere al menos un plato"}), 400

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

    def trabajo(cur):
        # En la misma consulta se cuenta cuantos pedidos hizo antes ese mismo
        # telefono, asi no es un viaje mas a la base.
        cur.execute(
            "INSERT INTO pedidos (items, total, envio, cliente)"
            " VALUES (%s::jsonb, %s, %s, jsonb_set(%s::jsonb, '{pedidos_anteriores}',"
            "   to_jsonb((SELECT count(*) FROM pedidos"
            "              WHERE %s <> '' AND cliente->>'telefono_normalizado' = %s))))"
            " RETURNING id",
            (json.dumps(platos, ensure_ascii=False), total, envio,
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

    def trabajo(cur):
        cur.execute("UPDATE pedidos SET estado = %s WHERE id = %s", (estado, order_id))
        return cur.rowcount

    cambiados = recorrer_base(trabajo, transaccion=False)
    if cambiados is None:
        return sin_base()
    if cambiados == 0:
        return jsonify({"error": "Pedido no encontrado"}), 404
    return jsonify({"ok": True, "order_id": order_id, "estado": estado})


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

    partes = [
        texto_limpio(cliente.get("calle"), 120),
        texto_limpio(cliente.get("numero"), 20),
    ]
    entre = texto_limpio(cliente.get("entre"), 80)
    direccion = " ".join(parte for parte in partes if parte)
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
