"""
MODO HAMBRE — Instalación de requerimientos.

Uso: doble clic en este archivo (o "python instalar_requerimientos.py").

Este archivo solamente instala lo que hace falta para que Modo Hambre
funcione. No levanta el servidor ni abre nada: para eso esta app.py.
"""

import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REQUIREMENTS = BASE_DIR / "requirements.txt"
APP = BASE_DIR / "app.py"


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
    """El bloque con que se cierra el programa, siempre con la misma forma."""
    mostrar_mensaje("-" * 60)
    mostrar_mensaje(f"  {titulo}")
    for linea in lineas:
        mostrar_mensaje(f"  {linea}")
    mostrar_mensaje("-" * 60)
    mostrar_mensaje("")


def leer_requerimientos():
    """Saca los nombres de los paquetes de requirements.txt."""
    nombres = []
    for linea in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#")[0].split(";")[0].strip()
        if not linea:
            continue
        # queda solo el nombre: fuera versiones, extras y espacios
        nombre = re.split(r"[<>=!~\[ ]", linea, maxsplit=1)[0].strip()
        if nombre:
            nombres.append(nombre)
    return nombres


def faltan_requerimientos(nombres):
    """Devuelve los paquetes que todavia no estan, o None si no se puede saber."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return None

    faltan = []
    for nombre in nombres:
        try:
            version(nombre)
        except PackageNotFoundError:
            faltan.append(nombre)
        except Exception:
            return None
    return faltan


def instalar_requerimientos():
    """Instala los requerimientos. Devuelve 'listos', 'instalados' o 'error'."""
    if not REQUIREMENTS.exists():
        mostrar_aviso(
            "No se encontro requirements.txt.",
            ["No se puede instalar nada sin ese archivo."],
        )
        return "error"

    faltan = faltan_requerimientos(leer_requerimientos())
    if faltan == []:
        return "listos"

    if faltan is None:
        mostrar_mensaje("Revisando las dependencias...")
    else:
        mostrar_mensaje(f"Faltan {len(faltan)} dependencia(s). Instalando, puede tardar un momento...")
    mostrar_mensaje("")

    resultado = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=str(BASE_DIR),
    )
    if resultado.returncode != 0:
        mostrar_mensaje("")
        mostrar_aviso(
            "No se pudieron instalar los requerimientos.",
            ["Revisa tu conexion a internet y volve a intentarlo."],
        )
        return "error"

    return "instalados"


def main():
    mostrar_titulo("Instalacion de requerimientos")

    if not APP.exists():
        mostrar_aviso(
            "No se encontro app.py.",
            ["Este archivo instala los requerimientos, no levanta el host."],
        )
        input("\nPresiona ENTER para cerrar...")
        return

    resultado = instalar_requerimientos()

    if resultado == "listos":
        mostrar_aviso("Los requerimientos ya estan instalados.")
    elif resultado == "instalados":
        mostrar_aviso("Requerimientos instalados exitosamente.")
    else:
        input("\nPresiona ENTER para cerrar...")
        return

    mostrar_mensaje("  Para levantar el host, doble clic en app.py")
    mostrar_mensaje('  (o escribe "python app.py").')
    input("\nPresiona ENTER para cerrar...")


if __name__ == "__main__":
    main()
