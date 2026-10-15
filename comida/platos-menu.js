/* DIBUJAR EL MENÚ QUE VIENEN DE LA BASE — MODO HAMBRE
 *
 * El menú de la página del cliente estaba escrito a mano en platos.html.
 * Ahora está en la base de datos, así que el dueño lo cambia desde el panel y
 * acá se dibuja lo que viene de /api/menu.
 *
 * Lo importante: el HTML sigue teniendo el menú escrito adentro, y es el que
 * se muestra si la base no contesta. Un local sin internet (o con la base
 * caída) sigue atendiendo pedidos con el menu de siempre, en vez de una página
 * vacía. Cuando la base contesta, se reemplaza.
 *
 * Los botones del menu dibujado acá funcionan porque platos-cart.js usa
 * delegación de eventos: no importa si los botones estaban en el HTML o se
 * crearon después.
 */

(function () {
    'use strict';

    var contenedor = document.querySelector('.container-categorias');
    if (!contenedor) return;

    /* El pedido de la base no puede tardar toda la vida: si la base está
       lenta o dormida, el cliente tiene que ver el menú de respaldo ya. */
    var TIEMPO_MAXIMO = 4000;

    function esc(valor) {
        return String(valor == null ? '' : valor)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function conPrecio(valor) {
        return '$' + Number(valor || 0).toLocaleString('es-AR');
    }

    function platoHTML(comida) {
        var id = comida.ancla ? ' id="menu-' + esc(comida.ancla) + '"' : '';
        var foto = comida.imagen_url
            ? '<img class="img-platos img-completa" src="' + esc(comida.imagen_url) +
              '" alt="' + esc(comida.nombre) + '" loading="lazy">'
            : '<div class="img-platos img-completa"></div>';

        var pie;
        if (comida.tipo === 'gustos' && (comida.gustos || []).length) {
            pie =
                '<div class="plato-footer">' +
                '<span class="plato-price">Desde ' + conPrecio(Math.min.apply(null, comida.gustos.map(function (g) {
                    return Number(g.precio) || 0;
                }))) + '</span>' +
                '<button class="boton variantes-toggle" type="button" aria-expanded="false">Agregar</button>' +
                '</div>' +
                '<div class="selector-variantes" hidden>' +
                '<button class="cerrar-selector" type="button" aria-label="Cerrar">×</button>' +
                '<p class="selector-titulo">' + esc(comida.nombre) + '</p>' +
                comida.gustos.map(function (gusto) {
                    return '<div class="variante">' +
                        '<span>' + esc(gusto.nombre) + ' · ' + conPrecio(gusto.precio) + '</span>' +
                        '<button class="variante-add" type="button" data-name="' +
                        esc(gusto.nombre) + '" data-price="' + esc(gusto.precio) + '">Agregar</button>' +
                        '</div>';
                }).join('') +
                '</div>';
        } else {
            pie =
                '<div class="plato-footer">' +
                '<span class="plato-price">' + conPrecio(comida.precio) + '</span>' +
                '<button class="boton add-cart" type="button" data-name="' +
                esc(comida.nombre) + '" data-price="' + esc(comida.precio) + '">Agregar</button>' +
                '</div>';
        }

        return '<article class="plato"' + id + '>' +
            foto +
            '<p>' + esc(comida.descripcion || comida.nombre) + '</p>' +
            pie +
            '</article>';
    }

    function categoriaHTML(categoria) {
        return '<div class="categoria">' +
            '<button class="categoria-toggle" type="button" aria-expanded="false">' +
            '<span class="categoria-icono-circulo">' + esc(categoria.icono || '🍽') + '</span>' +
            '<span>' + esc(categoria.nombre) + '</span>' +
            '<span class="categoria-icono">▼</span>' +
            '</button>' +
            '<div class="categoria-contenido">' +
            '<div class="categoria-inner">' +
            '<div class="container-platos">' +
            (categoria.comidas || []).map(platoHTML).join('') +
            '</div></div></div></div>';
    }

    function dibujar(categorias) {
        contenedor.innerHTML = categorias.map(categoriaHTML).join('');
        // Se avisa a la página para que aplique lo del link ?plato=..., que
        // estaba esperando a que el menú estuviera en su lugar.
        if (typeof window.avisoQueElMenuEstaListo === 'function') {
            window.avisoQueElMenuEstaListo();
        }
    }

    /* Mientras llega el menú de la base, el de respaldo se ve pero no se puede
       tocar: si no, un cliente rápido agregaba al carrito un plato con el
       precio viejo del HTML, justo antes de que llegara el precio nuevo. */
    function listo() {
        contenedor.classList.remove('menu-cargando');
    }

    function pedirElMenu() {
        if (typeof AbortController === 'undefined') return sinControlTimeout();
        contenedor.classList.add('menu-cargando');
        var control = new AbortController();
        var reloj = setTimeout(function () { control.abort(); }, TIEMPO_MAXIMO);
        fetch('/api/menu', { signal: control.signal })
            .then(function (respuesta) {
                clearTimeout(reloj);
                if (!respuesta.ok) throw new Error('el servidor respondió ' + respuesta.status);
                return respuesta.json();
            })
            .then(function (datos) {
                /* desde_base viene false cuando el servidor no pudo leer la
                   base (no hay internet, la base está caída, o todavía no se
                   configuró la URL). En ese caso no se toca el HTML. */
                if (datos && datos.desde_base && datos.categorias && datos.categorias.length) {
                    dibujar(datos.categorias);
                }
                listo();
            })
            .catch(function () {
                clearTimeout(reloj);
                // Sin base: el menú escrito en el HTML es el que queda. No se
                // avisa nada al cliente, porque igual puede pedir.
                listo();
            });
    }

    /* En los navegadores viejos no hay AbortController. Se hace igual, sin
       límite de tiempo. */
    function sinControlTimeout() {
        fetch('/api/menu')
            .then(function (r) { return r.json(); })
            .then(function (datos) {
                if (datos && datos.desde_base && datos.categorias && datos.categorias.length) {
                    dibujar(datos.categorias);
                }
            })
            .catch(function () {});
    }

    pedirElMenu();
})();
