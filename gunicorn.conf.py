# Configuracion de gunicorn para Render (la misma que comida/gunicorn.conf.py).
#
# gunicorn busca este archivo en la carpeta DESDE DONDE ARRANCA, antes de entrar
# a la carpeta de la pagina. Render arranca desde aca (la raiz del repositorio),
# por eso tiene que estar en este lugar. Si se cambia algo, cambiarlo en los dos.
#
# Sin esto gunicorn atiende de a UN pedido por vez, y mientras el panel
# preguntaba por los pedidos nuevos, los botones esperaban en la fila.
workers = 1
threads = 8
worker_class = "gthread"
timeout = 60
