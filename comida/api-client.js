async function saveOrder(items) {
  const response = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items })
  });

  if (!response.ok) {
    throw new Error('No se pudo guardar el pedido');
  }

  return response.json();
}
