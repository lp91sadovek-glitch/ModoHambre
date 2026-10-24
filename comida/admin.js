/* PANEL DE PEDIDOS — MODO HAMBRE */

/* El panel lee los pedidos del mismo sitio donde está abierto
   (modohambre.onrender.com). Los pedidos están guardados en Neon. */
var API = '';

var lista = document.getElementById('pedidos-lista');
var banner = document.getElementById('banner-nuevo');
var estadoConexion = document.getElementById('estado-conexion');
var contadorNuevos = document.getElementById('contador-nuevos');
var contadorRecibidos = document.getElementById('contador-recibidos');
var contadorListos = document.getElementById('contador-listos');
var ticketPrint = document.getElementById('ticket-print');

var pedidos = [];
var ultimoId = null;
var sinConexion = false;
var primeraCarga = true;

/* Todos los pedidos al host llevan la clave del panel. Si el servidor la
   rechaza (401) aparece la pantalla para escribirla de nuevo. */
async function pedir(url, opciones) {
  var config = opciones || {};
  config.headers = PanelClave.cabeceras(config.headers);
  var response = await fetch(url, config);
  if (response.status === 401) {
    PanelClave.errorDeClave();
  }
  return response;
}

function formatPrice(value) {
  return '$' + value.toLocaleString('es-AR');
}

function esc(valor) {
  return String(valor == null ? '' : valor)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function construirDatosCliente(pedido) {
  var cliente = pedido.cliente || {};
  var esDomicilio = pedido.envio === 'domicilio';
  var nombre = esc(cliente.nombre) + ' ' + esc(cliente.apellido);
  if (!nombre.trim()) nombre = 'Sin datos del cliente';

  var html =
    '<div class="pedido-cliente-fila">' +
      '<span class="pedido-cliente-ico">' + (esDomicilio ? '🛵' : '🏪') + '</span>' +
      '<div class="pedido-cliente-texto">' +
        '<strong>' + nombre.trim() + '</strong>' +
        '<span>' + (esDomicilio ? 'A domicilio' : 'Retiro en el local') + '</span>' +
      '</div>' +
    '</div>';

  if (cliente.telefono) {
    // El telefono "limpio" lo arma el servidor (sin +54, sin 0 ni 9): con
    // el 549 adelante es el formato que pide WhatsApp.
    var limpio = String(cliente.telefono_normalizado || '').replace(/\D/g, '');
    html +=
      '<div class="pedido-telefono">' +
        '<span>📞 ' + esc(cliente.telefono) + '</span>' +
        '<a href="tel:' + esc(limpio || cliente.telefono) + '">Llamar</a>' +
        (limpio
          ? '<a href="https://wa.me/549' + esc(limpio) + '" target="_blank" rel="noopener">WhatsApp</a>'
          : '') +
      '</div>';
  }

  if (cliente.telefono_normalizado) {
    var anteriores = Number(cliente.pedidos_anteriores) || 0;
    html += anteriores > 0
      ? '<div class="pedido-frecuente">⭐ Ya pidió ' + anteriores + (anteriores === 1 ? ' vez' : ' veces') + ' antes</div>'
      : '<div class="pedido-frecuente pedido-primera">🆕 Primer pedido</div>';
  }

  if (esDomicilio && (cliente.calle || cliente.numero || cliente.entre)) {
    html +=
      '<div class="pedido-direccion">' +
        '📌 ' + esc(cliente.calle) +
        (cliente.numero ? ' ' + esc(cliente.numero) : '') +
        (cliente.entre ? '<br>↕ Entre ' + esc(cliente.entre) : '') +
      '</div>';
  }

  return '<div class="pedido-cliente">' + html + '</div>';
}

function parseFecha(dbFecha) {
  if (!dbFecha) return null;
  return new Date(dbFecha.replace(' ', 'T') + 'Z');
}

function formatFecha(fecha) {
  if (!fecha) return '';
  var opcionesFecha = { day: '2-digit', month: '2-digit', year: 'numeric' };
  var opcionesHora = { hour: '2-digit', minute: '2-digit' };
  return fecha.toLocaleDateString('es-AR', opcionesFecha) + ' · ' +
         fecha.toLocaleTimeString('es-AR', opcionesHora);
}

function estadoTexto(estado) {
  if (estado === 'recibido') return 'Recibido';
  if (estado === 'listo') return 'Listo';
  return 'Nuevo';
}

function sonarNuevo() {
  try {
    var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    var osc = audioCtx.createOscillator();
    var gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.type = 'sine';
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.6);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.6);
  } catch (e) {}
}

/* =====================
   RENDERIZADO
   ===================== */

function construirFilaTabla(item) {
  var cantidad = item.quantity || 1;
  var nombre = item.name || 'Sin nombre';
  var precioUnitario = item.price || 0;
  var subtotal = precioUnitario * cantidad;
  return (
    '<tr>' +
      '<td class="cantidad-cell">' + esc(cantidad) + '</td>' +
      '<td>' + esc(nombre) + '</td>' +
      '<td class="precio-cell">' + formatPrice(precioUnitario) + '</td>' +
      '<td class="subtotal-cell">' + formatPrice(subtotal) + '</td>' +
    '</tr>'
  );
}

function construirCard(pedido) {
  var estado = pedido.estado || 'nuevo';
  var fecha = parseFecha(pedido.created_at);
  var filasItems = pedido.items.map(construirFilaTabla).join('');

  var botonRecibir = estado === 'nuevo'
    ? '<button class="boton-accion accion-recibir" data-accion="recibir" data-id="' + pedido.id + '">Recibir</button>'
    : '<button class="boton-accion accion-recibir" data-accion="recibir" data-id="' + pedido.id + '" disabled>Recibir</button>';

  var botonListo = estado === 'listo'
    ? '<button class="boton-accion accion-listo" data-accion="listo" data-id="' + pedido.id + '" disabled>Marcar listo</button>'
    : '<button class="boton-accion accion-listo" data-accion="listo" data-id="' + pedido.id + '">Marcar listo</button>';

  return (
    '<article class="pedido-card pedido-' + estado + '" data-pedido-id="' + pedido.id + '" data-estado="' + estado + '">' +
      '<div class="pedido-cabecera">' +
        '<span class="pedido-id">Pedido #' + pedido.id + '</span>' +
        '<span class="pedido-fecha">' + formatFecha(fecha) + '</span>' +
        '<span class="pedido-estado estado-' + estado + '">' + estadoTexto(estado) + '</span>' +
        '<button class="boton-accion accion-imprimir pedido-imprimir" data-accion="imprimir" data-id="' + pedido.id + '" aria-label="Imprimir ticket de pedido ' + pedido.id + '">🖨️</button>' +
        '<button class="boton-accion accion-eliminar pedido-eliminar" data-accion="eliminar" data-id="' + pedido.id + '" aria-label="Eliminar pedido ' + pedido.id + '">🗑️</button>' +
      '</div>' +
      '<table class="pedido-items">' +
        '<thead>' +
          '<tr><th>N°</th><th>Plato</th><th class="num">Precio</th><th class="num">Subtotal</th></tr>' +
        '</thead>' +
        '<tbody>' + filasItems + '</tbody>' +
      '</table>' +
      construirDatosCliente(pedido) +
      '<div class="pedido-pie">' +
        '<span class="pedido-total">Total: ' + formatPrice(pedido.total) + '</span>' +
        '<div class="pedido-acciones">' +
          botonRecibir + botonListo +
        '</div>' +
      '</div>' +
    '</article>'
  );
}

function renderizar() {
  var contadores = { nuevo: 0, recibido: 0, listo: 0 };
  pedidos.forEach(function (pedido) {
    var estado = pedido.estado || 'nuevo';
    if (contadores[estado] !== undefined) contadores[estado] += 1;
  });
  contadorNuevos.textContent = String(contadores.nuevo);
  contadorRecibidos.textContent = String(contadores.recibido);
  contadorListos.textContent = String(contadores.listo);

  var botonBorrar = document.getElementById('borrar-todos');
  if (botonBorrar) botonBorrar.disabled = pedidos.length === 0;

  if (pedidos.length === 0) {
    var tipoDeseado = sinConexion ? 'sin-conexion' : 'sin-pedidos';
    var vacioExistente = lista.querySelector('.pedido-vacio');
    if (!vacioExistente || vacioExistente.dataset.tipo !== tipoDeseado) {
      var mensajeSinConexion =
        'Revisá tu internet o aguardá unos segundos: si el sitio estaba dormido ' +
        'tarda hasta un minuto en despertar.';
      lista.innerHTML = sinConexion
        ? '<div class="pedido-vacio" data-tipo="sin-conexion">' +
            '<span class="pedido-vacio-icono">🔌</span>' +
            '<strong>Sin conexión con el servidor.</strong><br>' +
            mensajeSinConexion +
          '</div>'
        : '<div class="pedido-vacio" data-tipo="sin-pedidos">' +
            '<span class="pedido-vacio-icono">🛎️</span>' +
            'Aún no hay pedidos ingresados. Cuando un cliente haga un pedido, va a aparecer acá.' +
          '</div>';
    }
    return;
  }

  var vacio = lista.querySelector('.pedido-vacio');
  if (vacio) vacio.remove();

  var enPantalla = {};

  Array.prototype.slice.call(lista.querySelectorAll('.pedido-card')).forEach(function (card) {
    var id = Number(card.dataset.pedidoId);
    var pedido = pedidos.find(function (p) { return p.id === id; });

    if (!pedido) {
      card.remove();
      return;
    }

    enPantalla[id] = true;

    var estado = pedido.estado || 'nuevo';
    if (card.dataset.estado !== estado) {
      card.outerHTML = construirCard(pedido);
    }
  });

  var nuevos = pedidos.filter(function (pedido) {
    return !enPantalla[pedido.id];
  });

  if (nuevos.length > 0) {
    var fragmento = document.createDocumentFragment();
    nuevos.forEach(function (pedido) {
      var contenedor = document.createElement('div');
      contenedor.innerHTML = construirCard(pedido);
      var card = contenedor.firstElementChild;
      if (!primeraCarga) {
        card.classList.add('pedido-llegada');
      }
      fragmento.appendChild(card);
    });
    lista.insertBefore(fragmento, lista.firstChild);
  }

  primeraCarga = false;
}

/* =====================
   CARGAR PEDIDOS (polling)
   ===================== */

/* Los botones cambian la pantalla al instante, sin esperar al servidor (que
   está lejos y tarda). Mientras el servidor no confirma, el cambio queda
   anotado acá: id -> 'recibido' | 'listo' | 'fuera' (sacado de la pantalla).
   Así una actualización que llega en el medio no "deshace" lo que se tocó. */
var cambiosPendientes = {};
var pedidosDelServidor = [];

/* Sube cada vez que el servidor confirma un cambio. Una consulta que salió
   antes de eso trae datos viejos y se descarta. */
var versionCambios = 0;
var consultando = false;

function aplicarPendientes() {
  pedidos = pedidosDelServidor
    .filter(function (pedido) { return cambiosPendientes[pedido.id] !== 'fuera'; })
    .map(function (pedido) {
      var estado = cambiosPendientes[pedido.id];
      return estado ? Object.assign({}, pedido, { estado: estado }) : pedido;
    });
  renderizar();
}

async function cargarPedidos() {
  // Si la consulta anterior todavía no volvió, no se apila otra.
  if (consultando) return;
  consultando = true;
  var versionAlSalir = versionCambios;
  try {
    var response = await pedir(API + '/api/orders');
    if (!response.ok) throw new Error('Respuesta no válida');
    var datos = await response.json();
    if (versionAlSalir !== versionCambios) return;

    estadoConexion.textContent = 'Conectado · cada 4 segundos';
    estadoConexion.classList.add('ok');
    sinConexion = false;

    var hayNuevo = false;
    if (ultimoId !== null) {
      datos.forEach(function (pedido) {
        if (pedido.id > ultimoId && pedido.estado === 'nuevo') {
          hayNuevo = true;
        }
      });
    }

    pedidosDelServidor = datos;
    if (datos.length > 0) ultimoId = Math.max(ultimoId || 0, datos[0].id);
    aplicarPendientes();

    if (hayNuevo) {
      sonarNuevo();
      banner.hidden = false;
      setTimeout(function () { banner.hidden = true; }, 4000);
    }
  } catch (e) {
    estadoConexion.textContent = 'Sin conexión con el servidor';
    estadoConexion.classList.remove('ok');
    sinConexion = true;
    renderizar();
  } finally {
    consultando = false;
  }
}

/* Anota el cambio, lo muestra ya, y lo manda al servidor. Si el servidor
   falla, se avisa y la pantalla vuelve a lo que dice el servidor. */
async function cambiarYMandar(ids, cambio, mandar, textoError) {
  ids.forEach(function (id) { cambiosPendientes[id] = cambio; });
  aplicarPendientes();
  try {
    var response = await mandar();
    if (!response.ok) throw new Error('Respuesta no válida');
    // Ya quedó en el servidor: se aplica también a la copia local, así no
    // parpadea hasta la próxima consulta.
    pedidosDelServidor = pedidosDelServidor
      .filter(function (pedido) { return cambio !== 'fuera' || ids.indexOf(pedido.id) === -1; })
      .map(function (pedido) {
        return ids.indexOf(pedido.id) !== -1 && cambio !== 'fuera'
          ? Object.assign({}, pedido, { estado: cambio })
          : pedido;
      });
  } catch (e) {
    console.error(e);
    alert(textoError);
  } finally {
    ids.forEach(function (id) {
      if (cambiosPendientes[id] === cambio) delete cambiosPendientes[id];
    });
    versionCambios += 1;
    aplicarPendientes();
  }
}

/* =====================
   CAMBIAR ESTADO
   ===================== */

function cambiarEstado(id, estado) {
  return cambiarYMandar([id], estado, function () {
    return pedir(API + '/api/orders/' + id + '/estado', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ estado: estado })
    });
  }, 'No se pudo actualizar el pedido #' + id + '. Revisá la conexión.');
}

/* Sacar un pedido de la pantalla no lo borra: sigue en el registro de
   pedidos (archivo.html). */
function eliminarPedido(id) {
  if (!confirm('¿Sacar el pedido #' + id + ' de la pantalla?\n\nQueda guardado en el registro de pedidos.')) return;
  return cambiarYMandar([id], 'fuera', function () {
    return pedir(API + '/api/orders/' + id, { method: 'DELETE' });
  }, 'No se pudo sacar el pedido #' + id + '. Revisá la conexión.');
}

/* =====================
   BORRAR TODOS LOS PEDIDOS
   ===================== */

function eliminarTodos() {
  if (pedidos.length === 0) return;
  var confirmacion = confirm(
    'Se van a sacar de la pantalla los ' + pedidos.length + ' pedidos.' +
    '\n\nQuedan todos guardados en el registro de pedidos.' +
    '\n\n¿Continuar?'
  );
  if (!confirmacion) return;

  var ids = pedidos.map(function (pedido) { return pedido.id; });
  // "hasta": se sacan solo los que se ven ahora. Un pedido que entra justo
  // mientras tanto no desaparece sin que nadie lo haya visto.
  var hasta = Math.max.apply(null, ids);
  return cambiarYMandar(ids, 'fuera', function () {
    return pedir(API + '/api/orders?hasta=' + hasta, { method: 'DELETE' });
  }, 'No se pudieron sacar los pedidos. Revisá la conexión.');
}

/* =====================
   TICKET
   ===================== */

function construirTicket(pedido) {
  var fecha = parseFecha(pedido.created_at);
  var opcionesTicketFecha = { day: '2-digit', month: '2-digit', year: 'numeric' };
  var opcionesTicketHora = { hour: '2-digit', minute: '2-digit' };

  var cliente = pedido.cliente || {};
  var esDomicilio = pedido.envio === 'domicilio';
  var nombreCliente = (cliente.nombre || '') + ' ' + (cliente.apellido || '');
  if (!nombreCliente.trim()) nombreCliente = 'Sin datos';

  var datosCliente =
    '<p class="ticket-cliente">' +
      (esDomicilio ? '🛵 A domicilio' : '🏪 Retiro en el local') + '<br>' +
      'Cliente: ' + esc(nombreCliente) +
      (cliente.telefono ? '<br>Tel: ' + esc(cliente.telefono) : '') +
      (esDomicilio && (cliente.calle || cliente.numero)
        ? '<br>' + esc(cliente.calle) + ' ' + esc(cliente.numero) +
          (cliente.entre ? ' (entre ' + esc(cliente.entre) + ')' : '')
        : '') +
    '</p>';

  var filas = pedido.items.map(function (item) {
    var cantidad = item.quantity || 1;
    var nombre = item.name || 'Sin nombre';
    var precioUnitario = item.price || 0;
    var subtotal = precioUnitario * cantidad;
    return (
      '<tr>' +
        '<td>' + esc(cantidad) + ' x ' + esc(nombre) + '</td>' +
        '<td class="num">' + formatPrice(subtotal) + '</td>' +
      '</tr>'
    );
  }).join('');

  return (
    '<h2 class="ticket-cabecera-titulo">MODO HAMBRE</h2>' +
    '<p class="ticket-datos">Ticket N° ' + pedido.id + '<br>' +
      'Fecha: ' + fecha.toLocaleDateString('es-AR', opcionesTicketFecha) + '<br>' +
      'Hora: ' + fecha.toLocaleTimeString('es-AR', opcionesTicketHora) + '</p>' +
    datosCliente +
    '<hr class="ticket-regla">' +
    '<table class="ticket-tabla">' +
      '<tbody>' + filas + '</tbody>' +
    '</table>' +
    '<hr class="ticket-regla">' +
    '<div class="ticket-total"><span>TOTAL</span><span>' + formatPrice(pedido.total) + '</span></div>' +
    '<p class="ticket-estado">Estado: ' + estadoTexto(pedido.estado) + '</p>'
  );
}

function imprimirTicket(id) {
  var pedido = pedidos.find(function (p) { return p.id === id; });
  if (!pedido) return;
  ticketPrint.innerHTML = construirTicket(pedido);
  window.print();
}

/* =====================
   EVENTOS
   ===================== */

lista.addEventListener('click', function (event) {
  var boton = event.target.closest('[data-accion]');
  if (!boton) return;
  var id = Number(boton.dataset.id);
  var accion = boton.dataset.accion;

  if (accion === 'recibir') cambiarEstado(id, 'recibido');
  else if (accion === 'listo') cambiarEstado(id, 'listo');
  else if (accion === 'imprimir') imprimirTicket(id);
  else if (accion === 'eliminar') eliminarPedido(id);
});

var botonBorrarTodos = document.getElementById('borrar-todos');
if (botonBorrarTodos) {
  botonBorrarTodos.addEventListener('click', eliminarTodos);
}

/* =====================
   LOCAL ABIERTO / CERRADO
   =====================
   Con el local cerrado la web no acepta pedidos. Queda guardado en el
   servidor, así que vale aunque este panel se cierre. */

var botonLocal = document.getElementById('boton-local');
var localAbierto = null;

function mostrarEstadoLocal() {
  if (!botonLocal) return;
  botonLocal.hidden = localAbierto === null;
  botonLocal.classList.toggle('local-cerrado', localAbierto === false);
  botonLocal.textContent = localAbierto ? '🟢 Local abierto' : '🔴 Local cerrado';
  botonLocal.title = localAbierto
    ? 'Los clientes pueden pedir. Tocá para cerrar.'
    : 'La web no acepta pedidos. Tocá para abrir.';
}

async function cargarEstadoLocal() {
  try {
    var response = await fetch(API + '/api/local/estado', { cache: 'no-store' });
    if (!response.ok) return;
    localAbierto = Boolean((await response.json()).abierto);
    mostrarEstadoLocal();
  } catch (e) {}
}

if (botonLocal) {
  botonLocal.addEventListener('click', async function () {
    var abrir = !localAbierto;
    if (!abrir && !confirm('¿Cerrar el local? La web deja de aceptar pedidos hasta que lo abras.')) return;
    botonLocal.disabled = true;
    try {
      var response = await pedir(API + '/api/local/estado', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ abierto: abrir })
      });
      if (!response.ok) throw new Error('Respuesta no válida');
      localAbierto = Boolean((await response.json()).abierto);
      mostrarEstadoLocal();
    } catch (e) {
      console.error(e);
      alert('No se pudo cambiar el estado del local. Revisá la conexión.');
    } finally {
      botonLocal.disabled = false;
    }
  });
}

/* =====================
   INICIALIZACIÓN
   ===================== */

cargarEstadoLocal();
cargarPedidos();
setInterval(cargarPedidos, 4000);