# Configuracion de gunicorn, el programa que levanta la pagina en Render.
# gunicorn lee este archivo solo si arranca en esta carpeta ("gunicorn app:app").
# Hay una copia igual en la raiz del repositorio, por si arranca desde ahi.
#
# Por defecto gunicorn atiende de a UN pedido por vez: mientras el panel
# preguntaba por los pedidos nuevos, el boton "Recibido" esperaba en la fila.
# Con hilos atiende varios a la vez.
#
# Un solo proceso a proposito: el menu y las fotos se guardan en la memoria del
# proceso, y con varios cada uno tendria su propia copia (y el plan gratis de
# Render tiene poca memoria).
workers = 1
threads = 8
worker_class = "gthread"
timeout = 60
