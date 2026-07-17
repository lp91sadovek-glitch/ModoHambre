const cart = [];
const cartItemsEl = document.getElementById('cart-items');
const cartTotalEl = document.getElementById('cart-total');
const cartCountEl = document.getElementById('cart-count');
const cartPanel = document.getElementById('cart-panel');
const navOverlay = document.getElementById('nav-overlay');
const menuToggle = document.getElementById('menu-toggle');
const cartToggle = document.getElementById('cart-toggle');
const cartClose = document.getElementById('cart-close');
const navClose = document.getElementById('nav-close');
const clearCart = document.getElementById('clear-cart');
const whatsappOrderBtn = document.getElementById('whatsapp-order');
const whatsappNumber = '2215012289';

function formatPrice(value) {
  return '$' + value.toLocaleString('es-AR');
}

function updateCart() {
  cartItemsEl.innerHTML = '';
  if (cart.length === 0) {
    cartItemsEl.innerHTML = '<p class="empty-cart">Aún no hay platos en el carrito.</p>';
  } else {
    cart.forEach((item, index) => {
      const itemEl = document.createElement('div');
      itemEl.className = 'cart-item';
      itemEl.innerHTML = `
        <div>
          <p class="cart-item-name">${item.name}</p>
          <p class="cart-item-price">${formatPrice(item.price)}</p>
        </div>
        <button class="remove-item" data-index="${index}" aria-label="Eliminar ${item.name}">Eliminar</button>
      `;
      cartItemsEl.appendChild(itemEl);
    });
  }
  const total = cart.reduce((sum, item) => sum + item.price, 0);
  cartTotalEl.textContent = formatPrice(total);
  cartCountEl.textContent = cart.length;
  whatsappOrderBtn.disabled = cart.length === 0;
}

function togglePanel(panel, visible) {
  panel.classList.toggle('visible', visible);
  panel.setAttribute('aria-hidden', String(!visible));
}

function closeAllPanels() {
  togglePanel(cartPanel, false);
  togglePanel(navOverlay, false);
}

function addToCart(name, price) {
  cart.push({ name, price });
  updateCart();
  togglePanel(cartPanel, true);
}

menuToggle.addEventListener('click', () => {
  const visible = !navOverlay.classList.contains('visible');
  closeAllPanels();
  togglePanel(navOverlay, visible);
});

cartToggle.addEventListener('click', () => {
  const visible = !cartPanel.classList.contains('visible');
  closeAllPanels();
  togglePanel(cartPanel, visible);
});

cartClose.addEventListener('click', () => togglePanel(cartPanel, false));
navClose.addEventListener('click', () => togglePanel(navOverlay, false));
clearCart.addEventListener('click', () => {
  cart.length = 0;
  updateCart();
});

whatsappOrderBtn.addEventListener('click', () => {
  if (cart.length === 0) return;

  const message = `Hola, quiero hacer este pedido:%0A%0A${cart.map((item) => `- ${item.name}: ${formatPrice(item.price)}`).join('%0A')}%0A%0ATotal: ${formatPrice(cart.reduce((sum, item) => sum + item.price, 0))}`;
  window.open(`https://wa.me/${whatsappNumber}?text=${message}`, '_blank', 'noopener');
});

cartItemsEl.addEventListener('click', (event) => {
  const button = event.target.closest('.remove-item');
  if (!button) return;
  const index = Number(button.dataset.index);
  cart.splice(index, 1);
  updateCart();
});

document.querySelectorAll('.add-cart').forEach(button => {
  button.addEventListener('click', () => {
    const name = button.dataset.name;
    const price = Number(button.dataset.price);
    addToCart(name, price);
  });
});

updateCart();
