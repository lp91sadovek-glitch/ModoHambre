/* ---- A DONDE MANDA LOS PEDIDOS ----
   Dejalo vacio ('') para que el pedido se guarde en el servidor local (pruebas).
   Con la URL de OnRender, el pedido viaja al puente y el panel lo recibe,
   aunque la web la estes sirviendo en tu PC o en la del cliente. */
var API_PEDIDOS = 'https://modohambre.onrender.com';

async function saveOrder(items, envio, cliente) {
  const response = await fetch(API_PEDIDOS + '/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items, envio, cliente })
  });

  if (!response.ok) {
    // el servidor puede explicar por que fallo (por ejemplo, que el local esta
    // cerrado). Si no dice nada, usamos un mensaje generico.
    let mensaje = 'No se pudo guardar el pedido';
    let codigo = '';
    try {
      const datos = await response.json();
      if (datos && datos.error) mensaje = datos.error;
      if (datos && datos.codigo) codigo = datos.codigo;
    } catch (e) {}

    const error = new Error(mensaje);
    error.codigo = codigo;
    throw error;
  }

  return response.json();
}