# Configuracion de gunicorn, el programa que levanta la pagina en Render.
#
# gunicorn busca este archivo en la carpeta DESDE DONDE ARRANCA, antes de entrar
# a la carpeta de la pagina. Render arranca desde aca (la raiz del repositorio),
# por eso tiene que estar en este lugar y no adentro de comida/.
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
