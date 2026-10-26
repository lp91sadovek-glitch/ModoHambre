/* ---- A DONDE MANDA LOS PEDIDOS ----
   Vacio ('') = al mismo sitio desde donde se abrio la pagina
   (modohambre.onrender.com). Ahi se guardan en la base y el panel los ve. */
var API_PEDIDOS = '';

async function saveOrder(items, envio, cliente) {
  const response = await fetch(API_PEDIDOS + '/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // sitio_web: el campo trampa del formulario (ver platos-cart.js)
    body: JSON.stringify({ items, envio, cliente, sitio_web: (cliente && cliente.sitio_web) || '' })
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