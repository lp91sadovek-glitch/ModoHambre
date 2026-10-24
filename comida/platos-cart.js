const STORAGE_KEY = 'carrito-modo-hambre';

function cargarCarrito() {
  try {
    const guardado = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (Array.isArray(guardado)) {
      return guardado
        .filter(item => item && typeof item.name === 'string' && typeof item.price === 'number')
        .map(item => ({
          name: item.name,
          price: item.price,
          image: item.image || '',
          quantity: item.quantity || 1
        }));
    }
  } catch (error) {
    // storage corrupto → carrito vacío
  }
  return [];
}

const cart = cargarCarrito();

function guardarCarrito() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cart));
  } catch (error) {
    // sin storage, carrito vive solo en sesión
  }
}

const cartItemsEl = document.getElementById('cart-items');
const cartSubtitle = document.getElementById('cart-subtitle');
const cartSubtotalEl = document.getElementById('cart-subtotal');
const cartEnvioEl = document.getElementById('cart-envio');
const cartTotalEl = document.getElementById('cart-total');
const cartCountEl = document.getElementById('cart-count');
const cartPanel = document.getElementById('cart-panel');
const cartOverlay = document.getElementById('cart-overlay');
const navOverlay = document.getElementById('nav-overlay');
const menuToggle = document.getElementById('menu-toggle');
const cartToggle = document.getElementById('cart-toggle');
const cartClose = document.getElementById('cart-close');
const navClose = document.getElementById('nav-close');
const clearCart = document.getElementById('clear-cart');
const whatsappOrderBtn = document.getElementById('whatsapp-order');
const systemOrderBtn = document.getElementById('system-order');
/* wa.me pide el número completo, sin + ni espacios: 54 (Argentina),
   9 (celular) y después la característica y el número. Sin el 549 abría
   otro número o daba error. */
const whatsappNumber = '5492215012289';

const isOrderingPage = window.location.pathname.includes('platos.html');

function formatPrice(value) {
  return '$' + value.toLocaleString('es-AR');
}

function getTotalItems() {
  return cart.reduce((sum, item) => sum + item.quantity, 0);
}

function getSubtotal() {
  return cart.reduce((sum, item) => sum + item.price * item.quantity, 0);
}

/* =====================
   RENDERIZADO DEL CARRITO
   ===================== */

function updateCart() {
  cartItemsEl.innerHTML = '';
  const totalItems = getTotalItems();
  const subtotal = getSubtotal();

  if (cart.length === 0) {
    cartSubtitle.textContent = 'Aún no hay productos';
  } else {
    cartSubtitle.textContent = totalItems + (totalItems === 1 ? ' producto' : ' productos');
  }

  if (cart.length === 0) {
    const showVerMenu = !isOrderingPage;
    cartItemsEl.innerHTML =
      '<div class="empty-cart-state">' +
        '<div class="empty-cart-icon">🛒</div>' +
        '<h3 class="empty-cart-title">Tu carrito está vacío</h3>' +
        '<p class="empty-cart-text">Agregá tus platos favoritos<br>y comenzá tu pedido.</p>' +
        (showVerMenu ? '<a href="platos.html" class="ver-menu-btn">🍴 Pedir comida</a>' : '') +
        '<div class="empty-cart-chef">👨‍🍳</div>' +
      '</div>';
  } else {
    cart.forEach(function (item, index) {
      var itemEl = document.createElement('div');
      itemEl.className = 'cart-item';

      var imgSrc = item.image || '';
      var imgHtml = imgSrc
        ? '<img class="cart-item-image" src="' + imgSrc + '" alt="' + item.name + '" onerror="this.style.display=\'none\'">'
        : '';

      itemEl.innerHTML =
        imgHtml +
        '<div class="cart-item-info">' +
          '<p class="cart-item-name">' + item.name + '</p>' +
          '<p class="cart-item-price">' + formatPrice(item.price * item.quantity) + '</p>' +
          '<div class="cart-item-controls">' +
            '<button class="quantity-btn qty-minus" data-index="' + index + '" aria-label="Disminuir cantidad">−</button>' +
            '<span class="cart-item-qty">' + item.quantity + '</span>' +
            '<button class="quantity-btn qty-plus" data-index="' + index + '" aria-label="Aumentar cantidad">+</button>' +
            '<button class="remove-item-btn" data-index="' + index + '" aria-label="Eliminar ' + item.name + '">🗑</button>' +
          '</div>' +
        '</div>';

      cartItemsEl.appendChild(itemEl);
    });
  }

  cartSubtotalEl.textContent = formatPrice(subtotal);
  cartEnvioEl.textContent = cart.length === 0 ? '—' : 'Gratis';
  cartTotalEl.textContent = formatPrice(subtotal);
  cartCountEl.textContent = getTotalItems();
  whatsappOrderBtn.disabled = cart.length === 0;
  clearCart.disabled = cart.length === 0;
  if (systemOrderBtn) {
    systemOrderBtn.disabled = cart.length === 0;
  }
}

/* =====================
   ABRIR / CERRAR CARRITO
   ===================== */

function openCartDrawer() {
  cartOverlay.classList.add('active');
  cartPanel.classList.add('open');
  cartPanel.setAttribute('aria-hidden', 'false');
  document.body.classList.add('panel-abierto');
}

function closeCartDrawer() {
  cartOverlay.classList.remove('active');
  cartPanel.classList.remove('open');
  cartPanel.setAttribute('aria-hidden', 'true');
  actualizarScrollLock();
}

function toggleCartDrawer() {
  if (cartPanel.classList.contains('open')) {
    closeCartDrawer();
  } else {
    closeAllPanels();
    openCartDrawer();
  }
}

/* =====================
   ABRIR / CERRAR MENÚ NAV
   ===================== */

function toggleNavOverlay(visible) {
  navOverlay.classList.toggle('visible', visible);
  navOverlay.setAttribute('aria-hidden', String(!visible));
  actualizarScrollLock();
}

function actualizarScrollLock() {
  var bloqueado = navOverlay.classList.contains('visible') || cartPanel.classList.contains('open');
  document.body.classList.toggle('panel-abierto', bloqueado);
}

function closeAllPanels() {
  closeCartDrawer();
  toggleNavOverlay(false);
}

/* =====================
   EVENT LISTENERS — NAVEGACIÓN
   ===================== */

menuToggle.addEventListener('click', function () {
  var visible = !navOverlay.classList.contains('visible');
  closeAllPanels();
  toggleNavOverlay(visible);
});

cartToggle.addEventListener('click', function () {
  toggleCartDrawer();
});

cartClose.addEventListener('click', function () {
  closeCartDrawer();
});

cartOverlay.addEventListener('click', function (event) {
  if (event.target === cartOverlay) {
    closeCartDrawer();
  }
});

if (navClose) {
  navClose.addEventListener('click', function () {
    toggleNavOverlay(false);
  });
}

navOverlay.addEventListener('click', function (event) {
  if (event.target === navOverlay) {
    toggleNavOverlay(false);
  }
});

document.addEventListener('keydown', function (event) {
  if (event.key === 'Escape') closeAllPanels();
});

/* =====================
   AGREGAR AL CARRITO
   ===================== */

function addToCart(name, price, openCart, image) {
  var existing = cart.find(function (item) { return item.name === name; });
  if (existing) {
    existing.quantity += 1;
  } else {
    cart.push({ name: name, price: price, image: image || '', quantity: 1 });
  }
  guardarCarrito();
  updateCart();
  if (openCart) {
    openCartDrawer();
  }
}

function getImageForPlato(button) {
  var plato = button.closest('.plato');
  if (!plato) return '';
  var img = plato.querySelector('.img-platos');
  if (!img) return '';
  /* Se manda solo el path relativo: si guardamos el src completo queda
     "localhost:5000" en la base y el panel no encuentra la imagen. */
  try {
    return new URL(img.src).pathname;
  } catch (e) {
    return img.src;
  }
}

function animarContadorCarrito() {
  if (!cartCountEl) return;
  cartCountEl.classList.remove('animar');
  void cartCountEl.offsetWidth;
  cartCountEl.classList.add('animar');
}

function mostrarToast(texto, tipo) {
  var viejo = document.querySelector('.toast-cart');
  if (viejo) viejo.remove();
  var toast = document.createElement('div');
  toast.className = tipo ? 'toast-cart ' + tipo : 'toast-cart';
  toast.setAttribute('role', 'status');
  toast.textContent = texto;
  document.body.appendChild(toast);
  requestAnimationFrame(function () {
    toast.classList.add('visible');
  });
  setTimeout(function () {
    toast.classList.remove('visible');
    setTimeout(function () { toast.remove(); }, 400);
  }, tipo === 'error' ? 5000 : 2000);
}

/* =====================
   EL MENÚ (platos y categorías)
   =====================
   Todo esto usa delegación de eventos en vez de engancharle el clic a cada
   botón que ya existe en la página. La razón es que el menú ahora se dibuja
   desde la base de datos (platos-menu.js) y llega después de que esta página
   terminó de cargar: con delegación los botones nuevos funcionan sin tocar
   nada acá. También por eso el menú de respaldo escrito en el HTML y el que
   viene de la base se comportan exactamente igual. */

document.addEventListener('click', function (event) {
  var boton;

  /* Agregar al carrito una comida de un solo precio. */
  boton = event.target.closest('.add-cart');
  if (boton) {
    addToCart(
      boton.dataset.name,
      Number(boton.dataset.price),
      true,
      getImageForPlato(boton)
    );
    return;
  }

  /* Agregar al carrito una comida con el gusto elegido. */
  boton = event.target.closest('.variante-add');
  if (boton) {
    var name = boton.dataset.name;
    addToCart(name, Number(boton.dataset.price), false, getImageForPlato(boton));
    animarContadorCarrito();
    // Sin "agregada"/"agregado": el nombre puede ser de cualquier género.
    mostrarToast('Agregado al carrito: ' + name);
    return;
  }

  /* Abrir y cerrar la lista de gustos de una comida. */
  boton = event.target.closest('.variantes-toggle');
  if (boton) {
    var plato = boton.closest('.plato');
    var selector = plato && plato.querySelector('.selector-variantes');
    if (selector) {
      var estabaAbierto = !selector.hidden;
      closeAllSelectors();
      if (!estabaAbierto) {
        selector.hidden = false;
        boton.setAttribute('aria-expanded', 'true');
        abrirOverlayGustos();
      }
    }
    return;
  }

  /* Cerrar la lista de gustos con la cruz. */
  if (event.target.closest('.cerrar-selector')) {
    closeAllSelectors();
    return;
  }

  /* Abrir y cerrar una categoría (el acordeón). */
  boton = event.target.closest('.categoria-toggle');
  if (boton) {
    var categoria = boton.closest('.categoria');
    if (categoria) {
      var abierta = categoria.classList.toggle('abierta');
      boton.setAttribute('aria-expanded', String(abierta));
    }
  }
});

/* hundimiento al mantener pulsado — funciona en móvil y PC */
document.addEventListener('pointerdown', function (event) {
  var boton = event.target.closest('.boton, .variante-add');
  if (boton) boton.classList.add('presionado');
});

['pointerup', 'pointercancel', 'pointerleave'].forEach(function (evento) {
  document.addEventListener(evento, function (event) {
    var boton = event.target.closest('.boton, .variante-add');
    if (boton) boton.classList.remove('presionado');
  }, true);
});

/* =====================
   CONTROLES DEL CARRITO
   ===================== */

cartItemsEl.addEventListener('click', function (event) {
  var minusBtn = event.target.closest('.qty-minus');
  var plusBtn = event.target.closest('.qty-plus');
  var removeBtn = event.target.closest('.remove-item-btn');

  if (minusBtn) {
    var idx = Number(minusBtn.dataset.index);
    if (cart[idx].quantity > 1) {
      cart[idx].quantity -= 1;
    } else {
      cart.splice(idx, 1);
    }
    guardarCarrito();
    updateCart();
  } else if (plusBtn) {
    var idx2 = Number(plusBtn.dataset.index);
    cart[idx2].quantity += 1;
    guardarCarrito();
    updateCart();
  } else if (removeBtn) {
    var idx3 = Number(removeBtn.dataset.index);
    cart.splice(idx3, 1);
    guardarCarrito();
    updateCart();
  }
});

clearCart.addEventListener('click', function () {
  cart.length = 0;
  guardarCarrito();
  updateCart();
});

whatsappOrderBtn.addEventListener('click', function () {
  if (cart.length === 0) return;
  abrirCheckout(enviarPedidoWhatsApp);
});

function enviarPedidoWhatsApp(tipo, cliente) {
  var esDomicilio = tipo === 'domicilio';

  var lines = cart.map(function (item) {
    var qty = item.quantity > 1 ? ' (x' + item.quantity + ')' : '';
    return '- ' + item.name + qty + ': ' + formatPrice(item.price * item.quantity);
  });

  var encabezado = esDomicilio
    ? 'Hola, quiero pedir por delivery:\n\n'
    : 'Hola, quiero retirar mi pedido en el local:\n\n';

  var datosCliente = esDomicilio
    ? 'Datos del cliente:\n' +
      'Nombre: ' + cliente.nombre + ' ' + cliente.apellido + '\n' +
      'Teléfono: ' + cliente.telefono + '\n' +
      'Dirección: ' + cliente.calle + ' ' + cliente.numero +
      (cliente.entre ? ' (entre ' + cliente.entre + ')' : '')
    : 'Datos del cliente:\n' +
      'Nombre: ' + cliente.nombre + ' ' + cliente.apellido + '\n' +
      'Teléfono: ' + cliente.telefono + '\n' +
      'Retiro en el local';

  var message = encabezado +
    lines.join('\n') +
    '\n\nTotal: ' + formatPrice(getSubtotal()) +
    '\n\n' + datosCliente;

  /* encodeURIComponent: sin esto un "&" o un "#" en la dirección cortaba el
     mensaje ahí ("Calle 7 & 50" llegaba como "Calle 7"). */
  window.open('https://wa.me/' + whatsappNumber + '?text=' + encodeURIComponent(message), '_blank', 'noopener');
  cerrarCheckout();
}

/* =====================
   CHECKOUT — ELEGIR DOMICILIO O RETIRO EN LOCAL
   ===================== */

var checkoutOverlay = null;
var checkoutFinalizar = null;

/* DATOS DEL CLIENTE GUARDADOS EN EL NAVEGADOR
   Si el cliente lo deja marcado, su nombre, teléfono y dirección quedan
   guardados en este celular o computadora (y en ningún otro lado del
   navegador), así la próxima vez el formulario ya viene completo. */
var DATOS_CLIENTE_KEY = 'datos-cliente-modo-hambre';
var CAMPOS_CLIENTE = ['nombre', 'apellido', 'telefono', 'calle', 'entre', 'numero'];

function datosGuardados() {
  try {
    var datos = JSON.parse(localStorage.getItem(DATOS_CLIENTE_KEY));
    return datos && typeof datos === 'object' ? datos : null;
  } catch (error) {
    return null;
  }
}

function guardarDatosCliente(cliente) {
  try {
    // Se mezcla con lo que ya había: si esta vez retira en el local, no se
    // pierde la dirección que dejó la vez anterior.
    var datos = datosGuardados() || {};
    CAMPOS_CLIENTE.forEach(function (campo) {
      if (cliente[campo]) datos[campo] = cliente[campo];
    });
    localStorage.setItem(DATOS_CLIENTE_KEY, JSON.stringify(datos));
  } catch (error) {
    // sin storage (modo privado): no se recuerda, pero el pedido sale igual
  }
}

function olvidarDatosCliente() {
  try {
    localStorage.removeItem(DATOS_CLIENTE_KEY);
  } catch (error) {}
}

function abrirCheckout(finalizar) {
  checkoutFinalizar = finalizar || function () {};
  if (finalizar === enviarPedidoSistema) despertarServidor();
  mostrarPasoElegir();
}

/* Mientras el cliente escribe sus datos se despierta el servidor y la base de
   datos (si estaban dormidos, despertarlos tarda unos segundos). Así, al tocar
   "Confirmar pedido" ya están listos. De paso, si el local está cerrado se
   avisa ahora y no después de llenar todo. */
function despertarServidor() {
  fetch(API_PEDIDOS + '/api/local/estado?despertar=1', { cache: 'no-store' })
    .then(function (respuesta) { return respuesta.ok ? respuesta.json() : null; })
    .then(function (datos) {
      if (datos && datos.abierto === false) {
        mostrarToast('El local está cerrado ahora mismo: no se pueden enviar pedidos por la app.', 'error');
      }
    })
    .catch(function () {});
}

function crearCheckoutOverlay() {
  if (checkoutOverlay) return;
  checkoutOverlay = document.createElement('div');
  checkoutOverlay.className = 'elegir-overlay';
  checkoutOverlay.setAttribute('aria-hidden', 'true');
  document.body.appendChild(checkoutOverlay);
}

function cerrarCheckout() {
  if (!checkoutOverlay) return;
  checkoutOverlay.classList.remove('visible');
  checkoutOverlay.setAttribute('aria-hidden', 'true');
  checkoutOverlay.innerHTML = '';
  document.body.classList.remove('checkout-abierto');
}

function mostrarPasoElegir() {
  crearCheckoutOverlay();
  checkoutOverlay.innerHTML =
    '<div class="elegir-panel" role="dialog" aria-modal="true" aria-label="Elegir forma de entrega">' +
      '<button class="elegir-cerrar" id="elegir-cerrar-paso" type="button" aria-label="Cerrar">×</button>' +
      '<h2 class="elegir-titulo">¿Cómo querés recibir tu pedido?</h2>' +
      '<p class="elegir-subtitulo">Elegí una opción para continuar</p>' +
      '<div class="elegir-opciones">' +
        '<button class="elegir-opcion" id="elegir-domicilio" type="button">' +
          '<span class="elegir-emoji">🛵</span>' +
          '<span class="elegir-texto">A domicilio</span>' +
          '<span class="elegir-flecha">→</span>' +
        '</button>' +
        '<button class="elegir-opcion" id="elegir-local" type="button">' +
          '<span class="elegir-emoji">🏪</span>' +
          '<span class="elegir-texto">Retirar en el local</span>' +
          '<span class="elegir-flecha">→</span>' +
        '</button>' +
      '</div>' +
    '</div>';

  checkoutOverlay.classList.add('visible');
  checkoutOverlay.setAttribute('aria-hidden', 'false');
  document.body.classList.add('checkout-abierto');

  checkoutOverlay.querySelector('#elegir-domicilio').addEventListener('click', function () {
    mostrarPasoFormulario('domicilio');
  });
  checkoutOverlay.querySelector('#elegir-local').addEventListener('click', function () {
    mostrarPasoFormulario('local');
  });
  checkoutOverlay.querySelector('#elegir-cerrar-paso').addEventListener('click', cerrarCheckout);
  checkoutOverlay.addEventListener('click', function (event) {
    if (event.target === checkoutOverlay) cerrarCheckout();
  });
}

function mostrarPasoFormulario(tipo) {
  var esDomicilio = tipo === 'domicilio';
  var camposDomicilio = esDomicilio
    ? '<label class="elegir-campo">' +
        '<span>Calle principal</span>' +
        '<input type="text" name="calle" placeholder="Ej: Av. 7" required>' +
      '</label>' +
      '<label class="elegir-campo">' +
        '<span>Entre qué calles</span>' +
        '<input type="text" name="entre" placeholder="Ej: entre 44 y 45" required>' +
      '</label>' +
      '<label class="elegir-campo">' +
        '<span>Número de casa</span>' +
        '<input type="text" name="numero" placeholder="Ej: 1234" required>' +
      '</label>'
    : '';

  crearCheckoutOverlay();
  checkoutOverlay.innerHTML =
    '<div class="elegir-panel" role="dialog" aria-modal="true" aria-label="Datos del cliente">' +
      '<button class="elegir-cerrar" id="elegir-cerrar-paso" type="button" aria-label="Cerrar">×</button>' +
      '<h2 class="elegir-titulo">' + (esDomicilio ? '🛵 Datos del envío' : '🏪 Datos para retirar') + '</h2>' +
      '<p class="elegir-subtitulo">Necesitamos tus datos para confirmar el pedido</p>' +
      '<form class="elegir-form" id="elegir-form">' +
        '<label class="elegir-campo">' +
          '<span>Nombre</span>' +
          '<input type="text" name="nombre" placeholder="Tu nombre" required autocomplete="given-name">' +
        '</label>' +
        '<label class="elegir-campo">' +
          '<span>Apellido</span>' +
          '<input type="text" name="apellido" placeholder="Tu apellido" required autocomplete="family-name">' +
        '</label>' +
        /* El teléfono es para que el local pueda avisar o coordinar el pago.
           Se aceptan espacios, guiones, paréntesis y el +54. */
        '<label class="elegir-campo">' +
          '<span>Teléfono</span>' +
          '<input type="tel" name="telefono" placeholder="Ej: 221 501 2289" required autocomplete="tel"' +
          ' inputmode="tel" pattern="[0-9 +\\(\\)\\-]{8,20}"' +
          ' title="Escribí tu número con la característica, por ejemplo 221 501 2289">' +
        '</label>' +
        camposDomicilio +
        '<label class="elegir-recordar">' +
          '<input type="checkbox" name="recordar" checked>' +
          '<span>Recordar mis datos en este dispositivo</span>' +
        '</label>' +
        '<p class="elegir-guardados" id="elegir-guardados" hidden>' +
          'Completamos tus datos de la última vez. ' +
          '<button type="button" id="elegir-olvidar">Borrar mis datos</button>' +
        '</p>' +
        '<div class="elegir-form-acciones">' +
          '<button class="elegir-boton-volver" id="elegir-volver" type="button">← Volver</button>' +
          '<button class="elegir-boton-confirmar" type="submit">Confirmar pedido</button>' +
        '</div>' +
      '</form>' +
    '</div>';

  checkoutOverlay.classList.add('visible');
  checkoutOverlay.setAttribute('aria-hidden', 'false');
  document.body.classList.add('checkout-abierto');

  var form = checkoutOverlay.querySelector('#elegir-form');

  // Los datos se ponen con .value y no dentro del HTML: así un nombre con
  // comillas o con "<" no puede romper el formulario.
  var guardados = datosGuardados();
  if (guardados) {
    CAMPOS_CLIENTE.forEach(function (campo) {
      if (form.elements[campo] && guardados[campo]) form.elements[campo].value = guardados[campo];
    });
    checkoutOverlay.querySelector('#elegir-guardados').hidden = false;
  }
  checkoutOverlay.querySelector('#elegir-olvidar').addEventListener('click', function () {
    olvidarDatosCliente();
    CAMPOS_CLIENTE.forEach(function (campo) {
      if (form.elements[campo]) form.elements[campo].value = '';
    });
    form.elements.recordar.checked = false;
    checkoutOverlay.querySelector('#elegir-guardados').hidden = true;
    form.elements.nombre.focus();
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    var cliente = leerDatosCliente(tipo);
    if (form.elements.recordar.checked) {
      guardarDatosCliente(cliente);
    } else {
      olvidarDatosCliente();
    }
    checkoutFinalizar(tipo, cliente);
  });
  checkoutOverlay.querySelector('#elegir-volver').addEventListener('click', mostrarPasoElegir);
  checkoutOverlay.querySelector('#elegir-cerrar-paso').addEventListener('click', cerrarCheckout);
  checkoutOverlay.addEventListener('click', function (event) {
    if (event.target === checkoutOverlay) cerrarCheckout();
  });
}

function leerDatosCliente(tipo) {
  var form = checkoutOverlay.querySelector('#elegir-form');
  var cliente = {
    nombre: (form.elements.nombre.value || '').trim(),
    apellido: (form.elements.apellido.value || '').trim(),
    telefono: (form.elements.telefono.value || '').trim()
  };
  if (tipo === 'domicilio') {
    cliente.calle = (form.elements.calle.value || '').trim();
    cliente.entre = (form.elements.entre.value || '').trim();
    cliente.numero = (form.elements.numero.value || '').trim();
  }
  return cliente;
}

function enviarPedidoSistema(tipo, cliente) {
  var botonConfirmar = checkoutOverlay.querySelector('.elegir-boton-confirmar');
  botonConfirmar.disabled = true;
  // Se ve al instante que el toque se tomó, aunque el servidor tarde.
  botonConfirmar.textContent = 'Enviando pedido…';

  var pedidoDB = cart.map(function (item) {
    return { name: item.name, price: item.price, quantity: item.quantity, image: item.image || '' };
  });

  /* Después de enviar el cliente se queda en la misma página. Antes, desde el
     inicio se lo mandaba a platos.html, que es la página más pesada, y parecía
     que el pedido tardaba más en salir. */
  saveOrder(pedidoDB, tipo, cliente)
    .then(function () {
      cart.length = 0;
      guardarCarrito();
      updateCart();
      cerrarCheckout();
      closeCartDrawer();
      mostrarToast('Su pedido se ha enviado correctamente');
    })
    .catch(function (e) {
      console.error(e);
      botonConfirmar.disabled = false;
      botonConfirmar.textContent = 'Confirmar pedido';
      // el carrito y el formulario quedan como estaban, el cliente puede
      // reintentar mas tarde
      if (e && e.codigo === 'local_cerrado') {
        mostrarToast('No se pudo enviar el pedido: el local está cerrado ahora mismo. Intentá de nuevo más tarde.', 'error');
      } else {
        mostrarToast('No se pudo enviar el pedido. Intentá de nuevo.', 'error');
      }
    });
}

systemOrderBtn.addEventListener('click', function () {
  if (cart.length === 0) return;
  abrirCheckout(enviarPedidoSistema);
});

/* =====================
   SELECTORES DE VARIANTES
   ===================== */

var overlayGustos = null;

function crearOverlayGustos() {
  if (overlayGustos) return;
  overlayGustos = document.createElement('div');
  overlayGustos.className = 'gustos-overlay';
  overlayGustos.setAttribute('aria-hidden', 'true');
  document.body.appendChild(overlayGustos);
  overlayGustos.addEventListener('click', closeAllSelectors);
}

function abrirOverlayGustos() {
  crearOverlayGustos();
  overlayGustos.classList.add('visible');
  overlayGustos.setAttribute('aria-hidden', 'false');
  document.body.classList.add('gusto-abierto');
}

function cerrarOverlayGustos() {
  if (!overlayGustos) return;
  overlayGustos.classList.remove('visible');
  overlayGustos.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('gusto-abierto');
}

function closeAllSelectors() {
  document.querySelectorAll('.selector-variantes').forEach(function (selector) {
    selector.hidden = true;
  });
  document.querySelectorAll('.variantes-toggle').forEach(function (button) {
    button.setAttribute('aria-expanded', 'false');
  });
  cerrarOverlayGustos();
}

/* Un clic en cualquier lado de la página que no sea la lista de gustos la
   cierra. El enganche de los botones está arriba, con el resto del menú. */
document.addEventListener('click', function (event) {
  if (event.target.closest('.selector-variantes') || event.target.closest('.variantes-toggle')) return;
  closeAllSelectors();
});

document.addEventListener('keydown', function (event) {
  if (event.key === 'Escape') closeAllSelectors();
});

/* =====================
   BARRA SUPERIOR
   =====================
   Arriba de todo la barra es transparente y se ve el fondo. Apenas se
   scrollea toma color, así los botones no quedan encima del contenido.
   Al entrar a la página arranca con color (el HTML ya trae con-scroll) y
   se vuelve transparente después de la espera del CSS (5 segundos). */

var barraSuperior = document.querySelector('.header');

function marcarBarraSuperior() {
  if (barraSuperior) barraSuperior.classList.toggle('con-scroll', window.scrollY > 8);
}

window.addEventListener('scroll', marcarBarraSuperior, { passive: true });

/* =====================
   INICIALIZACIÓN
   ===================== */

/* Se espera a que la barra ya se haya dibujado con color: si se le saca la
   clase antes, el navegador no hace la transición y queda transparente de una. */
requestAnimationFrame(function () {
  requestAnimationFrame(marcarBarraSuperior);
});
updateCart();
