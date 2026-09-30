"""
MODO HAMBRE — Instalación y puesta en marcha.

Uso: doble clic en este archivo (o "python instalar_ejecutar.py").

Instala las dependencias, levanta el servidor y abre el panel de pedidos.
"""

import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REQUIREMENTS = BASE_DIR / "requirements.txt"
APP = BASE_DIR / "app.py"

CLIENT_URL = "http://localhost:5000"
ADMIN_URL = "http://localhost:5000/admin.html"


def mostrar_mensaje(texto):
    """Imprime sin problemas caracteres especiales en la consola de Windows."""
    print(texto.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()


def instalar_dependencias():
    if not REQUIREMENTS.exists():
        mostrar_mensaje("ERROR: no se encontro requirements.txt")
        return False

    mostrar_mensaje("Instalando dependencias (puede tardar un momento)...")
    resultado = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=str(BASE_DIR),
    )
    if resultado.returncode != 0:
        mostrar_mensaje("")
        mostrar_mensaje("No se pudieron instalar las dependencias.")
        mostrar_mensaje("Revisa tu conexion a internet y volve a intentarlo.")
        return False

    mostrar_mensaje("Dependencias listas.")
    return True


def esperar_servidor(intentos=20):
    """Espera a que el servidor responda en lugar de asumir que levanto."""
    for _ in range(intentos):
        try:
            with urllib.request.urlopen(CLIENT_URL, timeout=2):
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    mostrar_mensaje("=" * 60)
    mostrar_mensaje("  MODO HAMBRE")
    mostrar_mensaje("  Instalacion y puesta en marcha")
    mostrar_mensaje("=" * 60)

    if not APP.exists():
        mostrar_mensaje("")
        mostrar_mensaje("ERROR: no se encontro app.py")
        return

    mostrar_mensaje("")
    if not instalar_dependencias():
        input("\nPresiona ENTER para cerrar...")
        return

    servidor = subprocess.Popen([sys.executable, str(APP)], cwd=str(BASE_DIR))

    mostrar_mensaje("")
    mostrar_mensaje("Arrancando el servidor...")
    if not esperar_servidor():
        servidor.terminate()
        mostrar_mensaje("")
        mostrar_mensaje("El servidor no se pudo levantar.")
        mostrar_mensaje("Revisa si el puerto 5000 esta ocupado:")
        mostrar_mensaje("  netstat -ano | findstr :5000")
        input("\nPresiona ENTER para cerrar...")
        return

    mostrar_mensaje("")
    mostrar_mensaje("-" * 60)
    mostrar_mensaje("  El servidor esta funcionando.")
    mostrar_mensaje("")
    mostrar_mensaje(f"  Pagina para tus clientes:  {CLIENT_URL}")
    mostrar_mensaje(f"  Panel de pedidos:         {ADMIN_URL}")
    mostrar_mensaje("")
    mostrar_mensaje("  El panel recibe los pedidos que hacen tus clientes")
    mostrar_mensaje("  en la web.")
    mostrar_mensaje("-" * 60)
    mostrar_mensaje("")
    mostrar_mensaje("Presiona Ctrl+C para detener el servidor.")
    mostrar_mensaje("")

    try:
        webbrowser.open(ADMIN_URL)
    except Exception:
        mostrar_mensaje("No se pudo abrir el navegador. Abrilo manualmente en:")
        mostrar_mensaje(f"  {ADMIN_URL}")

    try:
        servidor.wait()
    except KeyboardInterrupt:
        mostrar_mensaje("")
        mostrar_mensaje("Deteniendo el servidor...")
        servidor.terminate()
        try:
            servidor.wait(timeout=5)
        except Exception:
            servidor.kill()

    input("\nPresiona ENTER para cerrar...")


if __name__ == "__main__":
    main()