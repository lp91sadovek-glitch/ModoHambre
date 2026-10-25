/* AVISOS DEL PEDIDO — MODO HAMBRE
 *
 * Este archivo lo instala el navegador del cliente cuando acepta "avisarme
 * aunque cierre la página". Queda escuchando aunque la página esté cerrada, y
 * cuando el local toca "Recibir" o "Listo" en el panel, el servidor le manda
 * el aviso y acá se muestra como una notificación del celular.
 *
 * Tiene que estar en la raíz del sitio (/sw.js) para poder avisar de cualquier
 * página.
 */

self.addEventListener('push', function (evento) {
  var datos = {};
  try {
    datos = evento.data ? evento.data.json() : {};
  } catch (error) {}

  var titulo = datos.titulo || 'Modo Hambre';
  evento.waitUntil(
    self.registration.showNotification(titulo, {
      body: datos.cuerpo || 'Tu pedido cambió de estado.',
      icon: '/imagenes/modo-hambre.webp',
      badge: '/imagenes/modo-hambre.webp',
      // misma etiqueta = la notificación nueva reemplaza a la vieja del mismo
      // pedido, en vez de amontonarse
      tag: datos.etiqueta || 'pedido',
      renotify: true
    })
  );
});

/* Tocar la notificación abre la página (o la trae al frente si ya estaba). */
self.addEventListener('notificationclick', function (evento) {
  evento.notification.close();
  evento.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (ventanas) {
      for (var i = 0; i < ventanas.length; i++) {
        if ('focus' in ventanas[i]) return ventanas[i].focus();
      }
      return self.clients.openWindow('/#mis-pedidos');
    })
  );
});
