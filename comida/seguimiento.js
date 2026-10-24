/* SEGUIMIENTO DEL PEDIDO — MODO HAMBRE
 *
 * Después de "Enviar por la app", el cliente ve una tarjetita abajo con el
 * estado de su pedido: Enviado → Recibido → Listo (o En camino, si es a
 * domicilio). Se actualiza sola mientras la página esté abierta, en cualquier
 * página del sitio, y avisa cuando cambia.
 *
 * Además ofrece "Avisarme aunque cierre la página": con eso le llega una
 * notificación del celular cuando el local toca "Recibir" o "Listo" (anda en
 * Android y en computadoras; en iPhone solo si la página está agregada a la
 * pantalla de inicio, así que ahí el botón ni aparece).
 *
 * Cada pedido se guarda en el navegador con su código de seguimiento: sin ese
 * código el servidor no muestra nada, así nadie puede ver un pedido ajeno.
 */

var SeguimientoPedidos = (function () {
  'use strict';

  var CLAVE = 'pedidos-seguidos-modo-hambre';
  var CADA_CUANTO = 8000;              // cada cuánto se pregunta el estado
  var DURACION = 6 * 60 * 60 * 1000;   // un pedido se sigue como mucho 6 horas

  /* Mismos textos que manda el servidor en la notificación (app.py). */
  var TEXTOS = {
    nuevo: { titulo: 'Pedido enviado', cuerpo: 'Esperando que el local lo reciba.' },
    recibido: { titulo: '🍽️ ¡Recibimos tu pedido!', cuerpo: 'Ya lo estamos preparando.' },
    listo_local: { titulo: '✅ ¡Tu pedido está listo!', cuerpo: 'Ya podés pasar a retirarlo por el local.' },
    listo_domicilio: { titulo: '🛵 ¡Tu pedido va en camino!', cuerpo: 'Está listo y lo estamos llevando a tu domicilio.' }
  };

  var reloj = null;
  var caja = null;

  /* ---------- lo guardado en el navegador ---------- */

  function leer() {
    try {
      var lista = JSON.parse(localStorage.getItem(CLAVE));
      if (!Array.isArray(lista)) return [];
      var ahora = Date.now();
      return lista.filter(function (p) {
        return p && p.id && p.t && ahora - (p.creado || 0) < DURACION;
      });
    } catch (error) {
      return [];
    }
  }

  function guardar(lista) {
    try {
      localStorage.setItem(CLAVE, JSON.stringify(lista.slice(-5)));
    } catch (error) {}
  }

  function textoDe(pedido) {
    if (pedido.estado === 'listo') {
      return TEXTOS[pedido.envio === 'domicilio' ? 'listo_domicilio' : 'listo_local'];
    }
    return TEXTOS[pedido.estado] || TEXTOS.nuevo;
  }

  /* ---------- avisos del celular ---------- */

  function puedeAvisarCerrada() {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window &&
      Notification.permission !== 'denied';
  }

  // Convierte la clave del servidor (base64url) al formato que pide el navegador.
  function claveABytes(clave) {
    var relleno = '='.repeat((4 - clave.length % 4) % 4);
    var crudo = atob((clave + relleno).replace(/-/g, '+').replace(/_/g, '/'));
    var bytes = new Uint8Array(crudo.length);
    for (var i = 0; i < crudo.length; i++) bytes[i] = crudo.charCodeAt(i);
    return bytes;
  }

  async function activarAvisos(pedido, boton) {
    boton.disabled = true;
    boton.textContent = 'Activando…';
    try {
      var permiso = await Notification.requestPermission();
      if (permiso !== 'granted') throw new Error('sin permiso');
      var registro = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      var respuesta = await fetch(API_PEDIDOS + '/api/avisos/clave');
      if (!respuesta.ok) throw new Error('sin clave');
      var clave = (await respuesta.json()).clave;
      var suscripcion = await registro.pushManager.getSubscription() ||
        await registro.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: claveABytes(clave) });
      var guardada = await fetch(API_PEDIDOS + '/api/seguimiento/' + pedido.id + '/avisos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ t: pedido.t, suscripcion: suscripcion.toJSON() })
      });
      if (!guardada.ok) throw new Error('no se guardó');
      marcar(pedido.id, { avisos: true });
      dibujar();
    } catch (error) {
      console.warn('No se pudieron activar los avisos', error);
      boton.disabled = false;
      boton.textContent = Notification.permission === 'denied'
        ? 'Los avisos están bloqueados en el navegador'
        : 'No se pudo. Tocá para reintentar';
    }
  }

  /* Con la página abierta: si el cliente dio permiso, también se muestra la
     notificación del celular (misma etiqueta que la del servidor, así no se
     duplica si llegan las dos). */
  function avisarAhora(pedido) {
    var texto = textoDe(pedido);
    if (typeof mostrarToast === 'function') {
      mostrarToast(texto.titulo + ' ' + texto.cuerpo);
    }
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    var opciones = {
      body: 'Pedido #' + pedido.id + ': ' + texto.cuerpo,
      icon: '/imagenes/modo-hambre.webp',
      tag: 'pedido-' + pedido.id
    };
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistration().then(function (registro) {
        if (registro) registro.showNotification(texto.titulo, opciones);
        else new Notification(texto.titulo, opciones);
      }).catch(function () {});
    } else {
      try { new Notification(texto.titulo, opciones); } catch (error) {}
    }
  }

  /* ---------- la tarjetita ---------- */

  function marcar(id, cambios) {
    var lista = leer();
    lista.forEach(function (p) {
      if (p.id === id) Object.assign(p, cambios);
    });
    guardar(lista);
  }

  function pasoHTML(nombre, hecho, actual) {
    return '<li class="seg-paso' + (hecho ? ' hecho' : '') + (actual ? ' actual' : '') + '">' +
      '<span class="seg-punto"></span>' + nombre + '</li>';
  }

  function dibujar() {
    var visibles = leer().filter(function (p) { return !p.oculto; });
    if (!caja) {
      caja = document.createElement('div');
      caja.className = 'seguimiento';
      caja.setAttribute('role', 'status');
      caja.setAttribute('aria-live', 'polite');
      document.body.appendChild(caja);
      caja.addEventListener('click', alTocar);
    }
    if (!visibles.length) {
      caja.hidden = true;
      return;
    }
    // Se muestra el pedido más nuevo (casi siempre hay uno solo).
    var pedido = visibles[visibles.length - 1];
    var texto = textoDe(pedido);
    var recibido = pedido.estado === 'recibido' || pedido.estado === 'listo';
    var listo = pedido.estado === 'listo';
    var ultimoPaso = pedido.envio === 'domicilio' ? 'En camino' : 'Listo';

    var botonAvisos = '';
    if (!listo && !pedido.avisos && puedeAvisarCerrada()) {
      botonAvisos = '<button class="seg-avisos" type="button" data-accion="avisos">🔔 Avisarme aunque cierre la página</button>';
    } else if (!listo && pedido.avisos) {
      botonAvisos = '<p class="seg-nota">🔔 Te vamos a avisar aunque cierres la página.</p>';
    }

    caja.hidden = false;
    caja.className = 'seguimiento' + (listo ? ' seguimiento-listo' : '');
    caja.innerHTML =
      '<button class="seg-cerrar" type="button" data-accion="cerrar" aria-label="Ocultar">×</button>' +
      '<p class="seg-numero">Pedido #' + pedido.id + '</p>' +
      '<p class="seg-titulo">' + texto.titulo + '</p>' +
      '<p class="seg-cuerpo">' + texto.cuerpo + '</p>' +
      '<ol class="seg-pasos">' +
        pasoHTML('Enviado', true, !recibido) +
        pasoHTML('Recibido', recibido, recibido && !listo) +
        pasoHTML(ultimoPaso, listo, listo) +
      '</ol>' +
      botonAvisos;
    caja.dataset.id = pedido.id;
  }

  function alTocar(evento) {
    var boton = evento.target.closest('[data-accion]');
    if (!boton) return;
    var id = Number(caja.dataset.id);
    var pedido = leer().find(function (p) { return p.id === id; });
    if (!pedido) return;
    if (boton.dataset.accion === 'cerrar') {
      // Listo: se deja de seguir. Si no, se esconde hasta el próximo cambio.
      if (pedido.estado === 'listo') {
        guardar(leer().filter(function (p) { return p.id !== id; }));
      } else {
        marcar(id, { oculto: true });
      }
      dibujar();
    } else if (boton.dataset.accion === 'avisos') {
      activarAvisos(pedido, boton);
    }
  }

  /* ---------- preguntar el estado ---------- */

  async function actualizar() {
    var pendientes = leer().filter(function (p) { return p.estado !== 'listo'; });
    for (var i = 0; i < pendientes.length; i++) {
      var pedido = pendientes[i];
      try {
        var respuesta = await fetch(API_PEDIDOS + '/api/seguimiento/' + pedido.id +
          '?t=' + encodeURIComponent(pedido.t), { cache: 'no-store' });
        if (respuesta.status === 404) {
          // El pedido ya no existe: se deja de seguir.
          guardar(leer().filter(function (p) { return p.id !== pedido.id; }));
          continue;
        }
        if (!respuesta.ok) continue;
        var datos = await respuesta.json();
        if (datos.estado !== pedido.estado) {
          // Cambió: se vuelve a mostrar aunque el cliente la haya ocultado.
          marcar(pedido.id, { estado: datos.estado, envio: datos.envio, oculto: false });
          avisarAhora(Object.assign({}, pedido, datos));
        }
      } catch (error) {
        // sin internet un momento: se reintenta en la próxima vuelta
      }
    }
    dibujar();
    if (!leer().some(function (p) { return p.estado !== 'listo'; })) {
      clearInterval(reloj);
      reloj = null;
    }
  }

  function seguir() {
    dibujar();
    if (!reloj && leer().some(function (p) { return p.estado !== 'listo'; })) {
      reloj = setInterval(actualizar, CADA_CUANTO);
      actualizar();
    }
  }

  /* La llama platos-cart.js cuando el pedido se guardó en el servidor. */
  function agregar(respuesta) {
    if (!respuesta || !respuesta.order_id || !respuesta.seguimiento) return;
    var lista = leer();
    lista.push({
      id: respuesta.order_id,
      t: respuesta.seguimiento,
      envio: respuesta.envio || 'local',
      estado: 'nuevo',
      creado: Date.now()
    });
    guardar(lista);
    seguir();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', seguir);
  } else {
    seguir();
  }

  return { agregar: agregar };
})();
