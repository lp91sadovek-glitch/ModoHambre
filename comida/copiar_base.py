"""
MODO HAMBRE — Copiar la base de Neon a otra base de Neon.

Se uso para pasar la base de San Pablo (Brasil) a Oregon (Estados Unidos), al
lado de Render: cada consulta tardaba ~0,2 s solo en ir y volver de Brasil.

Uso:
    python copiar_base.py                 copia todo (menu, fotos, pedidos...)
    python copiar_base.py --solo-pedidos  copia solo los pedidos que falten

De donde saca las bases:
    vieja -> la misma que usa app.py (DATABASE_URL o el archivo de la base)
    nueva -> la linea "DATABASE_URL_NUEVA:" de "para abrir la base de datos.txt"
             (o la variable de entorno DATABASE_URL_NUEVA)

La base vieja no se toca: solo se lee.

Como se usa en la mudanza:
  1. "python copiar_base.py" antes de cambiar DATABASE_URL en Render.
  2. Se cambia DATABASE_URL en Render por la nueva.
  3. "python copiar_base.py --solo-pedidos" enseguida, por si entro algun
     pedido en la vieja mientras tanto. No pisa los pedidos que ya entraron en
     la nueva: los numeros de pedido de la nueva arrancan 100 mas arriba que
     los de la vieja, justo para que no choquen.
  No editar el menu entre el paso 1 y el 2: esos cambios quedarian en la vieja.
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import app  # noqa: E402  (trae la URL de la base vieja y las tablas)
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

# En este orden, por las referencias entre tablas: una comida apunta a su
# categoria y a su foto, y un gusto apunta a su comida.
TABLAS = [
    ("categorias", "id"),
    ("imagenes", "id"),
    ("comidas", "id"),
    ("gustos", "id"),
    ("clientes", "id"),
    ("pedidos", "id"),
    ("ajustes", "clave"),
]

# Lugar que se deja entre el ultimo pedido de la vieja y el primero de la nueva.
LUGAR_PARA_PEDIDOS = 100


def url_nueva():
    url = app.limpiar_url(os.environ.get("DATABASE_URL_NUEVA", ""))
    if app.url_de_conexion_valida(url):
        return url
    for carpeta in (BASE_DIR, BASE_DIR.parent):
        ruta = carpeta / app.ARCHIVO_DB
        if not ruta.exists():
            continue
        for linea in ruta.read_text(encoding="utf-8", errors="ignore").splitlines():
            if linea.strip().upper().startswith("DATABASE_URL_NUEVA:"):
                url = app.limpiar_url(linea.split(":", 1)[1])
                if app.url_de_conexion_valida(url):
                    return url
    return ""


def region(url):
    """Solo el pedazo de la region (sa-east-1, us-west-2), sin la clave."""
    for parte in url.split("."):
        if parte.count("-") == 2 and parte[-1].isdigit():
            return parte
    return "?"


def conectar(url):
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=15,
                           prepare_threshold=None)


def como_valor(valor):
    # Los platos y los datos del cliente son JSON: hay que mandarlos como tal.
    return Jsonb(valor) if isinstance(valor, (dict, list)) else valor


def copiar_tabla(vieja, nueva, tabla, llave, solo_agregar):
    with vieja.cursor() as cur:
        cur.execute(f"SELECT * FROM {tabla} ORDER BY {llave}")
        filas = cur.fetchall()
    if not filas:
        return 0
    columnas = list(filas[0].keys())
    lista = ", ".join(columnas)
    marcas = ", ".join(["%s"] * len(columnas))
    if solo_agregar:
        al_chocar = "DO NOTHING"
    else:
        al_chocar = "DO UPDATE SET " + ", ".join(
            f"{c} = EXCLUDED.{c}" for c in columnas if c != llave
        )
    sql = f"INSERT INTO {tabla} ({lista}) VALUES ({marcas}) ON CONFLICT ({llave}) {al_chocar}"
    copiadas = 0
    with nueva.cursor() as cur:
        for fila in filas:
            cur.execute(sql, [como_valor(fila[c]) for c in columnas])
            copiadas += cur.rowcount
    return copiadas


def acomodar_numeradores(vieja, nueva):
    """Que los ids nuevos sigan despues de los copiados (y no choquen)."""
    with vieja.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) AS maximo FROM pedidos")
        maximo_viejo = cur.fetchone()["maximo"]
    with nueva.cursor() as cur:
        for tabla, llave in TABLAS:
            if llave != "id":
                continue
            cur.execute(f"SELECT COALESCE(MAX(id), 0) AS maximo FROM {tabla}")
            maximo = cur.fetchone()["maximo"]
            if tabla == "pedidos":
                maximo = max(maximo, maximo_viejo + LUGAR_PARA_PEDIDOS)
            if maximo > 0:
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s)", (tabla, maximo)
                )


def comparar(vieja, nueva, tablas):
    """Cuenta las filas y compara el contenido entero de cada tabla."""
    iguales = True
    for tabla, llave in tablas:
        resultados = []
        for conn in (vieja, nueva):
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT count(*) AS n, md5(COALESCE(string_agg(t::text, '|' ORDER BY {llave}), ''))"
                    f" AS huella FROM {tabla} t"
                )
                resultados.append(cur.fetchone())
        igual = resultados[0]["huella"] == resultados[1]["huella"]
        iguales = iguales and igual
        print(f"  {tabla:<11} vieja={resultados[0]['n']:<4} nueva={resultados[1]['n']:<4}"
              f" {'IGUAL' if igual else 'DISTINTA'}")
    return iguales


def main():
    parser = argparse.ArgumentParser(description="Copia la base de Neon a la nueva.")
    parser.add_argument("--solo-pedidos", action="store_true",
                        help="Copiar solo los pedidos que falten en la nueva.")
    argumentos = parser.parse_args()

    origen, destino = app.DATABASE_URL, url_nueva()
    if not origen or not destino:
        print("Falta la URL de la base vieja o la de la nueva (DATABASE_URL_NUEVA).")
        return 1
    if origen == destino:
        print("La base vieja y la nueva son la misma. No hay nada que copiar.")
        return 1
    print(f"Copiando de {region(origen)} a {region(destino)}...")

    vieja = conectar(origen)
    nueva = conectar(destino)
    try:
        with nueva.cursor() as cur:
            for sentencia in app.TABLAS_NEON:
                cur.execute(sentencia)

        tablas = [("pedidos", "id")] if argumentos.solo_pedidos else TABLAS
        for tabla, llave in tablas:
            copiadas = copiar_tabla(vieja, nueva, tabla, llave, argumentos.solo_pedidos)
            print(f"  {tabla:<11} {copiadas} filas copiadas")
        acomodar_numeradores(vieja, nueva)
        # Todo o nada: si algo falla a la mitad, la nueva queda como estaba.
        nueva.commit()
    except Exception as error:
        nueva.rollback()
        print(f"No se pudo copiar: {type(error).__name__}: {error}")
        return 1
    finally:
        vieja.close()

    try:
        if argumentos.solo_pedidos:
            print("Listo. (Despues de la mudanza la nueva puede tener pedidos que la vieja no.)")
            return 0
        print("")
        print("Comparando las dos bases:")
        iguales = comparar(vieja := conectar(origen), nueva, TABLAS)
        vieja.close()
    finally:
        nueva.close()
    print("")
    print("Listo: las dos bases tienen lo mismo." if iguales
          else "OJO: hay tablas distintas, revisar antes de cambiar Render.")
    return 0 if iguales else 1


if __name__ == "__main__":
    sys.exit(main())
