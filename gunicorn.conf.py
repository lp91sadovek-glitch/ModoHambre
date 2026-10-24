# Configuracion de gunicorn, el programa que levanta la pagina en Render.
#
# gunicorn busca este archivo en la carpeta DESDE DONDE ARRANCA. Render hoy
# arranca desde comida/ y usa la copia de ahi (comida/gunicorn.conf.py); esta
# queda por si algun dia arranca desde la raiz. Si se cambia algo, cambiarlo en
# los dos.
#
# Sin esto gunicorn atiende de a UN pedido por vez, y mientras el panel
# preguntaba por los pedidos nuevos, los botones esperaban en la fila.
#
# Un solo proceso a proposito: el menu y las fotos se guardan en la memoria del
# proceso, y con varios cada uno tendria su propia copia (y el plan gratis de
# Render tiene poca memoria).
workers = 1
threads = 8
worker_class = "gthread"
timeout = 60
