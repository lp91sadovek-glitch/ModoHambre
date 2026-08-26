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
        (showVerMenu ? '<a href="platos.html" class="ver-menu-btn">🍴 Ver menú</a>' : '') +
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
    }
  });
});

document.querySelectorAll('.variante-add').forEach(function (button) {
  button.addEventListener('click', function () {
    var image = getImageForPlato(button);
    addToCart(button.dataset.name, Number(button.dataset.price), false, image);
  });
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

  var lines = cart.map(function (item) {
    var qty = item.quantity > 1 ? ' (x' + item.quantity + ')' : '';
    return '- ' + item.name + qty + ': ' + formatPrice(item.price * item.quantity);
  });

  var message = 'Hola, quiero hacer este pedido:%0A%0A' +
    lines.join('%0A') +
    '%0A%0ATotal: ' + formatPrice(getSubtotal());

  window.open('https://wa.me/' + whatsappNumber + '?text=' + message, '_blank', 'noopener');
});

/* =====================
   SELECTORES DE VARIANTES
   ===================== */

function closeAllSelectors() {
  document.querySelectorAll('.selector-variantes').forEach(function (selector) {
    selector.hidden = true;
  });
  document.querySelectorAll('.variantes-toggle').forEach(function (button) {
    button.setAttribute('aria-expanded', 'false');
  });
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
