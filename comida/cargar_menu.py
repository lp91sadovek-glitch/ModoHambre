"""Cargar el menu que ya esta escrito en platos.html dentro de Neon.

Es un script de una sola vez. Lee las categorias, las comidas y los gustos que
hoy estan escritas a mano en el HTML, les achica las fotos y los sube a la
base. Despues el HTML ya no manda: lo que este en la base es lo que se ve, y
se edita desde el panel.

Como usarlo
-----------

    python cargar_menu.py

No pide clave: esto corre en la PC del dueno, que ya tiene la URL de la base
escrita en "para abrir la base de datos.txt".

Cuidado
-------

Si la base ya tiene categorias, el script NO las borra: agrega las del HTML al
final. Para empezar de cero, o para repetir la carga exacta:

    python cargar_menu.py --vaciar

--vaciar borra categorias, comidas y gustos. Las fotos se conservan, para no
volver a subirlas.
"""

import argparse
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARCHIVO_HTML = BASE_DIR / "platos.html"
CARPETA_FOTOS = BASE_DIR / "imagenes"
ARCHIVO_DB = "para abrir la base de datos.txt"

ANCHO_MAXIMO_FOTO = 900
CALIDAD_WEBP = 80


def mostrar_mensaje(texto):
    print(texto.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()


def mostrar_titulo(subtitulo):
    mostrar_mensaje("=" * 62)
    mostrar_mensaje("  MODO HAMBRE")
    mostrar_mensaje(f"  {subtitulo}")
    mostrar_mensaje("=" * 62)
    mostrar_mensaje("")


def mostrar_aviso(titulo, lineas=()):
    mostrar_mensaje("-" * 62)
    mostrar_mensaje(f"  {titulo}")
    for linea in lineas:
        mostrar_mensaje(f"  {linea}")
    mostrar_mensaje("-" * 62)
    mostrar_mensaje("")


def pausar():
    try:
        input("\nPresiona ENTER para cerrar...")
    except (EOFError, KeyboardInterrupt):
        pass


# ---------------------------------------------------------------------------
# LEER EL MENU DEL HTML
#
# No se usa BeautifulSoup a proposito: el HTML tiene una forma muy parejo (el
# mismo <article class="plato"> en todas las categorias) y con la biblioteca
# estandar sale bien, sin agregar dependencias.
# ---------------------------------------------------------------------------


def texto_de(html):
    """Saca el texto de un fragmento, sin las etiquetas."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def precio_de(texto):
    """'$150 c/u' -> 150.   '$1.500' -> 1500."""
    digitos = re.sub(r"[^\d]", "", texto or "")
    return int(digitos) if digitos else 0


def descripcion_util(nombre, parrafo):
    """Devuelve el parrafo solo si explica algo mas que el nombre.

    '<p>Tortilla de papa.</p>' con nombre 'Tortilla de papa' no dice nada nuevo:
    guardarlo como descripcion haria que el cliente lo lea dos veces en la
    pagina. '<p>Pollo al espiedo con papas, cheddar y ensaladas.</p>' si
    aporta, y ese se guarda.
    """
    def normalizar(texto):
        return re.sub(r"\s+", " ", (texto or "").strip().rstrip(".")).strip().lower()

    parrafo = (parrafo or "").strip()
    if not parrafo:
        return ""
    if normalizar(parrafo) == normalizar(nombre):
        return ""
    return parrafo


def leer_menu_del_html(ruta):
    """Devuelve [{'nombre', 'icono', 'comidas': [...]}] tal como esta en el HTML."""
    html = ruta.read_text(encoding="utf-8")

    # Cada categoria arranca con <div class="categoria">. Partir por ahi es mucho
    # mas seguro que contar <div> abiertos, porque se anidan entre si.
    menu = []
    for trozo in html.split('<div class="categoria">')[1:]:
        if '<div class="categoria-contenido">' not in trozo:
            continue
        cabecera, cuerpo = trozo.split('<div class="categoria-contenido">', 1)

        boton = re.search(r'<button class="categoria-toggle"[^>]*>(.*?)</button>', cabecera, re.S)
        if not boton:
            continue
        # El nombre esta en el <span> sin clase; el emoji en el que si la tiene.
        nombre_m = re.search(r"<span>(.*?)</span>", boton.group(1), re.S)
        if not nombre_m:
            continue
        nombre = texto_de(nombre_m.group(1))
        if not nombre:
            continue
        icono_m = re.search(
            r'<span class="categoria-icono-circulo">(.*?)</span>', boton.group(1), re.S
        )

        comidas = []
        for etiqueta, articulo in re.findall(
            r'(<article class="plato"[^>]*>)(.*?)</article>', cuerpo, re.S
        ):
            comida = leer_comida(articulo)
            if comida:
                # Los <article id="menu-empanadas"> son los que hacen que el
                # link "ver en el menú" de la pagina de inicio abra esta comida.
                ancla = re.search(r'id="menu-([^"]+)"', etiqueta)
                comida["ancla"] = ancla.group(1) if ancla else None
                comidas.append(comida)

        menu.append(
            {
                "nombre": nombre,
                "icono": texto_de(icono_m.group(1)) if icono_m else "",
                "comidas": comidas,
            }
        )

    if not menu:
        raise SystemExit("No se encontro ninguna categoria en el HTML. El archivo cambio de forma?")
    return menu


def leer_comida(articulo):
    foto_m = re.search(r'<img[^>]*\ssrc="([^"]*)"', articulo)
    texto_m = re.search(r"<p>(.*?)</p>", articulo, re.S)
    precio_m = re.search(r'<span class="plato-price">(.*?)</span>', articulo, re.S)

    parrafo = texto_de(texto_m.group(1)) if texto_m else ""
    nombre = ""
    precio = 0

    # Las comidas simples traen el nombre y el precio en el boton.
    directo = re.search(
        r'<button[^>]*\bclass="boton add-cart"[^>]*\bdata-name="([^"]*)"'
        r'[^>]*\bdata-price="(\d+)"',
        articulo,
    )
    if directo:
        nombre = directo.group(1).strip()
        precio = int(directo.group(2))
    elif precio_m:
        precio = precio_de(texto_de(precio_m.group(1)))

    # Las que tienen varios gustos no traen nombre en el boton: el nombre es
    # lo que ya decia el <p>. Sin el punto final, porque el nombre se muestra
    # como titulo y la pagina le pone el punto si hace falta.
    if not nombre:
        nombre = parrafo.rstrip(".")
    if not nombre:
        return None

    gustos = []
    for variante in re.findall(r'<div class="variante">(.*?)</div>', articulo, re.S):
        etiqueta = texto_de(variante)
        # 'Carne · $150' -> 'Carne'
        nombre_gusto = re.split(r"[·•$]", etiqueta)[0].strip()
        precio_gusto_m = re.search(r'data-price="(\d+)"', variante)
        precio_gusto = (
            int(precio_gusto_m.group(1)) if precio_gusto_m else precio_de(etiqueta)
        )
        if not nombre_gusto:
            continue
        gustos.append({"nombre": nombre_gusto, "precio": precio_gusto})

    return {
        "nombre": nombre,
        "descripcion": descripcion_util(nombre, parrafo),
        "precio": precio,
        "tipo": "gustos" if gustos else "simple",
        "foto": Path(foto_m.group(1)).name if foto_m else "",
        "gustos": gustos,
    }


# ---------------------------------------------------------------------------
# LA BASE
# ---------------------------------------------------------------------------


def leer_url_de_archivo():
    """Busca la URL de Neon en el archivo local.

    Usa la misma función que el host, y no una copia: si cada uno leyera el
    archivo por su cuenta, pasaría lo que ya pasó. El archivo tiene URLs de
    EJEMPLO arriba para explicar cómo se ve una URL, y una copia sin protección
    agarra la del ejemplo en vez de la real. Ese error tardó en verse y era
    difícil de entender (dejaba un error rarísimo de 'idna').
    """
    if BASE_DIR not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    try:
        import app
    except Exception as error:
        mostrar_aviso(
            "No se pudo leer app.py para buscar la URL de la base.",
            [f"{type(error).__name__}: {error}"],
        )
        return ""

    return app.leer_db_url_del_archivo()


def conectar(url):
    try:
        import psycopg
    except ImportError:
        mostrar_aviso(
            "Falta la dependencia 'psycopg'.",
            ["Instalala con: pip install -r requirements.txt"],
        )
        raise SystemExit(1)
    from psycopg.rows import dict_row

    try:
        # dict_row: las filas vuelven como diccionario, y se leen por nombre
        # (fila["nombre"]) en vez de por posición. Sin esto, psycopg devuelve
        # tuplas y "fila["nombre"]" revienta con un error de tipo.
        return psycopg.connect(url, row_factory=dict_row, connect_timeout=15)
    except Exception as error:
        mostrar_aviso(
            "No se pudo conectar con la base de Neon.",
            [
                f"{type(error).__name__}: {error}",
                "",
                "Revisa que la URL en 'para abrir la base de datos.txt'",
                "sea la POOLED (la que tiene '-pooler' en el host)",
                "y que la base este prendida en el panel de Neon.",
            ],
        )
        raise SystemExit(1)


def subir_fotos(cur, fotos, ya_subidas):
    """Convierte las fotos a WebP y las sube. Devuelve {archivo: id de imagen}."""
    import io

    try:
        from PIL import Image, ImageOps
    except ImportError:
        mostrar_aviso(
            "Falta 'pillow', asi que las fotos se suben sin achicar.",
            ["Instalalo con: pip install -r requirements.txt", "para que pesen menos."],
        )
        Image = None
        ImageOps = None

    resultado = dict(ya_subidas)
    total = len(fotos)
    for numero, archivo in enumerate(fotos, start=1):
        if archivo in resultado:
            mostrar_mensaje(f"  ({numero}/{total}) {archivo}: ya estaba, no se vuelve a subir")
            continue
        ruta = CARPETA_FOTOS / archivo
        if not ruta.exists():
            mostrar_mensaje(f"  ({numero}/{total}) {archivo}: NO EXISTE, se deja sin foto")
            continue

        contenido = ruta.read_bytes()
        mime = "image/webp"
        if Image is not None:
            with Image.open(io.BytesIO(contenido)) as imagen:
                # Los celulares guardan la rotacion en el EXIF en vez de girar
                # los pixeles; sin esto las fotos salen acostadas.
                imagen = ImageOps.exif_transpose(imagen)
                if imagen.mode not in ("RGB", "RGBA"):
                    imagen = imagen.convert("RGBA" if "A" in imagen.getbands() else "RGB")
                # thumbnail solo achica, nunca agranda: una foto chica no se
                # queda borrosa por esto.
                imagen.thumbnail((ANCHO_MAXIMO_FOTO, ANCHO_MAXIMO_FOTO), Image.LANCZOS)
                salida = io.BytesIO()
                imagen.save(salida, format="WEBP", quality=CALIDAD_WEBP, method=4)
            contenido = salida.getvalue()

        # Se guarda el nombre del archivo de origen con el que se lo reconoce,
        # asi una segunda carga no vuelve a subir lo que ya esta.
        cur.execute(
            "INSERT INTO imagenes (nombre, mime, contenido) VALUES (%s, %s, %s) RETURNING id",
            (archivo[:120], mime, contenido),
        )
        resultado[archivo] = cur.fetchone()["id"]
        mostrar_mensaje(f"  ({numero}/{total}) {archivo}: {len(contenido) // 1024} KB")
    return resultado


def main():
    analizador = argparse.ArgumentParser(description="Carga el menu del HTML en Neon.")
    analizador.add_argument(
        "--vaciar",
        action="store_true",
        help="Borra las categorias, comidas y gustos que ya hay antes de cargar.",
    )
    argumentos = analizador.parse_args()

    mostrar_titulo("Cargar el menu en la base de datos")

    if not ARCHIVO_HTML.exists():
        mostrar_aviso("No se encontro platos.html", [str(ARCHIVO_HTML)])
        pausar()
        return 1

    url = os.environ.get("DATABASE_URL", "").strip() or leer_url_de_archivo()
    if not url:
        mostrar_aviso(
            "No hay URL de conexion a la base.",
            [
                "Agregala en el archivo:",
                f"  {ARCHIVO_DB}",
                "",
                "Con la linea:  DATABASE_URL: postgresql://...",
                "",
                "Tiene que ser la POOLED, la que tiene '-pooler' en el host.",
            ],
        )
        pausar()
        return 1

    mostrar_mensaje("Leyendo el menu del HTML...")
    menu = leer_menu_del_html(ARCHIVO_HTML)
    total_comidas = sum(len(categoria["comidas"]) for categoria in menu)
    total_gustos = sum(
        len(comida["gustos"]) for categoria in menu for comida in categoria["comidas"]
    )
    mostrar_mensaje(f"  {len(menu)} categorias, {total_comidas} comidas y {total_gustos} gustos.")
    mostrar_mensaje("")

    mostrar_mensaje("Conectando con Neon...")
    conn = conectar(url)
    mostrar_mensaje("  Conectado.")
    mostrar_mensaje("")

    import app

    try:
        with conn.cursor() as cur:
            for sentencia in app.TABLAS_NEON:
                cur.execute(sentencia)

            if argumentos.vaciar:
                cur.execute("SELECT COUNT(*) AS total FROM categorias")
                if cur.fetchone()["total"]:
                    mostrar_mensaje("Vaciando el menu anterior...")
                    cur.execute("DELETE FROM categorias")
                    conn.commit()

            # Las fotos que ya estan en la base, para no subirlas de nuevo.
            cur.execute("SELECT nombre, id FROM imagenes")
            ya_subidas = {fila["nombre"]: fila["id"] for fila in cur.fetchall()}

            fotos = []
            vistas = set()
            for categoria in menu:
                for comida in categoria["comidas"]:
                    foto = comida["foto"]
                    if foto and foto not in vistas:
                        vistas.add(foto)
                        fotos.append(foto)

            if fotos:
                mostrar_mensaje(f"Subiendo {len(fotos)} fotos (se achican a WebP)...")
                ids_fotos = subir_fotos(cur, fotos, ya_subidas)
            else:
                ids_fotos = {}

            mostrar_mensaje("")
            mostrar_mensaje("Escribiendo el menu...")
            for numero_categoria, categoria in enumerate(menu, start=1):
                cur.execute(
                    "INSERT INTO categorias (nombre, icono, orden) VALUES (%s, %s, %s)"
                    " RETURNING id",
                    (categoria["nombre"], categoria["icono"], numero_categoria * 10),
                )
                categoria_id = cur.fetchone()["id"]
                mostrar_mensaje(f"  {categoria['nombre']}")

                for numero_comida, comida in enumerate(categoria["comidas"], start=1):
                    cur.execute(
                        "INSERT INTO comidas (categoria_id, nombre, descripcion, imagen,"
                        " precio, tipo, orden, activo, ancla)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)"
                        " RETURNING id",
                        (
                            categoria_id,
                            comida["nombre"],
                            comida["descripcion"],
                            ids_fotos.get(comida["foto"]),
                            comida["precio"],
                            comida["tipo"],
                            numero_comida * 10,
                            comida.get("ancla"),
                        ),
                    )
                    comida_id = cur.fetchone()["id"]
                    for numero_gusto, gusto in enumerate(comida["gustos"], start=1):
                        cur.execute(
                            "INSERT INTO gustos (comida_id, nombre, precio, orden)"
                            " VALUES (%s, %s, %s, %s)",
                            (comida_id, gusto["nombre"], gusto["precio"], numero_gusto * 10),
                        )
        conn.commit()
    except SystemExit:
        conn.close()
        raise
    except Exception as error:
        conn.rollback()
        conn.close()
        mostrar_aviso(
            "No se pudo cargar el menu. No se guardo nada.",
            [f"{type(error).__name__}: {error}"],
        )
        pausar()
        return 1

    with conn.cursor() as cur:
        cuentas = {}
        for tabla in ("categorias", "comidas", "gustos"):
            cur.execute(f"SELECT COUNT(*) AS total FROM {tabla}")
            cuentas[tabla] = cur.fetchone()["total"]
        cur.execute("SELECT COALESCE(SUM(octet_length(contenido)), 0) AS total FROM imagenes")
        bytes_fotos = cur.fetchone()["total"]
    conn.close()

    mostrar_mensaje("")
    mostrar_aviso(
        "Menu cargado.",
        [
            f"Categorias: {cuentas['categorias']}",
            f"Comidas:    {cuentas['comidas']}",
            f"Gustos:     {cuentas['gustos']}",
            f"Fotos:      {bytes_fotos / 1024 / 1024:.1f} MB de 500 MB",
            "",
            "Ahora el menu se edita desde el panel del local:",
            "  http://localhost:5000/menu.html",
            "",
            "Y lo que los clientes ven sale de ahi.",
        ],
    )
    pausar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
