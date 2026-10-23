/* EDITOR DEL MENÚ — MODO HAMBRE
 *
 * Esta pantalla es la que usa el dueño para cambiar categorias, comidas,
 * gustos y fotos. Lo que se guarda acá es lo que ven los clientes en la web.
 *
 * Se arma en tres columnas: las categorias a la izquierda, las comidas de la
 * categoria elegida en el medio (como tarjetas con su foto) y a la derecha el
 * panel para editar lo que se tocó. En pantallas chicas el panel se abre
 * encima, como una hoja.
 *
 * Dos decisiones que conviene no deshacer:
 *
 *   - Las fotos no se suben al elegirlas, sino al guardar. Si el dueño se
 *     equivoca y cancela, no queda ninguna foto huérfana ocupando espacio en
 *     la base.
 *
 *   - Todo lo que se manda al servidor lleva la cabecera de la clave
 *     (PanelClave). El servidor la pide en todas las rutas /api/admin/.
 */

var listaCategorias = document.getElementById('lista-categorias');
var cabecera = document.getElementById('cabecera-categoria');
var grilla = document.getElementById('grilla-comidas');
var vacio = document.getElementById('vacio');
var buscador = document.getElementById('buscar');
var panel = document.getElementById('panel');
var panelNada = document.getElementById('panel-nada');
var panelForm = document.getElementById('panel-form');
var panelFondo = document.getElementById('panel-fondo');
var avisoCaja = document.getElementById('aviso');
var estadoMenu = document.getElementById('estado-menu');

var categorias = [];
var yaCargo = false;
var cargando = false;
var otraVez = false;

var elegida = null;      // id de la categoria que se ve en el medio
var filtro = 'todas';    // todas | visibles | ocultas
var busqueda = '';

// Lo que esta abierto en el panel: { que: 'comida' | 'categoria', id }.
// id es null cuando es nuevo.
var editando = null;
var sucio = false;       // hay cambios sin guardar en el panel
var sacarLaFoto = false;
var fotoNueva = null;
var avisoReloj = null;

var EMOJIS = ['🥟', '🍔', '🍕', '🥩', '🍝', '🍗', '🔥', '🍰', '🍟', '🌭', '🌮', '🥗',
    '🥪', '🍣', '🍜', '🍦', '🧁', '🍩', '🥐', '🍳', '🥤', '🍺', '🍷', '☕'];

/* Los dibujitos de los botones. Van escritos acá para no depender de una
   librería de íconos de afuera. */
var ICONO = {
    lapiz: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m13.5 6.5 4 4"/></svg>',
    tacho: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
    mas: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    cruz: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    menos: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 12h8"/></svg>',
    foto: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 8"/></svg>',
    agarre: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="6" r="1.4"/><circle cx="15" cy="6" r="1.4"/><circle cx="9" cy="12" r="1.4"/><circle cx="15" cy="12" r="1.4"/><circle cx="9" cy="18" r="1.4"/><circle cx="15" cy="18" r="1.4"/></svg>'
};

/* ------------------------------------------------------------------ */
/* CHICHARRES                                                         */
/* ------------------------------------------------------------------ */

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

/* El dueño escribe los precios como le sale: "1500", "1.500", "$ 1.500".
   Devuelve el numero, o null si no se entiende. */
function numero(texto) {
    var limpio = String(texto == null ? '' : texto)
        .replace(/\$/g, '')
        .replace(/\s/g, '')
        .replace(/\./g, '')
        .replace(',', '.');
    if (limpio === '') return null;
    var valor = Number(limpio);
    return isFinite(valor) && valor >= 0 ? valor : null;
}

function plural(cantidad, uno, varios) {
    return cantidad + ' ' + (cantidad === 1 ? uno : varios);
}

/* Un cartelito abajo que se va solo. Los errores quedan más tiempo. */
function avisar(texto, malo) {
    clearTimeout(avisoReloj);
    avisoCaja.textContent = texto;
    avisoCaja.className = 'aviso' + (malo ? ' aviso-mal' : '');
    avisoCaja.hidden = false;
    avisoReloj = setTimeout(function () {
        avisoCaja.hidden = true;
    }, malo ? 7000 : 2500);
}

function estado(texto, clase) {
    estadoMenu.textContent = texto;
    estadoMenu.className = 'admin-conexion' + (clase ? ' ' + clase : '');
}

/* ------------------------------------------------------------------ */
/* HABLAR CON EL SERVIDOR                                             */
/* ------------------------------------------------------------------ */

async function pedir(ruta, opciones) {
    var config = opciones || {};
    config.headers = PanelClave.cabeceras(config.headers);
    var respuesta = await fetch(ruta, config);
    if (respuesta.status === 401) {
        PanelClave.errorDeClave();
        throw new Error('sin_clave');
    }
    var datos = null;
    try {
        datos = await respuesta.json();
    } catch (e) {}
    if (!respuesta.ok) {
        throw new Error((datos && datos.error) || 'el servidor no dijo que paso');
    }
    return datos;
}

function conCuerpo(ruta, metodo, cuerpo) {
    return pedir(ruta, {
        method: metodo,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cuerpo)
    });
}

async function subirFoto(archivo) {
    var datos = new FormData();
    datos.append('archivo', archivo);
    var leido = await pedir('/api/admin/imagenes', { method: 'POST', body: datos });
    if (!leido) throw new Error('no se pudo subir la foto');
    return leido.id;
}

/* ------------------------------------------------------------------ */
/* LEER EL MENÚ                                                       */
/* ------------------------------------------------------------------ */

async function cargar() {
    if (cargando) {
        // Ya se esta leyendo, pero puede ser una lectura de antes del ultimo
        // cambio: se vuelve a leer cuando termine, para no mostrar lo viejo.
        otraVez = true;
        return;
    }
    cargando = true;
    otraVez = false;
    if (!yaCargo) estado('Leyendo…');
    try {
        var datos = await pedir('/api/admin/menu');
        categorias = (datos && datos.categorias) || [];
        yaCargo = true;
        estado('Conectado', 'ok');
        if (!buscarCategoria(elegida)) {
            elegida = categorias.length ? categorias[0].id : null;
        }
        dibujar();
    } catch (error) {
        if (error.message === 'sin_clave') {
            // Todavia no se escribió la clave: se reintenta cada tanto, porque
            // el dueño puede estar escribiendo.
            estado('Esperando la clave');
            setTimeout(cargar, 2500);
            return;
        }
        estado('Sin base de datos', 'rojo');
        if (!yaCargo) {
            mostrarVacio('⚠️', 'No se pudo leer el menu', error.message);
        } else {
            avisar('No se pudo leer el menu: ' + error.message, true);
        }
    } finally {
        cargando = false;
        if (otraVez) cargar();
    }
}

function buscarCategoria(id) {
    for (var i = 0; i < categorias.length; i++) {
        if (categorias[i].id === id) return categorias[i];
    }
    return null;
}

function buscarComida(id) {
    for (var i = 0; i < categorias.length; i++) {
        var comidas = categorias[i].comidas || [];
        for (var j = 0; j < comidas.length; j++) {
            if (comidas[j].id === id) return comidas[j];
        }
    }
    return null;
}

/* ------------------------------------------------------------------ */
/* DIBUJAR                                                            */
/* ------------------------------------------------------------------ */

function dibujar() {
    dibujarCategorias();
    dibujarComidas();
}

function dibujarCategorias() {
    listaCategorias.innerHTML = categorias.map(function (categoria) {
        var cuantas = (categoria.comidas || []).length;
        return '<li class="categoria ordenable' + (categoria.id === elegida ? ' elegida' : '') +
            '" data-id="' + categoria.id + '">' +
            '  <span class="agarre" title="Arrastrá para cambiar el orden">' + ICONO.agarre + '</span>' +
            '  <button class="categoria-boton" type="button" data-accion="elegir">' +
            '    <span class="categoria-emoji">' + esc(categoria.icono || '🍽️') + '</span>' +
            '    <span class="categoria-nombre">' + esc(categoria.nombre) + '</span>' +
            '    <span class="categoria-cuenta">' + cuantas + '</span>' +
            '  </button>' +
            '  <button class="icono-boton" type="button" data-accion="editar-categoria"' +
            '          title="Editar ' + esc(categoria.nombre) + '">' + ICONO.lapiz + '</button>' +
            '</li>';
    }).join('');
}

function mostrarVacio(icono, titulo, texto, boton) {
    grilla.innerHTML = '';
    vacio.hidden = false;
    vacio.innerHTML =
        '<span class="vacio-icono">' + icono + '</span>' +
        '<p class="vacio-titulo">' + esc(titulo) + '</p>' +
        (texto ? '<p class="vacio-texto">' + esc(texto) + '</p>' : '') +
        (boton || '');
}

function pasaElFiltro(comida) {
    if (filtro === 'visibles') return comida.activo;
    if (filtro === 'ocultas') return !comida.activo;
    return true;
}

/* Solo se puede arrastrar cuando se ven todas las comidas de la categoria:
   con un filtro o una busqueda faltan tarjetas, y el orden quedaria mal. */
function sePuedeOrdenar() {
    return filtro === 'todas' && !busqueda;
}

function dibujarComidas() {
    vacio.hidden = true;

    if (!categorias.length) {
        cabecera.innerHTML = '';
        mostrarVacio('🍽️', 'Todavía no hay nada en el menu',
            'Empezá creando una categoría, por ejemplo “Empanadas” o “Pizzas”.',
            '<button class="boton-naranja" type="button" data-accion="nueva-categoria">' +
            ICONO.mas + ' Agregar categoría</button>');
        return;
    }

    var comidas;
    var categoria = buscarCategoria(elegida);

    if (busqueda) {
        // La busqueda mira todo el menu, no solo la categoria elegida.
        comidas = [];
        var texto = busqueda.toLowerCase();
        categorias.forEach(function (cat) {
            (cat.comidas || []).forEach(function (comida) {
                if (comida.nombre.toLowerCase().indexOf(texto) !== -1 ||
                    (comida.descripcion || '').toLowerCase().indexOf(texto) !== -1) {
                    comidas.push(comida);
                }
            });
        });
        comidas = comidas.filter(pasaElFiltro);
        cabecera.innerHTML =
            '<div class="cabecera-datos">' +
            '  <h2>Resultados para “' + esc(busqueda) + '”</h2>' +
            '  <p class="caja-sub">' + plural(comidas.length, 'comida encontrada', 'comidas encontradas') + '</p>' +
            '</div>';
    } else {
        var todas = categoria.comidas || [];
        var visibles = todas.filter(function (comida) { return comida.activo; }).length;
        comidas = todas.filter(pasaElFiltro);
        cabecera.innerHTML =
            '<span class="cabecera-emoji">' + esc(categoria.icono || '🍽️') + '</span>' +
            '<div class="cabecera-datos">' +
            '  <h2>' + esc(categoria.nombre) + '</h2>' +
            '  <p class="caja-sub">' + plural(todas.length, 'comida', 'comidas') + ' · ' +
            plural(visibles, 'visible', 'visibles') + '</p>' +
            '</div>' +
            '<div class="cabecera-botones">' +
            '  <button class="boton-blanco" type="button" data-accion="editar-categoria">' +
            ICONO.lapiz + ' Editar categoría</button>' +
            '  <button class="boton-naranja" type="button" data-accion="nueva-comida">' +
            ICONO.mas + ' Agregar comida</button>' +
            '</div>';
    }

    grilla.classList.toggle('sin-orden', !sePuedeOrdenar());
    grilla.innerHTML = comidas.map(tarjetaComida).join('');

    if (!comidas.length) {
        if (busqueda) {
            mostrarVacio('🔍', 'No se encontró ninguna comida', 'Probá con otra palabra.');
        } else if (filtro !== 'todas') {
            mostrarVacio('👀', filtro === 'ocultas' ? 'No hay comidas ocultas' : 'No hay comidas visibles',
                'Tocá “Todas” para ver todas las comidas de esta categoría.');
        } else {
            mostrarVacio('🍽️', 'Esta categoría está vacía', 'Agregale la primera comida.',
                '<button class="boton-naranja" type="button" data-accion="nueva-comida">' +
                ICONO.mas + ' Agregar comida</button>');
        }
    }
}

function textoDelPrecio(comida) {
    if (comida.tipo === 'gustos') {
        var gustos = comida.gustos || [];
        if (!gustos.length) return { precio: 'Sin gustos', abajo: 'Agregale gustos' };
        var minimo = Math.min.apply(null, gustos.map(function (g) { return Number(g.precio) || 0; }));
        return { precio: 'Desde ' + conPrecio(minimo), abajo: plural(gustos.length, 'gusto', 'gustos') };
    }
    return { precio: conPrecio(comida.precio), abajo: 'Precio único' };
}

function tarjetaComida(comida) {
    var categoria = buscarCategoria(comida.categoria_id);
    var precio = textoDelPrecio(comida);
    var abierta = editando && editando.que === 'comida' && editando.id === comida.id;
    var foto = comida.imagen_url
        ? '<img src="' + esc(comida.imagen_url) + '" alt="" loading="lazy">'
        : '<span class="tarjeta-sin-foto">' + esc((categoria && categoria.icono) || '🍽️') + '</span>';

    return '<article class="tarjeta ordenable' + (comida.activo ? '' : ' oculta') +
        (abierta ? ' abierta' : '') + '" data-id="' + comida.id + '">' +
        '  <button class="tarjeta-foto" type="button" data-accion="editar-comida" tabindex="-1">' + foto +
        (busqueda && categoria ? '<span class="tarjeta-etiqueta">' + esc(categoria.nombre) + '</span>' : '') +
        '  </button>' +
        '  <div class="tarjeta-cuerpo">' +
        '    <div class="tarjeta-arriba">' +
        '      <span class="agarre" title="Arrastrá para cambiar el orden">' + ICONO.agarre + '</span>' +
        '      <h3 class="tarjeta-nombre">' + esc(comida.nombre) + '</h3>' +
        '      <label class="interruptor" title="Si lo apagás, los clientes no ven esta comida">' +
        '        <input type="checkbox" data-accion="visible"' + (comida.activo ? ' checked' : '') + '>' +
        '        <span class="interruptor-pista"></span>' +
        '        <span class="interruptor-texto">' + (comida.activo ? 'Visible' : 'Oculta') + '</span>' +
        '      </label>' +
        '    </div>' +
        '    <div class="tarjeta-abajo">' +
        '      <div class="tarjeta-precio">' +
        '        <b>' + esc(precio.precio) + '</b>' +
        '        <small>' + esc(precio.abajo) + '</small>' +
        '      </div>' +
        '      <button class="boton-blanco boton-chico" type="button" data-accion="editar-comida">' +
        ICONO.lapiz + ' Editar</button>' +
        '      <button class="icono-boton icono-peligro" type="button" data-accion="borrar-comida"' +
        '              title="Borrar ' + esc(comida.nombre) + '">' + ICONO.tacho + '</button>' +
        '    </div>' +
        '  </div>' +
        '</article>';
}

/* ------------------------------------------------------------------ */
/* CLICS                                                              */
/* ------------------------------------------------------------------ */

document.getElementById('agregar-categoria').addEventListener('click', function () {
    abrirCategoria(null);
});

listaCategorias.addEventListener('click', function (evento) {
    var boton = evento.target.closest('button[data-accion]');
    if (!boton) return;
    var id = parseInt(boton.closest('.categoria').dataset.id, 10);
    if (boton.dataset.accion === 'elegir') {
        elegirCategoria(id);
    } else if (boton.dataset.accion === 'editar-categoria') {
        abrirCategoria(buscarCategoria(id));
    }
});

function elegirCategoria(id) {
    elegida = id;
    // Al elegir una categoria se deja de buscar: si no, el dueño toca una
    // categoria y sigue viendo los resultados de la busqueda.
    if (busqueda) {
        busqueda = '';
        buscador.value = '';
    }
    dibujar();
}

/* Los botones de la cabecera, las tarjetas y el cartel de "vacio" usan el
   mismo manejador. */
function clicEnElMedio(evento) {
    var boton = evento.target.closest('[data-accion]');
    if (!boton || boton.tagName === 'INPUT') return;
    var tarjeta = boton.closest('.tarjeta');
    var comida = tarjeta ? buscarComida(parseInt(tarjeta.dataset.id, 10)) : null;
    var accion = boton.dataset.accion;

    if (accion === 'editar-comida' && comida) {
        abrirComida(comida);
    } else if (accion === 'borrar-comida' && comida) {
        borrarComida(comida);
    } else if (accion === 'nueva-comida') {
        abrirComida(null);
    } else if (accion === 'editar-categoria') {
        abrirCategoria(buscarCategoria(elegida));
    } else if (accion === 'nueva-categoria') {
        abrirCategoria(null);
    }
}

cabecera.addEventListener('click', clicEnElMedio);
grilla.addEventListener('click', clicEnElMedio);
vacio.addEventListener('click', clicEnElMedio);

grilla.addEventListener('change', function (evento) {
    var casilla = evento.target.closest('input[data-accion="visible"]');
    if (!casilla) return;
    var comida = buscarComida(parseInt(casilla.closest('.tarjeta').dataset.id, 10));
    if (comida) cambiarVisibilidad(comida, casilla.checked);
});

buscador.addEventListener('input', function () {
    busqueda = buscador.value.trim();
    dibujarComidas();
});

document.querySelectorAll('.filtro').forEach(function (boton) {
    boton.addEventListener('click', function () {
        filtro = boton.dataset.filtro;
        document.querySelectorAll('.filtro').forEach(function (otro) {
            otro.classList.toggle('activo', otro === boton);
        });
        dibujarComidas();
    });
});

/* ------------------------------------------------------------------ */
/* ARRASTRAR PARA ORDENAR                                             */
/* ------------------------------------------------------------------ */

/* Se arrastra desde la manijita (⠿). Se hace con eventos de puntero y no con
   el "drag and drop" del navegador porque ese no anda con el dedo en el
   celular. Mientras se arrastra, la tarjeta se va cambiando de lugar; al
   soltar, si el orden cambió, se avisa con la lista de ids nueva. */
function ordenable(contenedor, alSoltar) {
    function ids() {
        return Array.prototype.map.call(
            contenedor.querySelectorAll(':scope > .ordenable'),
            function (el) { return parseInt(el.dataset.id, 10); }
        );
    }

    contenedor.addEventListener('pointerdown', function (evento) {
        var agarre = evento.target.closest('.agarre');
        if (!agarre || contenedor.classList.contains('sin-orden')) return;
        var item = agarre.closest('.ordenable');
        if (!item || item.parentNode !== contenedor) return;
        evento.preventDefault();

        var antes = ids();
        var terminado = false;
        item.classList.add('arrastrando');
        try {
            agarre.setPointerCapture(evento.pointerId);
        } catch (e) {}

        function mover(ev) {
            var debajo = document.elementFromPoint(ev.clientX, ev.clientY);
            var otro = debajo && debajo.closest('.ordenable');
            if (!otro || otro === item || otro.parentNode !== contenedor) return;
            var hijos = Array.prototype.slice.call(contenedor.children);
            if (hijos.indexOf(item) < hijos.indexOf(otro)) {
                otro.after(item);
            } else {
                otro.before(item);
            }
        }

        function soltar() {
            if (terminado) return;
            terminado = true;
            agarre.removeEventListener('pointermove', mover);
            item.classList.remove('arrastrando');
            var despues = ids();
            if (despues.join() !== antes.join()) alSoltar(despues);
        }

        agarre.addEventListener('pointermove', mover);
        agarre.addEventListener('pointerup', soltar, { once: true });
        agarre.addEventListener('pointercancel', soltar, { once: true });
    });
}

/* Se manda la lista entera en el orden nuevo y el servidor numera 10, 20,
   30... (calcular un numero "entre los dos vecinos" dejaba de andar cuando
   dos quedaban con numeros pegados). */
async function guardarOrden(ruta, ids) {
    try {
        await conCuerpo(ruta, 'POST', { ids: ids });
        avisar('Orden guardado ✓');
    } catch (error) {
        if (error.message !== 'sin_clave') avisar('No se pudo mover: ' + error.message, true);
    }
    await cargar();
}

ordenable(listaCategorias, function (ids) {
    categorias.sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
    guardarOrden('/api/admin/categorias/reordenar', ids);
});

ordenable(grilla, function (ids) {
    var categoria = buscarCategoria(elegida);
    if (categoria) {
        categoria.comidas.sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
    }
    guardarOrden('/api/admin/comidas/reordenar', ids);
});

/* ------------------------------------------------------------------ */
/* BORRAR Y APAGAR                                                    */
/* ------------------------------------------------------------------ */

async function borrarComida(comida) {
    if (!confirm('¿Borrar "' + comida.nombre + '" del menu?\n\n' +
        'Si solo querés que no se vea por un tiempo, mejor apagá "Visible".\n' +
        'Los pedidos que los clientes ya hicieron no se tocan.')) {
        return;
    }
    try {
        await pedir('/api/admin/comidas/' + comida.id, { method: 'DELETE' });
        if (editando && editando.que === 'comida' && editando.id === comida.id) {
            cerrarPanel(true);
        }
        avisar('"' + comida.nombre + '" se borró');
        await cargar();
    } catch (error) {
        if (error.message !== 'sin_clave') avisar('No se pudo borrar: ' + error.message, true);
    }
}

async function borrarCategoria(categoria) {
    var comidas = categoria.comidas || [];
    var texto = comidas.length
        ? '¿Borrar "' + categoria.nombre + '" y sus ' + plural(comidas.length, 'comida', 'comidas') + '?'
        : '¿Borrar "' + categoria.nombre + '"?';
    if (!confirm(texto + '\n\nLos pedidos que los clientes ya hicieron no se tocan.')) return;
    try {
        await pedir('/api/admin/categorias/' + categoria.id, { method: 'DELETE' });
        cerrarPanel(true);
        if (elegida === categoria.id) elegida = null;
        avisar('"' + categoria.nombre + '" se borró');
        await cargar();
    } catch (error) {
        if (error.message !== 'sin_clave') avisar('No se pudo borrar: ' + error.message, true);
    }
}

/* Se cambia en pantalla al instante y despues se guarda. Si falla, vuelve
   como estaba. */
async function cambiarVisibilidad(comida, activo) {
    comida.activo = activo;
    dibujar();
    // Si esa comida esta abierta en el panel, que el panel diga lo mismo: si
    // no, al guardar el panel volveria a dejarla como estaba.
    if (editando && editando.que === 'comida' && editando.id === comida.id) {
        panelForm.querySelector('[name="activo"]').checked = activo;
    }
    try {
        await conCuerpo('/api/admin/comidas/' + comida.id, 'PUT', { activo: activo });
        avisar(activo ? '"' + comida.nombre + '" ya se ve en el menu' : '"' + comida.nombre + '" quedó oculta');
    } catch (error) {
        comida.activo = !activo;
        dibujar();
        if (error.message !== 'sin_clave') avisar('No se pudo cambiar: ' + error.message, true);
    }
}

/* ------------------------------------------------------------------ */
/* EL PANEL DE LA DERECHA                                             */
/* ------------------------------------------------------------------ */

/* Antes de cerrar o cambiar lo que se edita, si hay cambios sin guardar se
   pregunta. Es fácil tocar otra tarjeta sin querer y perder lo escrito. */
function puedoSoltarElPanel() {
    return !sucio || confirm('Tenés cambios sin guardar. ¿Salir sin guardarlos?');
}

function cerrarPanel(sinPreguntar) {
    if (!sinPreguntar && !puedoSoltarElPanel()) return false;
    editando = null;
    sucio = false;
    fotoNueva = null;
    panelForm.hidden = true;
    panelForm.innerHTML = '';
    panelNada.hidden = false;
    document.body.classList.remove('panel-abierto');
    panelFondo.hidden = true;
    dibujarComidas();
    return true;
}

function abrirPanel(que, id, html) {
    editando = { que: que, id: id };
    sucio = false;
    sacarLaFoto = false;
    fotoNueva = null;
    panelForm.innerHTML = html;
    panelForm.hidden = false;
    panelNada.hidden = true;
    panel.scrollTop = 0;
    document.body.classList.add('panel-abierto');
    panelFondo.hidden = false;
    dibujarComidas();
    var primero = panelForm.querySelector('input[type=text]');
    // En el celular no se enfoca solo: abriria el teclado tapando todo.
    if (primero && window.matchMedia('(min-width: 70rem)').matches) primero.focus();
}

function cabeceraPanel(titulo, subtitulo) {
    return '<div class="panel-cabecera">' +
        '  <div>' +
        '    <h2>' + esc(titulo) + '</h2>' +
        (subtitulo ? '<p class="caja-sub">' + esc(subtitulo) + '</p>' : '') +
        '  </div>' +
        '  <button class="icono-boton" type="button" data-accion="cerrar" title="Cerrar">' + ICONO.cruz + '</button>' +
        '</div>';
}

function piePanel(textoBorrar) {
    return '<div class="panel-pie">' +
        (textoBorrar
            ? '<button class="boton-borrar" type="button" data-accion="borrar" title="' + esc(textoBorrar) + '">' + ICONO.tacho + ' Eliminar</button>'
            : '<span></span>') +
        '  <div class="panel-pie-botones">' +
        '    <button class="boton-blanco" type="button" data-accion="cerrar">Cancelar</button>' +
        '    <button class="boton-naranja" type="submit">Guardar cambios</button>' +
        '  </div>' +
        '</div>';
}

panelForm.addEventListener('input', function () { sucio = true; });
panelForm.addEventListener('change', function () { sucio = true; });
panelFondo.addEventListener('click', function () { cerrarPanel(); });

document.addEventListener('keydown', function (evento) {
    if (evento.key === 'Escape' && editando) {
        evento.preventDefault();
        cerrarPanel();
    }
});

panelForm.addEventListener('submit', function (evento) {
    evento.preventDefault();
    if (!editando) return;
    guardar(editando.que === 'comida' ? guardarComida : guardarCategoria);
});

/* Un solo lugar por donde pasan todos los guardados: mientras se guarda no se
   puede tocar el boton, y si algo falla se dice cual fue el problema en vez de
   dejar la pantalla callada. */
async function guardar(trabajo) {
    var boton = panelForm.querySelector('[type=submit]');
    if (boton.disabled) return;
    boton.disabled = true;
    boton.textContent = 'Guardando…';
    estado('Guardando…');
    try {
        var listo = await trabajo();
        estado('Conectado', 'ok');
        if (listo) {
            avisar('Guardado ✓');
            cerrarPanel(true);
            await cargar();
        }
    } catch (error) {
        if (error.message === 'sin_clave') {
            estado('Esperando la clave');
        } else {
            estado('No se pudo guardar', 'rojo');
            avisar('No se pudo guardar: ' + error.message, true);
        }
    } finally {
        if (boton.isConnected) {
            boton.disabled = false;
            boton.textContent = 'Guardar cambios';
        }
    }
}

/* Marca un campo en rojo, lo enfoca y dice qué falta. */
function falta(campo, texto) {
    if (campo) {
        campo.classList.add('campo-mal');
        campo.focus();
        campo.addEventListener('input', function () {
            campo.classList.remove('campo-mal');
        }, { once: true });
    }
    avisar(texto, true);
    return false;
}

/* ------------------------------------------------------------------ */
/* EDITAR UNA CATEGORÍA                                               */
/* ------------------------------------------------------------------ */

function abrirCategoria(categoria) {
    if (!puedoSoltarElPanel()) return;
    var icono = categoria ? (categoria.icono || '') : '';
    var cuantas = categoria ? (categoria.comidas || []).length : 0;

    abrirPanel('categoria', categoria ? categoria.id : null,
        cabeceraPanel(categoria ? 'Editar categoría' : 'Nueva categoría',
            categoria ? plural(cuantas, 'comida', 'comidas') : 'Se agrega al final de la lista') +
        '<div class="panel-cuerpo">' +
        '  <label class="campo">' +
        '    <span>Nombre</span>' +
        '    <input type="text" name="nombre" maxlength="80"' +
        '           placeholder="Ej: Empanadas" value="' + esc(categoria ? categoria.nombre : '') + '">' +
        '  </label>' +
        '  <div class="campo">' +
        '    <span>Dibujito</span>' +
        '    <div class="emoji-elegido">' +
        '      <span class="emoji-grande" id="emoji-grande">' + esc(icono || '🍽️') + '</span>' +
        '      <p class="caja-sub">Es el que se ve al lado del nombre, en la web y acá. Tocá uno:</p>' +
        '    </div>' +
        '    <div class="emojis">' +
        EMOJIS.map(function (emoji) {
            return '<button type="button" class="emoji' + (emoji === icono ? ' elegido' : '') +
                '" data-emoji="' + emoji + '">' + emoji + '</button>';
        }).join('') +
        '    </div>' +
        '    <label class="emoji-otro">O pegá otro: ' +
        '      <input type="text" name="icono" maxlength="8" value="' + esc(icono) + '" placeholder="🍽️">' +
        '    </label>' +
        '  </div>' +
        '</div>' +
        piePanel(categoria ? 'Eliminar categoría' : '')
    );
}

async function guardarCategoria() {
    var campoNombre = panelForm.querySelector('[name="nombre"]');
    var cuerpo = {
        nombre: campoNombre.value.trim(),
        icono: panelForm.querySelector('[name="icono"]').value.trim()
    };
    if (!cuerpo.nombre) return falta(campoNombre, 'La categoría necesita un nombre.');

    if (editando.id) {
        await conCuerpo('/api/admin/categorias/' + editando.id, 'PUT', cuerpo);
    } else {
        var nueva = await conCuerpo('/api/admin/categorias', 'POST', cuerpo);
        // Se muestra la categoria recien creada, que es lo que el dueño va a
        // querer llenar ahora.
        if (nueva && nueva.id) elegida = nueva.id;
        busqueda = '';
        buscador.value = '';
    }
    return true;
}

/* ------------------------------------------------------------------ */
/* EDITAR UNA COMIDA                                                  */
/* ------------------------------------------------------------------ */

function filaGusto(gusto) {
    return '<div class="gusto" data-gusto-id="' + (gusto ? gusto.id : '') + '">' +
        '  <input type="text" name="gusto-nombre" maxlength="120"' +
        '         placeholder="Ej: Carne" value="' + esc(gusto ? gusto.nombre : '') + '">' +
        '  <span class="con-pesos"><input type="text" name="gusto-precio" inputmode="decimal"' +
        '         placeholder="0" value="' + esc(gusto ? gusto.precio : '') + '"></span>' +
        '  <button class="icono-boton icono-peligro" type="button" data-accion="quitar-gusto"' +
        '          title="Sacar este gusto">' + ICONO.menos + '</button>' +
        '</div>';
}

function vistaFoto(url) {
    return url
        ? '<img src="' + esc(url) + '" alt="">'
        : '<span class="foto-vacia">' + ICONO.foto + '<br>Sin foto</span>';
}

function abrirComida(comida) {
    if (!categorias.length) {
        avisar('Primero creá una categoría.', true);
        return;
    }
    if (!puedoSoltarElPanel()) return;

    var conGustos = comida ? comida.tipo === 'gustos' : false;
    var gustos = comida ? (comida.gustos || []) : [];
    var deDonde = comida ? comida.categoria_id : (elegida || categorias[0].id);
    var categoria = buscarCategoria(deDonde);
    var activo = comida ? comida.activo : true;

    abrirPanel('comida', comida ? comida.id : null,
        cabeceraPanel(comida ? 'Editar comida' : 'Nueva comida',
            (categoria ? categoria.nombre : '') + (comida ? ' / ' + comida.nombre : '')) +
        '<div class="panel-cuerpo">' +
        '  <div class="foto">' +
        '    <div class="foto-vista" id="foto-vista">' + vistaFoto(comida && comida.imagen_url) + '</div>' +
        '    <div class="foto-botones">' +
        '      <label class="boton-blanco">' + ICONO.foto + ' <span id="foto-texto">' +
        (comida && comida.imagen_url ? 'Cambiar foto' : 'Subir foto') + '</span>' +
        '        <input type="file" name="foto" accept="image/png,image/jpeg,image/webp,image/gif" hidden>' +
        '      </label>' +
        '      <button class="boton-texto" type="button" data-accion="quitar-foto"' +
        (comida && comida.imagen_url ? '' : ' hidden') + '>Quitar la foto</button>' +
        '    </div>' +
        '  </div>' +
        '  <label class="campo">' +
        '    <span>Nombre</span>' +
        '    <input type="text" name="nombre" maxlength="120"' +
        '           placeholder="Ej: Pizza 4 quesos" value="' + esc(comida ? comida.nombre : '') + '">' +
        '  </label>' +
        '  <label class="campo">' +
        '    <span>Descripción</span>' +
        '    <textarea name="descripcion" maxlength="400" rows="2"' +
        '              placeholder="Ej: Mozzarella, roquefort y parmesano">' +
        esc(comida ? comida.descripcion : '') + '</textarea>' +
        '  </label>' +
        '  <label class="campo">' +
        '    <span>Categoría</span>' +
        '    <select name="categoria_id">' +
        categorias.map(function (cat) {
            return '<option value="' + cat.id + '"' + (cat.id === deDonde ? ' selected' : '') + '>' +
                esc(cat.icono ? cat.icono + ' ' : '') + esc(cat.nombre) + '</option>';
        }).join('') +
        '    </select>' +
        '  </label>' +
        '  <div class="campo">' +
        '    <span class="campo-titulo">¿Cómo se cobra?</span>' +
        '    <div class="dos-opciones">' +
        '      <button type="button" class="opcion' + (conGustos ? '' : ' activa') + '" data-tipo="simple">Precio único</button>' +
        '      <button type="button" class="opcion' + (conGustos ? ' activa' : '') + '" data-tipo="gustos">Por gustos</button>' +
        '    </div>' +
        '  </div>' +
        '  <label class="campo" id="bloque-precio"' + (conGustos ? ' hidden' : '') + '>' +
        '    <span>Precio</span>' +
        '    <span class="con-pesos"><input type="text" name="precio" inputmode="decimal"' +
        '           placeholder="0" value="' + esc(comida && !conGustos ? comida.precio : '') + '"></span>' +
        '  </label>' +
        '  <div class="campo" id="bloque-gustos"' + (conGustos ? '' : ' hidden') + '>' +
        '    <div class="gustos-titulos"><span>Gusto</span><span>Precio</span><span></span></div>' +
        '    <div class="gustos" id="gustos">' +
        (gustos.length ? gustos.map(filaGusto).join('') : filaGusto(null)) +
        '    </div>' +
        '    <button class="boton-punteado" type="button" data-accion="sumar-gusto">+ Agregar gusto</button>' +
        '  </div>' +
        '  <label class="fila-visible">' +
        '    <span>' +
        '      <b>Visible en el menu</b>' +
        '      <small>Si lo apagás, los clientes no ven esta comida</small>' +
        '    </span>' +
        '    <span class="interruptor interruptor-grande">' +
        '      <input type="checkbox" name="activo"' + (activo ? ' checked' : '') + '>' +
        '      <span class="interruptor-pista"></span>' +
        '    </span>' +
        '  </label>' +
        '</div>' +
        piePanel(comida ? 'Eliminar comida' : '')
    );
}

/* Los botones de adentro del panel. */
panelForm.addEventListener('click', function (evento) {
    var boton = evento.target.closest('button');
    if (!boton || boton.type === 'submit') return;

    if (boton.dataset.tipo) {
        var conGustos = boton.dataset.tipo === 'gustos';
        panelForm.querySelectorAll('.opcion').forEach(function (opcion) {
            opcion.classList.toggle('activa', opcion === boton);
        });
        panelForm.querySelector('#bloque-precio').hidden = conGustos;
        panelForm.querySelector('#bloque-gustos').hidden = !conGustos;
        sucio = true;
        return;
    }

    if (boton.dataset.emoji) {
        panelForm.querySelector('[name="icono"]').value = boton.dataset.emoji;
        panelForm.querySelector('#emoji-grande').textContent = boton.dataset.emoji;
        panelForm.querySelectorAll('.emoji').forEach(function (otro) {
            otro.classList.toggle('elegido', otro === boton);
        });
        sucio = true;
        return;
    }

    var accion = boton.dataset.accion;
    if (accion === 'cerrar') {
        cerrarPanel();
    } else if (accion === 'borrar') {
        if (editando.que === 'comida') {
            borrarComida(buscarComida(editando.id));
        } else {
            borrarCategoria(buscarCategoria(editando.id));
        }
    } else if (accion === 'sumar-gusto') {
        var lista = panelForm.querySelector('#gustos');
        lista.insertAdjacentHTML('beforeend', filaGusto(null));
        lista.lastElementChild.querySelector('input').focus();
        sucio = true;
    } else if (accion === 'quitar-gusto') {
        var filas = panelForm.querySelectorAll('.gusto');
        if (filas.length > 1) {
            boton.closest('.gusto').remove();
        } else {
            // Siempre queda una fila: vaciarla es lo mismo que sacarla.
            filas[0].querySelectorAll('input').forEach(function (campo) { campo.value = ''; });
        }
        sucio = true;
    } else if (accion === 'quitar-foto') {
        panelForm.querySelector('#foto-vista').innerHTML = vistaFoto(null);
        panelForm.querySelector('[name="foto"]').value = '';
        panelForm.querySelector('#foto-texto').textContent = 'Subir foto';
        boton.hidden = true;
        fotoNueva = null;
        sacarLaFoto = true;
        sucio = true;
    }
});

/* La foto elegida se muestra al instante, sin esperar al guardar, para que
   el dueño vea que agarró la correcta. */
panelForm.addEventListener('change', function (evento) {
    if (evento.target.name === 'icono') {
        panelForm.querySelector('#emoji-grande').textContent = evento.target.value.trim() || '🍽️';
        return;
    }
    if (evento.target.name !== 'foto') return;
    var archivo = evento.target.files[0];
    if (!archivo) return;
    if (archivo.type.indexOf('image/') !== 0) {
        evento.target.value = '';
        avisar('Ese archivo no es una foto.', true);
        return;
    }
    fotoNueva = archivo;
    sacarLaFoto = false;
    panelForm.querySelector('#foto-vista').innerHTML = vistaFoto(URL.createObjectURL(archivo));
    panelForm.querySelector('#foto-texto').textContent = 'Cambiar foto';
    panelForm.querySelector('[data-accion="quitar-foto"]').hidden = false;
});

async function guardarComida() {
    var campoNombre = panelForm.querySelector('[name="nombre"]');
    var conGustos = panelForm.querySelector('.opcion.activa').dataset.tipo === 'gustos';
    var cuerpo = {
        categoria_id: parseInt(panelForm.querySelector('[name="categoria_id"]').value, 10),
        nombre: campoNombre.value.trim(),
        descripcion: panelForm.querySelector('[name="descripcion"]').value.trim(),
        tipo: conGustos ? 'gustos' : 'simple',
        activo: panelForm.querySelector('[name="activo"]').checked
    };
    if (!cuerpo.nombre) return falta(campoNombre, 'La comida necesita un nombre.');

    // Se revisa todo antes de mandar nada, asi no queda guardada a medias.
    var gustos = [];
    if (conGustos) {
        var filas = panelForm.querySelectorAll('.gusto');
        for (var i = 0; i < filas.length; i++) {
            var campoGusto = filas[i].querySelector('[name="gusto-nombre"]');
            var campoPrecio = filas[i].querySelector('[name="gusto-precio"]');
            var nombre = campoGusto.value.trim();
            if (!nombre && !campoPrecio.value.trim()) continue; // fila vacia
            if (!nombre) return falta(campoGusto, 'A un gusto le falta el nombre.');
            var precioGusto = numero(campoPrecio.value);
            if (precioGusto === null) return falta(campoPrecio, 'Al gusto "' + nombre + '" le falta el precio.');
            gustos.push({ id: filas[i].dataset.gustoId ? parseInt(filas[i].dataset.gustoId, 10) : null,
                nombre: nombre, precio: precioGusto });
        }
        if (!gustos.length) {
            return falta(panelForm.querySelector('[name="gusto-nombre"]'),
                'Poné al menos un gusto, o elegí "Precio único".');
        }
        // El precio de la comida queda como el del gusto mas barato: la web
        // usa el de cada gusto, pero asi no queda un precio viejo guardado.
        cuerpo.precio = Math.min.apply(null, gustos.map(function (g) { return g.precio; }));
    } else {
        var campoPrecioUnico = panelForm.querySelector('[name="precio"]');
        cuerpo.precio = numero(campoPrecioUnico.value);
        if (cuerpo.precio === null) return falta(campoPrecioUnico, 'Poné el precio de la comida.');
    }

    if (fotoNueva) {
        cuerpo.imagen = await subirFoto(fotoNueva);
    } else if (sacarLaFoto) {
        cuerpo.imagen = null;
    }

    var idComida = editando.id;
    if (idComida) {
        await conCuerpo('/api/admin/comidas/' + idComida, 'PUT', cuerpo);
    } else {
        var creada = await conCuerpo('/api/admin/comidas', 'POST', cuerpo);
        idComida = creada.id;
    }
    await guardarGustos(idComida, conGustos ? gustos : []);
    elegida = cuerpo.categoria_id;
    return true;
}

/* Los gustos se guardan de a uno y en orden: se actualiza lo que cambió, se
   agrega lo nuevo y se borra lo que estaba y ya no está. Antes salian todos a
   la vez, y los nuevos se peleaban por el mismo numero de orden (y abrian
   varias conexiones a la base al mismo tiempo). */
async function guardarGustos(comidaId, gustos) {
    var existentes = new Map();
    var comida = buscarComida(comidaId);
    if (comida) {
        (comida.gustos || []).forEach(function (gusto) {
            existentes.set(gusto.id, gusto);
        });
    }

    var seQuedan = new Set();
    for (var i = 0; i < gustos.length; i++) {
        var gusto = gustos[i];
        if (!gusto.id) {
            await conCuerpo('/api/admin/comidas/' + comidaId + '/gustos', 'POST',
                { nombre: gusto.nombre, precio: gusto.precio });
            continue;
        }
        seQuedan.add(gusto.id);
        var antes = existentes.get(gusto.id);
        if (antes && antes.nombre === gusto.nombre && Number(antes.precio) === gusto.precio) {
            continue; // no cambió, no se manda nada
        }
        await conCuerpo('/api/admin/gustos/' + gusto.id, 'PUT',
            { nombre: gusto.nombre, precio: gusto.precio });
    }

    // Lo que estaba y ya no esta (o todos, si la comida paso a un solo precio).
    var aBorrar = [];
    existentes.forEach(function (gusto, id) {
        if (!seQuedan.has(id)) aBorrar.push(id);
    });
    for (var j = 0; j < aBorrar.length; j++) {
        await pedir('/api/admin/gustos/' + aBorrar[j], { method: 'DELETE' });
    }
}

/* ------------------------------------------------------------------ */
/* ARRANQUE                                                           */
/* ------------------------------------------------------------------ */

mostrarVacio('⏳', 'Cargando el menu…');

/* Cuando el dueño escribe la clave y esta entra bien, hay que cargarle el
   menu: hasta entonces no se puede mostrar nada. */
PanelClave.alEntrar(function () {
    cargar();
});

if (PanelClave.obtener()) {
    cargar();
} else {
    estado('Esperando la clave');
    setTimeout(cargar, 2500);
}
