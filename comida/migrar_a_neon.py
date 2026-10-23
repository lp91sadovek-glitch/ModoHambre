"""
MODO HAMBRE — Pasar los pedidos viejos a Neon.

Uso: python migrar_a_neon.py            (muestra lo que va a cargar, sin tocar nada)
     python migrar_a_neon.py --cargar   (los carga de verdad)

Antes los pedidos se guardaban en la PC del local: en orders.db (SQLite) y en
pedidos.jsonl (la copia permanente). Ahora viven en Neon, junto con el menu.
Este script lee esos dos archivos y copia cada pedido a la tabla "pedidos" de
Neon, como ya sacados de la pantalla (siguen viendose en el registro).

Se puede correr las veces que haga falta: cada pedido lleva una marca de donde
vino (migrado_de) y si ya estaba cargado no se repite.

La URL de la base se toma igual que en app.py: de la variable DATABASE_URL o
del archivo "para abrir la base de datos.txt".
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARCHIVO_SQLITE = BASE_DIR / "orders.db"
ARCHIVO_JSONL = BASE_DIR / "pedidos.jsonl"


def pedidos_de_sqlite():
    if not ARCHIVO_SQLITE.exists():
        return []
    conn = sqlite3.connect(ARCHIVO_SQLITE)
    conn.row_factory = sqlite3.Row
    try:
        filas = conn.execute(
            "SELECT id, items, total, estado, envio, cliente, created_at FROM orders"
        ).fetchall()
    except sqlite3.Error:
        # Una base vieja sin la tabla (o sin las columnas nuevas) no tiene nada
        # que pasar.
        return []
    finally:
        conn.close()
    return [dict(fila) for fila in filas]


def pedidos_del_jsonl():
    if not ARCHIVO_JSONL.exists():
        return []
    pedidos = []
    for linea in ARCHIVO_JSONL.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            pedidos.append(json.loads(linea))
        except ValueError:
            continue
    return pedidos


def como_lista(valor, por_defecto):
    """En SQLite los platos y el cliente estan como texto JSON; en el jsonl ya no."""
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except ValueError:
            return por_defecto
    return valor if valor is not None else por_defecto


def juntar_pedidos():
    """Une los dos archivos. Un mismo pedido (mismo id y fecha) cuenta una sola vez."""
    por_marca = {}
    for origen, pedidos in (("sqlite", pedidos_de_sqlite()), ("jsonl", pedidos_del_jsonl())):
        for pedido in pedidos:
            if not isinstance(pedido, dict) or pedido.get("id") is None:
                continue
            # El id solo no alcanza: cuando Render se reiniciaba los ids
            # volvian a empezar de 1, y hay pedidos distintos con el mismo id.
            marca = f"{pedido.get('id')}|{pedido.get('created_at')}"
            por_marca[marca] = {
                "marca": marca,
                "origen": origen,
                "items": como_lista(pedido.get("items"), []),
                "total": int(pedido.get("total") or 0),
                "estado": pedido.get("estado") or "listo",
                "envio": pedido.get("envio") or "local",
                "cliente": como_lista(pedido.get("cliente"), {}),
                "created_at": pedido.get("created_at"),
            }
    return sorted(por_marca.values(), key=lambda p: p["created_at"] or "")


def main():
    parser = argparse.ArgumentParser(description="Pasa los pedidos viejos a Neon.")
    parser.add_argument("--cargar", action="store_true", help="Cargarlos de verdad.")
    argumentos = parser.parse_args()

    pedidos = juntar_pedidos()
    print(f"Pedidos encontrados: {len(pedidos)}")
    for pedido in pedidos:
        print(f"  #{pedido['marca']:<30} ${pedido['total']:>8}  {pedido['estado']:<9} ({pedido['origen']})")

    if not pedidos:
        print("No hay nada para pasar.")
        return 0
    if not argumentos.cargar:
        print("")
        print("No se cargo nada. Para cargarlos: python migrar_a_neon.py --cargar")
        return 0

    sys.path.insert(0, str(BASE_DIR))
    import app  # crea las tablas de Neon si faltan, y trae la URL de la base

    conn = app.get_pg_conn()
    if conn is None:
        print("No se pudo conectar con Neon. Revisa DATABASE_URL o el archivo de la base.")
        return 1

    cargados = 0
    try:
        with conn.cursor() as cur:
            for pedido in pedidos:
                cur.execute(
                    "INSERT INTO pedidos (items, total, estado, envio, cliente, created_at,"
                    " oculto, migrado_de)"
                    " VALUES (%s::jsonb, %s, %s, %s, %s::jsonb,"
                    " COALESCE(%s::timestamp AT TIME ZONE 'UTC', now()), TRUE, %s)"
                    " ON CONFLICT (migrado_de) DO NOTHING",
                    (
                        json.dumps(pedido["items"], ensure_ascii=False),
                        pedido["total"],
                        pedido["estado"],
                        pedido["envio"],
                        json.dumps(pedido["cliente"], ensure_ascii=False),
                        pedido["created_at"],
                        pedido["marca"],
                    ),
                )
                cargados += cur.rowcount
        conn.commit()
    except Exception as error:
        conn.rollback()
        print(f"No se pudo cargar: {type(error).__name__}: {error}")
        return 1
    finally:
        conn.close()

    print("")
    print(f"Listo: {cargados} pedidos nuevos en Neon"
          f" ({len(pedidos) - cargados} ya estaban cargados).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
