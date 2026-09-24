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
const whatsappNumber = '2215012289';

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
  return img ? img.src : '';
}

function animarContadorCarrito() {
  if (!cartCountEl) return;
  cartCountEl.classList.remove('animar');
  void cartCountEl.offsetWidth;
  cartCountEl.classList.add('animar');
}

function mostrarToast(texto) {
  var viejo = document.querySelector('.toast-cart');
  if (viejo) viejo.remove();
  var toast = document.createElement('div');
  toast.className = 'toast-cart';
  toast.setAttribute('role', 'status');
  toast.textContent = texto;
  document.body.appendChild(toast);
  requestAnimationFrame(function () {
    toast.classList.add('visible');
  });
  setTimeout(function () {
    toast.classList.remove('visible');
    setTimeout(function () { toast.remove(); }, 400);
  }, 2000);
}

document.querySelectorAll('.add-cart').forEach(function (button) {
  button.addEventListener('click', function () {
    var name = button.dataset.name;
    var price = Number(button.dataset.price);
    var image = getImageForPlato(button);
    addToCart(name, price, true, image);
  });
});

document.querySelectorAll('.variantes-toggle').forEach(function (button) {
  button.addEventListener('click', function () {
    var selector = button.closest('.plato').querySelector('.selector-variantes');
    var estabaAbierto = !selector.hidden;
    closeAllSelectors();
    if (!estabaAbierto) {
      selector.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      abrirOverlayGustos();
    }
  });
});

document.querySelectorAll('.variante-add').forEach(function (button) {
  button.addEventListener('click', function () {
    var image = getImageForPlato(button);
    var name = button.dataset.name;
    addToCart(name, Number(button.dataset.price), false, image);
    animarContadorCarrito();
    mostrarToast('Su ' + name.charAt(0).toLowerCase() + name.slice(1) + ' ha sido agregada al carrito');
  });
});

/* hundimiento al mantener pulsado — funciona en móvil y PC */
document.querySelectorAll('.boton, .variante-add').forEach(function (btn) {
  btn.addEventListener('pointerdown', function () {
    btn.classList.add('presionado');
  });
  function soltarPulsacion() {
    btn.classList.remove('presionado');
  }
  btn.addEventListener('pointerup', soltarPulsacion);
  btn.addEventListener('pointercancel', soltarPulsacion);
  btn.addEventListener('pointerleave', soltarPulsacion);
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
    ? 'Hola, quiero pedir por delivery:%0A%0A'
    : 'Hola, quiero retirar mi pedido en el local:%0A%0A';

  var datosCliente = esDomicilio
    ? 'Datos del cliente:%0A' +
      'Nombre: ' + cliente.nombre + ' ' + cliente.apellido + '%0A' +
      'Dirección: ' + cliente.calle + ' ' + cliente.numero +
      (cliente.entre ? ' (entre ' + cliente.entre + ')' : '')
    : 'Datos del cliente:%0A' +
      'Nombre: ' + cliente.nombre + ' ' + cliente.apellido + '%0A' +
      'Retiro en el local';

  var message = encabezado +
    lines.join('%0A') +
    '%0A%0ATotal: ' + formatPrice(getSubtotal()) +
    '%0A%0A' + datosCliente;

  window.open('https://wa.me/' + whatsappNumber + '?text=' + message, '_blank', 'noopener');
  cerrarCheckout();
}

/* =====================
   CHECKOUT — ELEGIR DOMICILIO O RETIRO EN LOCAL
   ===================== */

var checkoutOverlay = null;
var checkoutFinalizar = null;

function abrirCheckout(finalizar) {
  checkoutFinalizar = finalizar || function () {};
  mostrarPasoElegir();
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
        camposDomicilio +
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
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    checkoutFinalizar(tipo, leerDatosCliente(tipo));
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
    apellido: (form.elements.apellido.value || '').trim()
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

  var pedidoDB = cart.map(function (item) {
    return { name: item.name, price: item.price, quantity: item.quantity, image: item.image || '' };
  });

  saveOrder(pedidoDB, tipo, cliente)
    .then(function () {
      cart.length = 0;
      guardarCarrito();
      updateCart();
      cerrarCheckout();
      closeCartDrawer();
      mostrarToast('Su pedido se ha enviado correctamente');
      setTimeout(function () {
        if (!isOrderingPage) {
          window.location.href = 'platos.html';
        }
      }, 1400);
    })
    .catch(function (e) {
      console.error(e);
      botonConfirmar.disabled = false;
      mostrarToast('No se pudo enviar el pedido. Intentá de nuevo.');
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

document.querySelectorAll('.cerrar-selector').forEach(function (button) {
  button.addEventListener('click', closeAllSelectors);
});

document.addEventListener('click', function (event) {
  if (event.target.closest('.selector-variantes') || event.target.closest('.variantes-toggle')) return;
  closeAllSelectors();
});

document.addEventListener('keydown', function (event) {
  if (event.key === 'Escape') closeAllSelectors();
});

/* =====================
   CATEGORÍAS (accordion)
   ===================== */

document.querySelectorAll('.categoria-toggle').forEach(function (button) {
  button.addEventListener('click', function () {
    var categoria = button.closest('.categoria');
    var abierta = categoria.classList.toggle('abierta');
    button.setAttribute('aria-expanded', String(abierta));
  });
});

/* =====================
   INICIALIZACIÓN
   ===================== */

updateCart();
