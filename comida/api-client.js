async function saveOrder(items, envio, cliente) {
  const response = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items, envio, cliente })
  });

  if (!response.ok) {
    throw new Error('No se pudo guardar el pedido');
  }

  return response.json();
}
