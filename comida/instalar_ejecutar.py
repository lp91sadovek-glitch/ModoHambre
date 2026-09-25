import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REQUIREMENTS = BASE_DIR / "requirements.txt"
APP = BASE_DIR / "app.py"

ADMIN_URL = "http://localhost:5000/admin.html"
CLIENT_URL = "http://localhost:5000"


def run(command):
    print(">>", " ".join(command))
    result = subprocess.run(command, cwd=str(BASE_DIR))
    if result.returncode != 0:
        print("ERROR: el comando anterior fallo.")
        input("Presiona ENTER para cerrar...")
        sys.exit(1)
    return result


def main():
    print("=" * 60)
    print("  MODO HAMBRE - Instalacion y puesta en marcha")
    print("=" * 60)

    print("\n[1/2] Instalando dependencias...")
    run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    print("Dependencias instaladas correctamente.\n")

    print("[2/2] Iniciando el servidor...")
    server = subprocess.Popen([sys.executable, str(APP)], cwd=str(BASE_DIR))
    time.sleep(3)

    open_browser = input("Abrir la pagina del cliente en el navegador? (s/n): ").strip().lower()
    if open_browser.startswith("s"):
        print("Abriendo", CLIENT_URL)
        webbrowser.open(CLIENT_URL)

    print("\nEl servidor esta corriendo.")
    print("  Pagina del cliente:", CLIENT_URL)
    print("  Panel de admin:   ", ADMIN_URL)
    print("\nPulsa Ctrl+C en esta ventana para detener el servidor.")
    try:
        server.wait()
    except KeyboardInterrupt:
        print("\nDeteniendo el servidor...")
        server.terminate()
        server.wait()

    input("Presiona ENTER para cerrar...")


if __name__ == "__main__":
    main()