"""MODO HAMBRE - PANEL DE DESARROLLADORES

Una ventana para la computadora de los desarrolladores. Muestra los equipos
que quedaron bloqueados por equivocarse 5 veces con la clave del panel (desde
un dispositivo nuevo), y deja aceptarlos (si son del dueno: se les dan 5
intentos mas) o rechazarlos (siguen bloqueados para siempre). Tambien muestra
el historial de entradas y claves equivocadas, para tener un monitoreo.

No es una pagina web: se conecta directo a la base de Neon con la URL del
archivo "para abrir la base de datos.txt", que no se sube al repositorio. Sin
ese archivo el programa no sirve, asi que solo lo pueden usar los
desarrolladores.

Como se abre:
    python panel-desarrolladores.py           (la base de verdad, la de Render)
    python panel-desarrolladores.py --vieja   (la base vieja de Brasil, para probar)
"""
import os
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None

CARPETA = Path(__file__).resolve().parent
ARCHIVO_DB = CARPETA / "para abrir la base de datos.txt"
SEGUNDOS_ACTUALIZAR = 10
NARANJA = "#FC8F02"


def url_de_la_base():
    """La URL sale del archivo de texto (o de la variable DATABASE_URL)."""
    llave = "DATABASE_URL_VIEJA_BRASIL:" if "--vieja" in sys.argv else "DATABASE_URL:"
    if ARCHIVO_DB.exists():
        for linea in ARCHIVO_DB.read_text(encoding="utf-8", errors="ignore").splitlines():
            if linea.strip().startswith(llave):
                url = linea.split(":", 1)[1].strip().strip("'\"")
                # el archivo tiene lineas de ejemplo ("postgresql://..."): se saltean
                if "@" in url and "..." not in url:
                    return url
    return "" if "--vieja" in sys.argv else os.environ.get("DATABASE_URL", "")


def navegador_corto(texto):
    """'Mozilla/5.0 (Windows NT 10.0...) Chrome/130...' -> 'Chrome · Windows'."""
    texto = texto or ""
    sistema = next((nombre for marca, nombre in (
        ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
        ("Mac OS", "Mac"), ("Linux", "Linux")) if marca in texto), "?")
    programa = next((nombre for marca, nombre in (
        ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
        ("Safari/", "Safari")) if marca in texto), "otro")
    if not texto:
        return "sin datos"
    if re.search(r"python|curl|wget|bot|http", texto, re.I) and programa == "otro":
        return "programa (" + texto[:30] + ")"
    return f"{programa} · {sistema}"


def hora(fecha):
    return fecha.astimezone().strftime("%d/%m %H:%M:%S") if fecha else ""


class Panel:
    def __init__(self, raiz, url):
        self.raiz = raiz
        self.url = url
        self.bloqueados_vistos = None
        raiz.title("Modo Hambre · Panel de desarrolladores")
        raiz.geometry("980x600")
        raiz.minsize(760, 420)

        estilo = ttk.Style()
        estilo.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        estilo.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        estilo.configure("TNotebook.Tab", padding=(14, 6), font=("Segoe UI", 10))

        cabecera = tk.Frame(raiz, bg="#171717")
        cabecera.pack(fill="x")
        tk.Label(cabecera, text="🛡️  Panel de desarrolladores", bg="#171717", fg=NARANJA,
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=14, pady=10)
        self.estado = tk.Label(cabecera, text="Conectando…", bg="#171717", fg="#cccccc",
                               font=("Segoe UI", 10))
        self.estado.pack(side="right", padx=14)

        self.pestanas = ttk.Notebook(raiz)
        self.pestanas.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Bloqueados ---
        marco = ttk.Frame(self.pestanas, padding=8)
        self.pestanas.add(marco, text="Bloqueados")
        ttk.Label(marco, text="Equipos que se equivocaron 5 veces con la clave. Si es el dueño, "
                              "aceptalo (le quedan 5 intentos más). Si no, rechazalo.",
                  wraplength=900).pack(anchor="w", pady=(0, 6))
        self.tabla_bloqueados = self.tabla(marco, (
            ("desde", "Bloqueado", 130), ("ip", "IP", 130), ("navegador", "Equipo", 170),
            ("intentos", "Intentos", 70), ("primera", "Apareció", 130), ("id", "Dispositivo", 120)))
        botones = ttk.Frame(marco)
        botones.pack(fill="x", pady=(8, 0))
        tk.Button(botones, text="✔  Es del dueño: aceptar", bg="#1e7b34", fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=6,
                  command=lambda: self.cambiar(self.tabla_bloqueados, "normal")).pack(side="left")
        tk.Button(botones, text="✖  No es del dueño: rechazar", bg="#b3261e", fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=6,
                  command=lambda: self.cambiar(self.tabla_bloqueados, "rechazado")).pack(side="left", padx=8)

        # --- Dispositivos ---
        marco = ttk.Frame(self.pestanas, padding=8)
        self.pestanas.add(marco, text="Dispositivos")
        ttk.Label(marco, text="Todos los equipos que intentaron entrar al panel.").pack(anchor="w", pady=(0, 6))
        self.tabla_dispositivos = self.tabla(marco, (
            ("estado", "Estado", 110), ("ultima", "Última vez", 130), ("ip", "IP", 130),
            ("navegador", "Equipo", 170), ("intentos", "Errores", 60), ("id", "Dispositivo", 120)))
        botones = ttk.Frame(marco)
        botones.pack(fill="x", pady=(8, 0))
        tk.Button(botones, text="Volver a habilitar", relief="flat", bg="#e8e8e8", padx=12, pady=5,
                  command=lambda: self.cambiar(self.tabla_dispositivos, "normal")).pack(side="left")

        # --- Historial ---
        marco = ttk.Frame(self.pestanas, padding=8)
        self.pestanas.add(marco, text="Historial")
        ttk.Label(marco, text="Los últimos 300 movimientos: entradas, claves equivocadas, bloqueos "
                              "y lo que hicieron los desarrolladores.").pack(anchor="w", pady=(0, 6))
        self.tabla_historial = self.tabla(marco, (
            ("cuando", "Cuándo", 130), ("resultado", "Qué pasó", 200), ("ip", "IP", 130),
            ("navegador", "Equipo", 170), ("id", "Dispositivo", 120)))

        self.actualizar()

    def tabla(self, padre, columnas):
        marco = ttk.Frame(padre)
        marco.pack(fill="both", expand=True)
        tabla = ttk.Treeview(marco, columns=[c[0] for c in columnas], show="headings", selectmode="browse")
        for nombre, titulo, ancho in columnas:
            tabla.heading(nombre, text=titulo)
            tabla.column(nombre, width=ancho, anchor="w")
        barra = ttk.Scrollbar(marco, orient="vertical", command=tabla.yview)
        tabla.configure(yscrollcommand=barra.set)
        tabla.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        tabla.tag_configure("bloqueado", foreground="#b3261e")
        tabla.tag_configure("rechazado", foreground="#888888")
        tabla.tag_configure("mal", foreground="#b3261e")
        tabla.tag_configure("bien", foreground="#1e7b34")
        return tabla

    def consultar(self, trabajo):
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=15,
                             prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                return trabajo(cur)

    def actualizar(self):
        try:
            def leer(cur):
                cur.execute("SELECT * FROM dispositivos ORDER BY ultima_vez DESC LIMIT 500")
                dispositivos = cur.fetchall()
                cur.execute("SELECT * FROM intentos_clave ORDER BY id DESC LIMIT 300")
                return dispositivos, cur.fetchall()

            dispositivos, historial = self.consultar(leer)
        except Exception as error:
            mensaje = str(error).replace(self.url, "<url>")
            if "dispositivos" in mensaje and "does not exist" in mensaje:
                mensaje = "la base todavía no tiene las tablas (se crean cuando arranca la página nueva)"
            self.estado.config(text="⚠️ Sin conexión: " + mensaje[:90], fg="#ffb4a8")
            self.raiz.after(SEGUNDOS_ACTUALIZAR * 1000, self.actualizar)
            return

        bloqueados = [d for d in dispositivos if d["estado"] == "bloqueado"]
        self.llenar(self.tabla_bloqueados, [
            (d["id"], (hora(d["bloqueado_at"]), d["ip"], navegador_corto(d["navegador"]), d["intentos"],
                       hora(d["primera_vez"]), d["id"][:12] + "…"), "bloqueado") for d in bloqueados])
        nombres = {"normal": "Habilitado", "bloqueado": "🔒 Bloqueado", "rechazado": "⛔ Rechazado"}
        self.llenar(self.tabla_dispositivos, [
            (d["id"], (nombres.get(d["estado"], d["estado"]) + ("" if d["conocido"] or d["estado"] != "normal"
                                                                 else " (nuevo)"),
                       hora(d["ultima_vez"]), d["ip"], navegador_corto(d["navegador"]), d["intentos"],
                       d["id"][:12] + "…"), d["estado"] if d["estado"] != "normal" else "")
            for d in dispositivos])
        self.llenar(self.tabla_historial, [
            (str(h["id"]), (hora(h["created_at"]), h["resultado"], h["ip"], navegador_corto(h["navegador"]),
                            (h["dispositivo"] or "")[:12] + "…"),
             "bien" if h["resultado"] in ("entro", "aceptado por un desarrollador") else
             "mal" if h["resultado"] in ("clave equivocada", "bloqueado") else "")
            for h in historial])

        self.pestanas.tab(0, text=f"Bloqueados ({len(bloqueados)})" if bloqueados else "Bloqueados")
        nuevos = {d["id"] for d in bloqueados}
        if self.bloqueados_vistos is not None and nuevos - self.bloqueados_vistos:
            # aparecio un bloqueado nuevo mientras el programa estaba abierto
            self.raiz.bell()
            self.pestanas.select(0)
            self.raiz.deiconify()
            self.raiz.lift()
        self.bloqueados_vistos = nuevos
        base = "base vieja (prueba)" if "--vieja" in sys.argv else "base de la página"
        self.estado.config(text=f"✔ Conectado a la {base} · se actualiza cada {SEGUNDOS_ACTUALIZAR} s",
                           fg="#9be09b")
        self.raiz.after(SEGUNDOS_ACTUALIZAR * 1000, self.actualizar)

    def llenar(self, tabla, filas):
        elegido = tabla.selection()
        tabla.delete(*tabla.get_children())
        for iid, valores, etiqueta in filas:
            tabla.insert("", "end", iid=iid, values=valores, tags=(etiqueta,) if etiqueta else ())
        if elegido and tabla.exists(elegido[0]):
            tabla.selection_set(elegido[0])

    def cambiar(self, tabla, estado):
        elegido = tabla.selection()
        if not elegido:
            messagebox.showinfo("Elegí un equipo", "Primero tocá un equipo de la lista.")
            return
        dispositivo = elegido[0]
        if estado == "normal":
            pregunta = ("¿Aceptar este equipo?\n\nVa a tener 5 intentos más para escribir la clave. "
                        "Hacelo solo si sabés que es del dueño.")
            resultado = "aceptado por un desarrollador"
        else:
            pregunta = "¿Rechazar este equipo?\n\nVa a seguir bloqueado y no va a poder entrar al panel."
            resultado = "rechazado por un desarrollador"
        if not messagebox.askyesno("Confirmar", pregunta):
            return

        def trabajo(cur):
            cur.execute("UPDATE dispositivos SET estado = %s, intentos = 0, revisado_at = now()"
                        " WHERE id = %s", (estado, dispositivo))
            cur.execute("INSERT INTO intentos_clave (dispositivo, resultado) VALUES (%s, %s)",
                        (dispositivo, resultado))

        try:
            self.consultar(trabajo)
        except Exception as error:
            messagebox.showerror("No se pudo", str(error).replace(self.url, "<url>"))
            return
        self.actualizar()


def main():
    if psycopg is None:
        print("Falta psycopg. Instalalo con:  pip install \"psycopg[binary]\"")
        return
    url = url_de_la_base()
    if not url:
        print(f"No encontré la URL de la base. Tiene que estar en: {ARCHIVO_DB.name}")
        return
    raiz = tk.Tk()
    Panel(raiz, url)
    raiz.mainloop()


if __name__ == "__main__":
    main()
