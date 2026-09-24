/* PANEL DE PEDIDOS — MODE HAMBRE */

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
      '<td class="cantidad-cell">' + cantidad + '</td>' +
      '<td>' + nombre + '</td>' +
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

  if (pedidos.length === 0) {
    var tipoDeseado = sinConexion ? 'sin-conexion' : 'sin-pedidos';
    var vacioExistente = lista.querySelector('.pedido-vacio');
    if (!vacioExistente || vacioExistente.dataset.tipo !== tipoDeseado) {
      lista.innerHTML = sinConexion
        ? '<div class="pedido-vacio" data-tipo="sin-conexion">' +
            '<span class="pedido-vacio-icono">🔌</span>' +
            '<strong>Sin conexión con el servidor.</strong><br>' +
            'Abrí este panel desde <b>http://localhost:5000/admin.html</b><br>' +
            'con el servidor encendido (ejecutá <b>py app.py</b>).' +
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

async function cargarPedidos() {
  try {
    var response = await fetch('/api/orders');
    if (!response.ok) throw new Error('Respuesta no válida');
    var datos = await response.json();

    estadoConexion.textContent = 'Conectado · se actualiza cada 4 segundos';
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

    pedidos = datos;
    ultimoId = pedidos.length > 0 ? pedidos[0].id : null;
    renderizar();

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
  }
}

/* =====================
   CAMBIAR ESTADO
   ===================== */

async function cambiarEstado(id, estado) {
  try {
    var response = await fetch('/api/orders/' + id + '/estado', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ estado: estado })
    });
    if (!response.ok) throw new Error('Respuesta no válida');
    cargarPedidos();
  } catch (e) {
    console.error(e);
    alert('No se pudo actualizar el pedido. ¿Está el servidor activo?');
  }
}

async function eliminarPedido(id) {
  if (!confirm('¿Eliminar el pedido #' + id + '?')) return;
  try {
    var response = await fetch('/api/orders/' + id, { method: 'DELETE' });
    if (!response.ok) throw new Error('Respuesta no válida');
    pedidos = pedidos.filter(function (p) { return p.id !== id; });
    var card = lista.querySelector('[data-pedido-id="' + id + '"]');
    if (card) card.remove();
    renderizar();
  } catch (e) {
    console.error(e);
    alert('No se pudo eliminar el pedido. ¿Está el servidor activo?');
  }
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
    '</p>';

  var filas = pedido.items.map(function (item) {
    var cantidad = item.quantity || 1;
    var nombre = item.name || 'Sin nombre';
    var precioUnitario = item.price || 0;
    var subtotal = precioUnitario * cantidad;
    return (
      '<tr>' +
        '<td>' + cantidad + ' x ' + nombre + '</td>' +
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

/* =====================
   INICIALIZACIÓN
   ===================== */

cargarPedidos();
setInterval(cargarPedidos, 4000);