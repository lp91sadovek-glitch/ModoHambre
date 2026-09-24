import json
import sqlite3
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "orders.db"

app = Flask(__name__, static_folder=".", static_url_path="")


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


@app.route("/api/orders", methods=["GET", "POST"])
def orders():
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


def run_http_server():
    make_server("0.0.0.0", 5000, app, threaded=True).serve_forever()


def run_https_server():
    make_server("0.0.0.0", 5001, app, threaded=True, ssl_context="adhoc").serve_forever()


if __name__ == "__main__":
    threads = [
        threading.Thread(target=run_http_server, daemon=True),
        threading.Thread(target=run_https_server, daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Servidor detenido")
