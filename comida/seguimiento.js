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
    listo_domicilio: { titulo: '🛵 ¡Tu pedido va en camino!', cuerpo: 'Está listo y lo estamos llevando a tu domicilio.' },
    entregado_local: { titulo: '🎉 ¡Retiraste tu pedido!', cuerpo: '¡Que lo disfrutes!' },
    entregado_domicilio: { titulo: '🎉 ¡Tu pedido fue entregado!', cuerpo: '¡Que lo disfrutes!' },
    cancelado: { titulo: '❌ Pedido cancelado', cuerpo: 'Cancelaste este pedido. No se va a preparar.' }
  };

  /* Un pedido está activo hasta que el local lo marca como entregado o
     retirado. Mientras está activo se sigue preguntando el estado, se ve la
     tarjeta de abajo y el botón "Mi pedido" de arriba. */
  function activo(pedido) {
    return pedido.estado !== 'entregado' && pedido.estado !== 'cancelado';
  }

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
    if (pedido.estado === 'cancelado') return TEXTOS.cancelado;
    if (pedido.estado === 'entregado') {
      return TEXTOS[pedido.envio === 'domicilio' ? 'entregado_domicilio' : 'entregado_local'];
    }
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

  /* El permiso se pide en el mismo toque de "Confirmar pedido" (el navegador
     solo deja preguntarlo cuando la persona toca algo). Antes había que tocar
     además un botón aparte en la tarjeta, y si no se tocaba el aviso nunca
     llegaba. Devuelve la promesa del permiso para no tener que esperarla. */
  var permisoPedido = null;

  function pedirPermiso() {
    if (!puedeAvisarCerrada()) return null;
    if (Notification.permission === 'granted') {
      permisoPedido = Promise.resolve('granted');
    } else {
      try {
        permisoPedido = Notification.requestPermission();
      } catch (error) {
        permisoPedido = null;
      }
    }
    return permisoPedido;
  }

  /* Anota este celular para que le lleguen los avisos del pedido. Si falla,
     queda escrito por qué en la tarjeta (antes fallaba sin decir nada). */
  async function suscribir(pedido) {
    try {
      var permiso = await (permisoPedido || Notification.requestPermission());
      if (permiso !== 'granted') {
        throw new Error(permiso === 'denied' ? 'bloqueado' : 'sin permiso');
      }
      var registro = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      var respuesta = await fetch(API_PEDIDOS + '/api/avisos/clave');
      if (!respuesta.ok) throw new Error('el servidor no tiene avisos');
      var clave = (await respuesta.json()).clave;
      var suscripcion = await registro.pushManager.getSubscription() ||
        await registro.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: claveABytes(clave) });
      var guardada = await fetch(API_PEDIDOS + '/api/seguimiento/' + pedido.id + '/avisos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ t: pedido.t, suscripcion: suscripcion.toJSON() })
      });
      if (!guardada.ok) throw new Error('el servidor no la guardó');
      marcar(pedido.id, { avisos: true, errorAvisos: '' });
    } catch (error) {
      console.warn('No se pudieron activar los avisos', error);
      var motivo = error && error.message === 'bloqueado'
        ? 'Las notificaciones están bloqueadas para esta página. Activalas desde el candadito de la barra de direcciones.'
        : error && error.message === 'sin permiso'
          ? 'No diste permiso para las notificaciones.'
          : 'No se pudieron activar las notificaciones en este navegador.';
      marcar(pedido.id, { errorAvisos: motivo });
    }
    dibujar();
  }

  function activarAvisos(pedido, boton) {
    boton.disabled = true;
    boton.textContent = 'Activando…';
    permisoPedido = null;
    suscribir(pedido);
  }

  /* ---------- el aviso en pantalla ----------
     Lo principal: un cartel grande en el medio de la página, con un sonido
     corto y vibración en el celular. Si el cliente está en otra pestaña, el
     título de la pestaña parpadea hasta que vuelve. */

  var tituloOriginal = document.title;
  var parpadeo = null;

  function sonar() {
    try {
      var audio = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.18].forEach(function (cuando, i) {
        var nota = audio.createOscillator();
        var volumen = audio.createGain();
        nota.connect(volumen);
        volumen.connect(audio.destination);
        nota.frequency.value = i === 0 ? 880 : 1175;
        volumen.gain.setValueAtTime(0.18, audio.currentTime + cuando);
        volumen.gain.exponentialRampToValueAtTime(0.01, audio.currentTime + cuando + 0.35);
        nota.start(audio.currentTime + cuando);
        nota.stop(audio.currentTime + cuando + 0.35);
      });
    } catch (error) {}
    if (navigator.vibrate) {
      try { navigator.vibrate([200, 100, 200]); } catch (error) {}
    }
  }

  function parpadearTitulo(texto) {
    clearInterval(parpadeo);
    var alternar = false;
    parpadeo = setInterval(function () {
      document.title = (alternar = !alternar) ? '🔔 ' + texto : tituloOriginal;
    }, 1000);
  }

  function dejarDeParpadear() {
    clearInterval(parpadeo);
    parpadeo = null;
    document.title = tituloOriginal;
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) dejarDeParpadear();
  });

  function cartelEnPantalla(pedido, texto) {
    // Solo se saca un cartel anterior, no la pantalla de seguimiento si
    // estaba abierta (el cartel queda arriba de ella).
    var viejo = document.querySelector('.seg-aviso-fondo');
    if (viejo) viejo.remove();
    var fondo = document.createElement('div');
    fondo.className = 'seg-cartel-fondo seg-aviso-fondo';
    fondo.innerHTML =
      '<div class="seg-cartel' + (pedido.estado === 'listo' ? ' seg-cartel-listo' : '') + '"' +
      ' role="alertdialog" aria-modal="true" aria-labelledby="seg-cartel-titulo">' +
        '<p class="seg-cartel-numero">Pedido #' + pedido.id + '</p>' +
        '<p class="seg-cartel-titulo" id="seg-cartel-titulo">' + texto.titulo + '</p>' +
        '<p class="seg-cartel-cuerpo">' + texto.cuerpo + '</p>' +
        '<button class="seg-cartel-boton" type="button">¡Genial!</button>' +
      '</div>';
    document.body.appendChild(fondo);
    var cerrar = function () {
      fondo.remove();
      dejarDeParpadear();
    };
    fondo.querySelector('.seg-cartel-boton').addEventListener('click', cerrar);
    fondo.addEventListener('click', function (evento) {
      if (evento.target === fondo) cerrar();
    });
    fondo.querySelector('.seg-cartel-boton').focus();
  }

  /* Además, si el cliente dio permiso, también se muestra la notificación
     del celular (misma etiqueta que la del servidor, así no se duplica si
     llegan las dos). */
  function avisarAhora(pedido) {
    var texto = textoDe(pedido);
    cartelEnPantalla(pedido, texto);
    sonar();
    if (document.hidden) parpadearTitulo(texto.titulo.replace(/^\S+\s/, ''));
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
    var visibles = leer().filter(function (p) { return !p.oculto && activo(p); });
    mostrarBotonArriba();
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
    var ultimoPaso = pedido.envio === 'domicilio' ? 'En camino' : 'Listo para retirar';

    var botonAvisos = '';
    if (!listo && pedido.avisos) {
      botonAvisos = '<p class="seg-nota">🔔 Te vamos a avisar aunque cierres la página.</p>';
    } else if (!listo && puedeAvisarCerrada()) {
      botonAvisos =
        (pedido.errorAvisos ? '<p class="seg-nota seg-error">' + pedido.errorAvisos + '</p>' : '') +
        '<button class="seg-avisos" type="button" data-accion="avisos">' +
        (pedido.errorAvisos ? '🔔 Reintentar avisos' : '🔔 Avisarme aunque cierre la página') + '</button>';
    } else if (!listo && 'Notification' in window && Notification.permission === 'denied') {
      botonAvisos = '<p class="seg-nota seg-error">Las notificaciones están bloqueadas para esta página. ' +
        'Activalas desde el candadito de la barra de direcciones.</p>';
    } else if (!listo) {
      // iPhone (fuera de la pantalla de inicio) y navegadores viejos
      botonAvisos = '<p class="seg-nota">Dejá esta página abierta y te avisamos acá. ' +
        'En iPhone, agregala a la pantalla de inicio para recibir notificaciones.</p>';
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
      '<div class="seg-acciones">' +
        '<button class="seg-ver" type="button" data-accion="detalle">Ver seguimiento ›</button>' +
        opcionCancelar(pedido) +
      '</div>' +
      botonAvisos;
    caja.dataset.id = pedido.id;
    if (detalleAbierto) dibujarDetalle();
  }

  /* ---------- cancelar el pedido ----------
     Solo mientras el local no lo recibió: después ya se está preparando, y en
     vez del botón aparece un link para hablar con el local por WhatsApp. */

  var WHATSAPP_LOCAL = '5492215012289';

  function opcionCancelar(pedido) {
    if (pedido.estado === 'nuevo') {
      return '<button class="seg-cancelar" type="button" data-accion="cancelar">Cancelar pedido</button>';
    }
    if (pedido.estado === 'recibido' || pedido.estado === 'listo') {
      var texto = encodeURIComponent('Hola, quiero cancelar el pedido #' + pedido.id);
      return '<a class="seg-cancelar-ws" href="https://wa.me/' + WHATSAPP_LOCAL + '?text=' + texto +
        '" target="_blank" rel="noopener">¿Cancelar? Escribinos por WhatsApp</a>';
    }
    return '';
  }

  async function cancelar(pedido) {
    if (!confirm('¿Cancelar el pedido #' + pedido.id + '?\n\nEl local no lo va a preparar.')) return;
    try {
      var respuesta = await fetch(API_PEDIDOS + '/api/seguimiento/' + pedido.id + '/cancelar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ t: pedido.t })
      });
      var datos = await respuesta.json().catch(function () { return {}; });
      if (respuesta.ok) {
        var detalle = Object.assign({}, pedido.detalle || {}, { cancelado: Math.floor(Date.now() / 1000) });
        marcar(pedido.id, { estado: 'cancelado', detalle: detalle });
        if (typeof mostrarToast === 'function') mostrarToast('Cancelaste el pedido #' + pedido.id + '.');
      } else {
        // el local lo recibió justo antes: se avisa y se actualiza el estado
        if (typeof mostrarToast === 'function') {
          mostrarToast(datos.error || 'No se pudo cancelar el pedido. Probá de nuevo.', 'error');
        }
        await consultar(pedido);
      }
    } catch (error) {
      if (typeof mostrarToast === 'function') mostrarToast('No se pudo cancelar. Revisá tu internet.', 'error');
    }
    dibujar();
  }

  /* ---------- la pantalla de seguimiento ----------
     Como en las apps de delivery: una línea de tiempo con la hora de cada
     paso, y abajo qué se pidió, el total y la entrega. Se abre desde la
     tarjetita ("Ver seguimiento") o desde "Mis pedidos" en el menú. */

  var detalleAbierto = null;   // id del pedido que se está mirando
  var fondoDetalle = null;

  function esc(valor) {
    return String(valor == null ? '' : valor)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function hora(segundos) {
    if (!segundos) return '';
    var fecha = new Date(segundos * 1000);
    return fecha.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  }

  function precio(valor) {
    return '$' + Number(valor || 0).toLocaleString('es-AR');
  }

  function pasoLinea(icono, titulo, detalle, cuando, hecho, actual) {
    return '<li class="seg-linea-paso' + (hecho ? ' hecho' : '') + (actual ? ' actual' : '') + '">' +
      '<span class="seg-linea-icono">' + icono + '</span>' +
      '<div class="seg-linea-texto">' +
        '<p class="seg-linea-titulo">' + titulo + (cuando ? '<span class="seg-linea-hora">' + cuando + '</span>' : '') + '</p>' +
        '<p class="seg-linea-detalle">' + detalle + '</p>' +
      '</div>' +
    '</li>';
  }

  function dibujarDetalle() {
    if (!fondoDetalle) return;
    var lista = leer();
    var panel = fondoDetalle.querySelector('.seg-detalle-contenido');

    if (!lista.length) {
      panel.innerHTML =
        '<p class="seg-detalle-vacio">📦<br>Todavía no hiciste pedidos por la app desde este dispositivo.</p>' +
        '<a class="seg-cartel-boton seg-detalle-pedir" href="platos.html">Pedir comida</a>';
      return;
    }

    var pedido = lista.find(function (p) { return p.id === detalleAbierto; }) || lista[lista.length - 1];
    detalleAbierto = pedido.id;
    var d = pedido.detalle || {};
    var texto = textoDe(pedido);
    var entregado = pedido.estado === 'entregado';
    var listo = pedido.estado === 'listo' || entregado;
    var recibido = pedido.estado === 'recibido' || listo;
    var aDomicilio = pedido.envio === 'domicilio';

    var otros = lista.length > 1
      ? '<div class="seg-detalle-otros">' + lista.slice().reverse().map(function (p) {
          return '<button type="button" data-ver="' + p.id + '"' + (p.id === pedido.id ? ' class="activo"' : '') + '>#' + p.id + '</button>';
        }).join('') + '</div>'
      : '';

    var platos = (d.items || []).map(function (item) {
      var cantidad = item.quantity || 1;
      // el precio de cada uno abajo, y a la derecha lo que suman
      return '<li><span>' + esc(cantidad) + ' × ' + esc(item.name) +
          '<small class="seg-unitario">' + precio(item.price) + ' c/u</small></span>' +
        '<span>' + precio((item.price || 0) * cantidad) + '</span></li>';
    }).join('');

    var direccion = aDomicilio && d.calle
      ? esc(d.calle) + (d.numero ? ' N° ' + esc(d.numero) : '') + (d.entre ? ' (entre ' + esc(d.entre) + ')' : '')
      : '';

    panel.innerHTML =
      otros +
      '<p class="seg-cartel-numero">Pedido #' + pedido.id + '</p>' +
      '<p class="seg-detalle-estado">' + texto.titulo + '</p>' +
      '<p class="seg-cartel-cuerpo">' + texto.cuerpo + '</p>' +
      (pedido.estado === 'cancelado' ? '' : '<div class="seg-detalle-cancelar">' + opcionCancelar(pedido) + '</div>') +
      '<ol class="seg-linea">' +
        (pedido.estado === 'cancelado'
          ? pasoLinea('🧾', 'Pedido enviado', 'Le llegó al local.', hora(d.enviado), true, false) +
            pasoLinea('❌', 'Cancelado', 'Lo cancelaste antes de que el local lo prepare.', hora(d.cancelado), true, true)
          : '') +
        (pedido.estado === 'cancelado' ? '' :
        pasoLinea('🧾', 'Pedido enviado', 'Le llegó al local.', hora(d.enviado), true, !recibido) +
        pasoLinea('👨‍🍳', 'Pedido recibido', 'El local lo está preparando.', hora(d.recibido), recibido, recibido && !listo) +
        (aDomicilio
          ? pasoLinea('🛵', 'En camino', 'Está listo y lo estamos llevando a tu domicilio.', hora(d.listo), listo, listo && !entregado) +
            pasoLinea('🎉', 'Entregado', 'Tu pedido llegó. ¡Que lo disfrutes!', hora(d.entregado), entregado, entregado)
          : pasoLinea('🛍️', 'Listo para retirar', 'Ya podés pasar a buscarlo por el local.', hora(d.listo), listo, listo && !entregado) +
            pasoLinea('🎉', 'Retirado', 'Ya lo retiraste. ¡Que lo disfrutes!', hora(d.entregado), entregado, entregado))) +
      '</ol>' +
      (platos
        ? '<div class="seg-detalle-caja">' +
            '<p class="seg-detalle-subtitulo">Tu pedido</p>' +
            '<ul class="seg-detalle-platos">' + platos + '</ul>' +
            '<p class="seg-detalle-total"><span>Total</span><span>' + precio(d.total) + '</span></p>' +
          '</div>'
        : '') +
      '<div class="seg-detalle-caja">' +
        '<p class="seg-detalle-subtitulo">Entrega</p>' +
        '<p>' + (aDomicilio ? '🛵 A domicilio' + (direccion ? '<br>📌 ' + direccion : '') : '🏪 Retiro en el local') + '</p>' +
      '</div>';
  }

  function cerrarDetalle() {
    if (fondoDetalle) fondoDetalle.remove();
    fondoDetalle = null;
    detalleAbierto = null;
  }

  function abrirDetalle(id) {
    cerrarDetalle();
    detalleAbierto = id || null;
    fondoDetalle = document.createElement('div');
    fondoDetalle.className = 'seg-cartel-fondo seg-detalle-fondo';
    fondoDetalle.innerHTML =
      '<div class="seg-detalle" role="dialog" aria-modal="true" aria-label="Seguimiento del pedido">' +
        '<div class="seg-detalle-cabecera">' +
          '<p>📦 Mis pedidos</p>' +
          '<button type="button" class="seg-detalle-cerrar" aria-label="Cerrar">×</button>' +
        '</div>' +
        '<div class="seg-detalle-contenido"></div>' +
      '</div>';
    document.body.appendChild(fondoDetalle);
    fondoDetalle.addEventListener('click', function (evento) {
      if (evento.target === fondoDetalle || evento.target.closest('.seg-detalle-cerrar')) {
        cerrarDetalle();
        return;
      }
      var botonCancelar = evento.target.closest('[data-accion="cancelar"]');
      if (botonCancelar) {
        var elegido = leer().find(function (p) { return p.id === detalleAbierto; });
        if (elegido) cancelar(elegido);
        return;
      }
      var otro = evento.target.closest('[data-ver]');
      if (otro) {
        detalleAbierto = Number(otro.dataset.ver);
        dibujarDetalle();
        consultarAhora(detalleAbierto);
      }
    });
    dibujarDetalle();
    if (detalleAbierto) consultarAhora(detalleAbierto);
  }

  /* Al abrir la pantalla se pregunta enseguida (también por los pedidos ya
     listos, que no se siguen consultando), así las horas están al día. */
  async function consultarAhora(id) {
    var pedido = leer().find(function (p) { return p.id === id; });
    if (!pedido) return;
    await consultar(pedido);
    dibujar();
  }

  document.addEventListener('keydown', function (evento) {
    if (evento.key === 'Escape' && fondoDetalle) cerrarDetalle();
  });

  /* "Mis pedidos" del menú y el botón de arriba (todo lo que tenga
     data-mis-pedidos). Abre el pedido activo más nuevo, o el último. */
  function pedidoParaAbrir() {
    var lista = leer();
    var activos = lista.filter(activo);
    var elegido = activos.length ? activos[activos.length - 1] : lista[lista.length - 1];
    return elegido ? elegido.id : null;
  }

  document.addEventListener('click', function (evento) {
    var link = evento.target.closest('[data-mis-pedidos]');
    if (!link) return;
    evento.preventDefault();
    if (typeof toggleNavOverlay === 'function') toggleNavOverlay(false);
    abrirDetalle(pedidoParaAbrir());
  });

  /* El botón "📦 Mi pedido" de la barra de arriba, entre el carrito y el
     menú. Solo aparece mientras hay un pedido activo: cuando el local lo
     marca como entregado o retirado, desaparece. */
  var botonArriba = null;

  function mostrarBotonArriba() {
    var hayActivo = leer().some(activo);
    if (!botonArriba) {
      var menu = document.getElementById('menu-toggle');
      if (!menu || !menu.parentNode) return;
      botonArriba = document.createElement('button');
      botonArriba.type = 'button';
      botonArriba.className = 'action-btn boton-mi-pedido';
      botonArriba.setAttribute('data-mis-pedidos', '');
      botonArriba.setAttribute('aria-label', 'Ver el estado de mi pedido');
      // en el celular se ve solo el 📦 (la barra ya tiene otros botones)
      botonArriba.innerHTML = '📦<span class="mi-pedido-texto"> Mi pedido</span>';
      menu.parentNode.insertBefore(botonArriba, menu);
    }
    botonArriba.hidden = !hayActivo;
  }

  function alTocar(evento) {
    var boton = evento.target.closest('[data-accion]');
    if (!boton) return;
    var id = Number(caja.dataset.id);
    var pedido = leer().find(function (p) { return p.id === id; });
    if (!pedido) return;
    if (boton.dataset.accion === 'cerrar') {
      // Se esconde la tarjeta (vuelve si cambia el estado). El pedido sigue
      // en "Mis pedidos" hasta 6 horas después.
      marcar(id, { oculto: true });
      dibujar();
    } else if (boton.dataset.accion === 'avisos') {
      activarAvisos(pedido, boton);
    } else if (boton.dataset.accion === 'cancelar') {
      cancelar(pedido);
    } else if (boton.dataset.accion === 'detalle') {
      abrirDetalle(id);
    }
  }

  /* ---------- preguntar el estado ---------- */

  /* Pregunta el estado de un pedido y guarda el detalle (horas, platos,
     total). Si cambió el estado, avisa. */
  async function consultar(pedido) {
    try {
      var respuesta = await fetch(API_PEDIDOS + '/api/seguimiento/' + pedido.id +
        '?t=' + encodeURIComponent(pedido.t), { cache: 'no-store' });
      if (respuesta.status === 404) {
        // El pedido ya no existe: se deja de seguir.
        guardar(leer().filter(function (p) { return p.id !== pedido.id; }));
        return;
      }
      if (!respuesta.ok) return;
      var datos = await respuesta.json();
      var cambios = { detalle: datos, envio: datos.envio };
      if (datos.estado !== pedido.estado) {
        // Cambió: se vuelve a mostrar aunque el cliente la haya ocultado.
        cambios.estado = datos.estado;
        cambios.oculto = false;
      }
      marcar(pedido.id, cambios);
      if (cambios.estado && cambios.estado !== 'entregado') avisarAhora(Object.assign({}, pedido, datos));
    } catch (error) {
      // sin internet un momento: se reintenta en la próxima vuelta
    }
  }

  async function actualizar() {
    var pendientes = leer().filter(activo);
    for (var i = 0; i < pendientes.length; i++) {
      await consultar(pendientes[i]);
    }
    dibujar();
    if (!leer().some(activo)) {
      clearInterval(reloj);
      reloj = null;
    }
  }

  function seguir() {
    dibujar();
    // /#mis-pedidos (lo abre la notificación al tocarla) abre la pantalla
    if (location.hash === '#mis-pedidos') {
      abrirDetalle(pedidoParaAbrir());
    }
    if (!reloj && leer().some(activo)) {
      reloj = setInterval(actualizar, CADA_CUANTO);
      actualizar();
    }
  }

  /* La llama platos-cart.js cuando el pedido se guardó en el servidor. Si el
     cliente dejó marcado "avisarme", el celular se anota solo. */
  function agregar(respuesta, quiereAvisos) {
    if (!respuesta || !respuesta.order_id || !respuesta.seguimiento) return;
    var pedido = {
      id: respuesta.order_id,
      t: respuesta.seguimiento,
      envio: respuesta.envio || 'local',
      estado: 'nuevo',
      creado: Date.now()
    };
    var lista = leer();
    lista.push(pedido);
    guardar(lista);
    seguir();
    if (quiereAvisos && puedeAvisarCerrada()) suscribir(pedido);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', seguir);
  } else {
    seguir();
  }

  /* Chrome frena las pestañas que no se están mirando (pregunta como mucho
     una vez por minuto). Al volver a la pestaña se pregunta enseguida, así el
     aviso aparece apenas el cliente mira la página. */
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && reloj) actualizar();
  });

  return { agregar: agregar, pedirPermiso: pedirPermiso, puedeAvisar: puedeAvisarCerrada };
})();
