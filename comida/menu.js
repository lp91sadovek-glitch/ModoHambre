/* EDITOR DEL MENÚ — MODO HAMBRE
 *
 * Esta pantalla es la que usa el dueño para cambiar categorias, comidas,
 * gustos y fotos. Lo que se guarda acá es lo que ven los clientes en la web.
 *
 * Dos decisiones que conviene no deshacer:
 *
 *   - Las fotos no se suben al empezar a editarlas, sino al guardar. Si el
 *     dueño se equivoca y cierra la ventana, no queda ninguna foto huérfana
 *     ocupando espacio en la base.
 *
 *   - Todo lo que se manda al servidor lleva la cabecera de la clave
 *     (PanelClave). El servidor la pide en todas las rutas /api/admin/.
 */

var lista = document.getElementById('lista-categorias');
var vacio = document.getElementById('menu-vacio');
var aviso = document.getElementById('menu-aviso');
var estadoMenu = document.getElementById('estado-menu');

var categorias = [];
var cargando = false;
var otraVez = false;
var ventana = null;
var sacarLaFoto = false;

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

function decir(texto, malo) {
    aviso.hidden = !texto;
    aviso.textContent = texto || '';
    aviso.className = 'menu-aviso' + (malo ? ' menu-aviso-mal' : '');
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
    var respuesta = await fetch('/api/admin/imagenes', {
        method: 'POST',
        headers: PanelClave.cabeceras(),
        body: datos
    });
    if (respuesta.status === 401) {
        PanelClave.errorDeClave();
        throw new Error('sin_clave');
    }
    var leido = null;
    try {
        leido = await respuesta.json();
    } catch (e) {}
    if (!respuesta.ok || !leido) {
        throw new Error((leido && leido.error) || 'no se pudo subir la foto');
    }
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
    estado('Leyendo…');
    try {
        var datos = await pedir('/api/admin/menu');
        categorias = (datos && datos.categorias) || [];
        estado('Conectado', 'ok');
        decir('');
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
        decir('No se pudo leer el menu: ' + error.message, true);
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
    lista.innerHTML = '';
    vacio.hidden = categorias.length > 0;
    categorias.forEach(function (categoria, indice) {
        lista.appendChild(filaCategoria(categoria, indice));
    });
}

function botonMini(texto, titulo, opciones) {
    var desactivado = opciones && opciones.desactivado;
    var atributos = ' class="menu-mini' + (opciones && opciones.peligro ? ' menu-mini-peligro' : '') + '"' +
        ' type="button" title="' + esc(titulo) + '"' +
        (desactivado ? ' disabled' : '') +
        ' data-accion="' + esc(opciones.accion) + '"' +
        (opciones.dato != null ? ' data-valor="' + esc(opciones.dato) + '"' : '') +
        ' data-nombre="' + esc((opciones && opciones.nombre) || '') + '"' +
        (opciones && opciones.id != null ? ' data-id="' + opciones.id + '"' : '') +
        '>' + texto + '</button>';
    return atributos;
}

function filaCategoria(categoria, indice) {
    var comidas = categoria.comidas || [];
    var visibles = comidas.filter(function (comida) { return comida.activo; }).length;
    var caja = document.createElement('section');
    caja.className = 'menu-categoria';
    caja.innerHTML =
        '<header class="menu-categoria-cabecera">' +
        '  <span class="menu-categoria-icono">' + esc(categoria.icono || '🍽') + '</span>' +
        '  <h2 class="menu-categoria-nombre">' + esc(categoria.nombre) + '</h2>' +
        '  <span class="menu-categoria-cuenta">' + visibles + ' de ' + comidas.length +
        (comidas.length === 1 ? ' comida visible' : ' comidas visibles') + '</span>' +
        '  <span class="menu-categoria-botones">' +
        botonMini('▲', 'Subir ' + categoria.nombre, {
            accion: 'subir', dato: indice, desactivado: indice === 0
        }) +
        botonMini('▼', 'Bajar ' + categoria.nombre, {
            accion: 'bajar', dato: indice, desactivado: indice === categorias.length - 1
        }) +
        botonMini('+ Comida', 'Agregar una comida en ' + categoria.nombre, {
            accion: 'agregar-comida', id: categoria.id
        }) +
        botonMini('✏️', 'Editar ' + categoria.nombre, {
            accion: 'editar-categoria', id: categoria.id
        }) +
        botonMini('🗑', 'Borrar ' + categoria.nombre, {
            accion: 'borrar-categoria', id: categoria.id, nombre: categoria.nombre, peligro: true
        }) +
        '  </span>' +
        '</header>' +
        '<div class="menu-comidas"></div>';

    var donde = caja.querySelector('.menu-comidas');
    if (!comidas.length) {
        donde.innerHTML = '<p class="menu-sin-comidas">Todavía no hay comidas en esta categoría.</p>';
    } else {
        comidas.forEach(function (comida, posicion) {
            donde.appendChild(filaComida(comida, categoria, posicion, comidas.length));
        });
    }
    return caja;
}

function filaComida(comida, categoria, posicion, total) {
    var foto = comida.imagen_url
        ? '<img class="menu-comida-foto" src="' + esc(comida.imagen_url) + '" alt="" loading="lazy">'
        : '<span class="menu-comida-sin-foto">?</span>';

    var cuantos = (comida.gustos || []).length;
    var tipo = comida.tipo === 'gustos'
        ? 'con ' + cuantos + ' gusto' + (cuantos === 1 ? '' : 's')
        : 'un solo precio';

    var fila = document.createElement('article');
    fila.className = 'menu-comida' + (comida.activo ? '' : ' menu-comida-apagada');
    fila.dataset.categoria = categoria.id;
    fila.innerHTML =
        '<input class="menu-comida-visible" type="checkbox" data-accion="visibilidad"' +
        '       data-id="' + comida.id + '"' + (comida.activo ? ' checked' : '') +
        '       title="Si lo desmarcás, los clientes no ven esta comida">' +
        foto +
        '<div class="menu-comida-datos">' +
        '  <span class="menu-comida-nombre">' + esc(comida.nombre) + '</span>' +
        '  <span class="menu-comida-precio">' + conPrecio(comida.precio) + '</span>' +
        (comida.descripcion ? '<span class="menu-comida-descripcion">' + esc(comida.descripcion) + '</span>' : '') +
        '  <span class="menu-comida-tipo">' + esc(tipo) + '</span>' +
        '</div>' +
        '<span class="menu-comida-botones">' +
        botonMini('▲', 'Subir ' + comida.nombre, {
            accion: 'subir-comida', dato: posicion, desactivado: posicion === 0
        }) +
        botonMini('▼', 'Bajar ' + comida.nombre, {
            accion: 'bajar-comida', dato: posicion, desactivado: posicion === total - 1
        }) +
        botonMini('✏️', 'Editar ' + comida.nombre, {
            accion: 'editar-comida', id: comida.id
        }) +
        botonMini('🗑', 'Borrar ' + comida.nombre, {
            accion: 'borrar-comida', id: comida.id, nombre: comida.nombre, peligro: true
        }) +
        '</span>';
    return fila;
}

/* ------------------------------------------------------------------ */
/* CLICS                                                              */
/* ------------------------------------------------------------------ */

document.getElementById('agregar-categoria').addEventListener('click', function () {
    editarCategoria(null);
});

lista.addEventListener('click', function (evento) {
    var boton = evento.target.closest('button[data-accion]');
    if (!boton || boton.disabled) return;
    var accion = boton.dataset.accion;
    var id = parseInt(boton.dataset.id, 10);
    var valor = parseInt(boton.dataset.valor, 10);

    if (accion === 'editar-categoria') {
        editarCategoria(buscarCategoria(id));
    } else if (accion === 'borrar-categoria') {
        borrarCategoria(id, boton.dataset.nombre);
    } else if (accion === 'agregar-comida') {
        editarComida(null, id);
    } else if (accion === 'editar-comida') {
        editarComida(buscarComida(id));
    } else if (accion === 'borrar-comida') {
        borrarComida(id, boton.dataset.nombre);
    } else if (accion === 'subir' || accion === 'bajar') {
        moverCategoria(valor, accion === 'subir' ? -1 : 1);
    } else if (accion === 'subir-comida' || accion === 'bajar-comida') {
        moverComida(boton.closest('.menu-comida').dataset.categoria, valor,
            accion === 'subir-comida' ? -1 : 1);
    }
});

lista.addEventListener('change', function (evento) {
    var casilla = evento.target.closest('input[data-accion="visibilidad"]');
    if (casilla) cambiarVisibilidad(parseInt(casilla.dataset.id, 10), casilla.checked);
});

/* ------------------------------------------------------------------ */
/* MOVER                                                              */
/* ------------------------------------------------------------------ */

/* Se manda la lista entera en el orden nuevo y el servidor numera 10, 20,
   30... Antes, con las categorias, se calculaba un numero "entre los dos
   vecinos", y cuando dos quedaban con numeros pegados (10 y 11) el promedio
   daba el mismo y el boton dejaba de mover. */
async function moverEnLista(lista, indice, paso, ruta) {
    var destino = indice + paso;
    if (destino < 0 || destino >= lista.length) return;
    var nueva = lista.slice();
    var movida = nueva.splice(indice, 1)[0];
    nueva.splice(destino, 0, movida);
    try {
        await conCuerpo(ruta, 'POST', {
            ids: nueva.map(function (fila) { return fila.id; })
        });
        await cargar();
    } catch (error) {
        decir('No se pudo mover: ' + error.message, true);
    }
}

function moverCategoria(indice, paso) {
    return moverEnLista(categorias, indice, paso, '/api/admin/categorias/reordenar');
}

function moverComida(categoriaId, indice, paso) {
    var categoria = buscarCategoria(parseInt(categoriaId, 10));
    if (!categoria) return;
    return moverEnLista(categoria.comidas || [], indice, paso, '/api/admin/comidas/reordenar');
}

/* ------------------------------------------------------------------ */
/* BORRAR Y APAGAR                                                    */
/* ------------------------------------------------------------------ */

async function borrarCategoria(id, nombre) {
    var categoria = buscarCategoria(id);
    var comidas = (categoria && categoria.comidas) || [];
    var texto = comidas.length
        ? 'Se borra "' + nombre + '" y sus ' + comidas.length + ' comida' +
          (comidas.length === 1 ? '' : 's') + '.'
        : 'Se borra "' + nombre + '".';
    if (!confirm(texto + '\n\nLos pedidos que los clientes ya hicieron no se tocan.')) return;
    try {
        await pedir('/api/admin/categorias/' + id, { method: 'DELETE' });
        await cargar();
    } catch (error) {
        decir('No se pudo borrar: ' + error.message, true);
    }
}

async function borrarComida(id, nombre) {
    if (!confirm('Se borra "' + nombre + '" del menu.\n\nLos pedidos que los clientes ya hicieron no se tocan.')) {
        return;
    }
    try {
        await pedir('/api/admin/comidas/' + id, { method: 'DELETE' });
        await cargar();
    } catch (error) {
        decir('No se pudo borrar: ' + error.message, true);
    }
}

async function cambiarVisibilidad(id, activo) {
    try {
        await conCuerpo('/api/admin/comidas/' + id, 'PUT', { activo: activo });
        await cargar();
    } catch (error) {
        decir('No se pudo cambiar: ' + error.message, true);
        cargar();
    }
}

/* ------------------------------------------------------------------ */
/* LA VENTANA PARA EDITAR                                             */
/* ------------------------------------------------------------------ */

function cerrarVentana() {
    if (ventana && ventana.parentNode) ventana.parentNode.removeChild(ventana);
    ventana = null;
}

/* La ventana se arma con un <form> de verdad, asi Enter guarda y Escape
   cierra, como en cualquier formulario. El boton de Guardar esta adentro del
   form porque si esta afuera el Enter no hace nada. */
function abrirVentana(titulo, cuerpoHTML, alGuardar) {
    cerrarVentana();
    sacarLaFoto = false;

    ventana = document.createElement('div');
    ventana.className = 'editor-fondo';
    ventana.innerHTML =
        '<form class="editor-caja">' +
        '  <h2 class="editor-titulo">' + esc(titulo) + '</h2>' +
        '  <div class="editor-cuerpo">' + cuerpoHTML + '</div>' +
        '  <div class="editor-pie">' +
        '    <button class="editor-cancelar" type="button">Cancelar</button>' +
        '    <button class="editor-guardar" type="submit">Guardar</button>' +
        '  </div>' +
        '</form>';
    document.body.appendChild(ventana);

    var form = ventana.querySelector('form');
    ventana.querySelector('.editor-cancelar').addEventListener('click', cerrarVentana);
    form.addEventListener('submit', function (evento) {
        evento.preventDefault();
        guardar(form, alGuardar);
    });
    ventana.addEventListener('keydown', function (evento) {
        if (evento.key === 'Escape') {
            evento.preventDefault();
            cerrarVentana();
        }
    });

    var primero = form.querySelector('input:not([type=file]), select, textarea');
    if (primero) primero.focus();
    return ventana;
}

/* Un solo lugar por donde pasan todos los guardados: mientras se guarda no se
   puede tocar el boton, y si algo falla se dice cual fue el problema en vez de
   dejar la pantalla callada. */
async function guardar(form, alGuardar) {
    var boton = form.querySelector('.editor-guardar');
    if (boton.disabled) return;
    boton.disabled = true;
    boton.textContent = 'Guardando…';
    estado('Guardando…');
    try {
        await alGuardar(form);
        estado('Conectado', 'ok');
        await cargar();
    } catch (error) {
        if (error.message === 'sin_clave') {
            estado('Esperando la clave');
        } else {
            estado('No se pudo guardar', 'rojo');
            decir('No se pudo guardar: ' + error.message, true);
            alert('No se pudo guardar: ' + error.message);
        }
    } finally {
        if (boton.isConnected) {
            boton.disabled = false;
            boton.textContent = 'Guardar';
        }
    }
}

function valorDe(form, nombre) {
    var campo = form.querySelector('[name="' + nombre + '"]');
    return campo ? campo.value : '';
}

function marcadoDe(form, nombre) {
    var campo = form.querySelector('[name="' + nombre + '"]');
    return !!(campo && campo.checked);
}

/* ------------------------------------------------------------------ */
/* CATEGORÍAS                                                         */
/* ------------------------------------------------------------------ */

function editarCategoria(categoria) {
    var esNueva = !categoria;
    abrirVentana(
        esNueva ? 'Nueva categoría' : 'Editar categoría',
        '<label class="editor-campo">' +
        '  <span>Nombre</span>' +
        '  <input type="text" name="nombre" maxlength="80" required' +
        '         placeholder="Ej: Empanadas" value="' + esc(categoria ? categoria.nombre : '') + '">' +
        '</label>' +
        '<label class="editor-campo">' +
        '  <span>Emoji</span>' +
        '  <input type="text" name="icono" maxlength="8" class="editor-emoji"' +
        '         placeholder="🥟" value="' + esc(categoria ? categoria.icono : '') + '">' +
        '</label>' +
        '<p class="editor-ayuda">El emoji es el dibujo redondo que se ve arriba de cada categoría. ' +
        'Si lo dejás vacío se usa uno genérico.</p>',
        async function (form) {
            var cuerpo = {
                nombre: valorDe(form, 'nombre').trim(),
                icono: valorDe(form, 'icono').trim()
            };
            if (!cuerpo.nombre) {
                alert('La categoría necesita un nombre.');
                return;
            }
            if (esNueva) {
                await conCuerpo('/api/admin/categorias', 'POST', cuerpo);
            } else {
                await conCuerpo('/api/admin/categorias/' + categoria.id, 'PUT', cuerpo);
            }
            cerrarVentana();
        }
    );
}

/* ------------------------------------------------------------------ */
/* COMIDAS                                                            */
/* ------------------------------------------------------------------ */

function opcionesCategorias(elegida) {
    return categorias.map(function (categoria) {
        return '<option value="' + categoria.id + '"' +
            (categoria.id === elegida ? ' selected' : '') + '>' +
            esc(categoria.icono ? categoria.icono + ' ' : '') + esc(categoria.nombre) +
            '</option>';
    }).join('');
}

function filaGusto(gusto) {
    return '<div class="editor-gusto" data-gusto-id="' + (gusto ? gusto.id : '') + '">' +
        '  <input type="text" name="gusto-nombre" maxlength="120"' +
        '         placeholder="Ej: Carne" value="' + esc(gusto ? gusto.nombre : '') + '">' +
        '  <span class="editor-guion">$</span>' +
        '  <input type="number" name="gusto-precio" min="0" step="1" placeholder="0"' +
        '         value="' + esc(gusto ? gusto.precio : '') + '">' +
        '  <button class="editor-quitar" type="button" title="Sacar este gusto">✕</button>' +
        '</div>';
}

function editarComida(comida, categoriaId) {
    if (!categorias.length) {
        alert('Primero creá una categoría.');
        return;
    }
    var esNueva = !comida;
    var conGustos = comida ? comida.tipo === 'gustos' : false;
    var gustos = comida ? (comida.gustos || []) : [];
    var deDonde = comida ? comida.categoria_id : parseInt(categoriaId, 10);

    var ventanaNueva = abrirVentana(
        esNueva ? 'Nueva comida' : 'Editar "' + comida.nombre + '"',
        '<div class="editor-rejilla">' +
        '  <label class="editor-campo">' +
        '    <span>Categoría</span>' +
        '    <select name="categoria_id">' + opcionesCategorias(deDonde) + '</select>' +
        '  </label>' +
        '  <label class="editor-campo">' +
        '    <span>Precio</span>' +
        '    <input type="number" name="precio" min="0" step="1" placeholder="0"' +
        '           value="' + esc(comida ? comida.precio : '') + '">' +
        '  </label>' +
        '</div>' +
        '<label class="editor-campo">' +
        '  <span>Nombre</span>' +
        '  <input type="text" name="nombre" maxlength="120" required' +
        '         placeholder="Ej: Pizza 4 quesos" value="' + esc(comida ? comida.nombre : '') + '">' +
        '</label>' +
        '<label class="editor-campo">' +
        '  <span>Descripción <small>lo que se ve abajo del nombre, en la web</small></span>' +
        '  <textarea name="descripcion" maxlength="400" rows="2"' +
        '            placeholder="Ej: Mozzarella, gorgonzola, parmesano y azul">' +
        esc(comida ? comida.descripcion : '') + '</textarea>' +
        '</label>' +
        '<div class="editor-foto">' +
        '  <div class="editor-foto-vista" id="foto-vista">' +
        (comida && comida.imagen_url
            ? '<img src="' + esc(comida.imagen_url) + '" alt="">'
            : '<span class="editor-foto-vacia">Sin foto</span>') +
        '  </div>' +
        '  <div class="editor-foto-controles">' +
        '    <input type="file" name="foto" accept="image/png,image/jpeg,image/webp,image/gif">' +
        '    <button class="editor-mini" type="button" id="quitar-foto">Quitar la foto</button>' +
        '    <p class="editor-ayuda">Se achica sola antes de guardarse. Si no elegís una, ' +
        'se deja la que ya tenía.</p>' +
        '  </div>' +
        '</div>' +
        '<fieldset class="editor-tipo">' +
        '  <legend>Cómo se cobra</legend>' +
        '  <label><input type="radio" name="tipo" value="simple"' +
        (conGustos ? '' : ' checked') + '> Un solo precio</label>' +
        '  <label><input type="radio" name="tipo" value="gustos"' +
        (conGustos ? ' checked' : '') + '> El cliente elige el gusto, cada uno con su precio</label>' +
        '</fieldset>' +
        '<div class="editor-gustos"' + (conGustos ? '' : ' hidden') + '>' +
        '  <p class="editor-ayuda">Lo que se le ofrece al cliente para elegir, con su precio.</p>' +
        '  <div class="editor-gustos-lista">' +
        (gustos.length ? gustos.map(filaGusto).join('') : filaGusto(null)) +
        '  </div>' +
        '  <button class="editor-mini" type="button" id="sumar-gusto">+ Agregar gusto</button>' +
        '</div>' +
        '<label class="editor-check">' +
        '  <input type="checkbox" name="activo"' + (!comida || comida.activo ? ' checked' : '') + '>' +
        '  <span>Los clientes ven esta comida</span>' +
        '</label>',
        async function (form) {
            var cuerpo = {
                categoria_id: parseInt(valorDe(form, 'categoria_id'), 10),
                nombre: valorDe(form, 'nombre').trim(),
                descripcion: valorDe(form, 'descripcion').trim(),
                precio: valorDe(form, 'precio'),
                tipo: form.querySelector('[name="tipo"]:checked').value,
                activo: marcadoDe(form, 'activo')
            };
            if (!cuerpo.nombre) {
                alert('La comida necesita un nombre.');
                return;
            }

            var archivo = form.querySelector('[name="foto"]').files[0];
            if (archivo) {
                cuerpo.imagen = await subirFoto(archivo);
            } else if (sacarLaFoto) {
                cuerpo.imagen = null;
            }

            var idComida = comida ? comida.id : null;
            if (idComida) {
                await conCuerpo('/api/admin/comidas/' + idComida, 'PUT', cuerpo);
            } else {
                var creada = await conCuerpo('/api/admin/comidas', 'POST', cuerpo);
                idComida = creada.id;
            }
            await guardarGustos(form, idComida, cuerpo.tipo === 'gustos');
            cerrarVentana();
        }
    );

    /* La foto elegida se muestra al instante, sin esperar al guardar, para que
       el dueño vea que agarro la correcta. */
    ventanaNueva.querySelector('[name="foto"]').addEventListener('change', function () {
        var archivo = this.files[0];
        if (!archivo) return;
        var vista = ventanaNueva.querySelector('#foto-vista');
        var previa = URL.createObjectURL(archivo);
        if (vista.querySelector('img')) {
            vista.querySelector('img').src = previa;
        } else {
            vista.innerHTML = '<img src="' + previa + '" alt="">';
        }
        sacarLaFoto = false;
    });

    ventanaNueva.querySelector('#quitar-foto').addEventListener('click', function () {
        ventanaNueva.querySelector('#foto-vista').innerHTML =
            '<span class="editor-foto-vacia">Sin foto</span>';
        ventanaNueva.querySelector('[name="foto"]').value = '';
        sacarLaFoto = true;
    });

    ventanaNueva.querySelector('#sumar-gusto').addEventListener('click', function () {
        ventanaNueva.querySelector('.editor-gustos-lista')
            .insertAdjacentHTML('beforeend', filaGusto(null));
    });

    ventanaNueva.querySelector('.editor-gustos-lista').addEventListener('click', function (evento) {
        var quitar = evento.target.closest('.editor-quitar');
        if (!quitar) return;
        var todas = this.querySelectorAll('.editor-gusto');
        if (todas.length > 1) {
            quitar.closest('.editor-gusto').remove();
        } else {
            alert('Si no querés poner gustos, dejá la comida en "un solo precio".');
        }
    });

    ventanaNueva.querySelectorAll('[name="tipo"]').forEach(function (radio) {
        radio.addEventListener('change', function () {
            ventanaNueva.querySelector('.editor-gustos').hidden = this.value !== 'gustos';
        });
    });
}

/* Los gustos se guardan de a uno: se actualiza lo que cambió, se agrega lo
   nuevo y se borra lo que estaba y ya no está en la ventana. Con dos o tres
   gustos por comida no vale la pena hacerlo de otra forma, y así el dueño
   puede agregar y sacar sin complicarse. */
async function guardarGustos(form, comidaId, conGustos) {
    var existentes = new Map();
    var comida = buscarComida(comidaId);
    if (comida) {
        (comida.gustos || []).forEach(function (gusto) {
            existentes.set(gusto.id, gusto);
        });
    }

    var filas = Array.prototype.slice.call(form.querySelectorAll('.editor-gusto'));
    var seQuedan = new Set();
    // Se guardan funciones y no pedidos ya lanzados: antes salian todos a la
    // vez, y los gustos nuevos se peleaban por el mismo numero de orden (y
    // abrian varias conexiones a la base al mismo tiempo).
    var trabajo = [];

    filas.forEach(function (fila) {
        var nombre = fila.querySelector('[name="gusto-nombre"]').value.trim();
        var precio = fila.querySelector('[name="gusto-precio"]').value;
        var idGusto = fila.dataset.gustoId ? parseInt(fila.dataset.gustoId, 10) : null;
        // Un gusto que ya existia y quedo sin nombre no se guarda: como no
        // entra en seQuedan, mas abajo se borra.
        if (!nombre) return;

        if (!conGustos) return;
        seQuedan.add(idGusto);
        if (!idGusto) {
            trabajo.push(function () {
                return conCuerpo('/api/admin/comidas/' + comidaId + '/gustos', 'POST',
                    { nombre: nombre, precio: precio });
            });
            return;
        }
        var antes = existentes.get(idGusto);
        if (antes && antes.nombre === nombre && String(antes.precio) === String(precio)) {
            return; // no cambió, no se manda nada
        }
        trabajo.push(function () {
            return conCuerpo('/api/admin/gustos/' + idGusto, 'PUT',
                { nombre: nombre, precio: precio });
        });
    });

    // Lo que estaba y ya no esta (o todos, si la comida paso a un solo precio).
    existentes.forEach(function (gusto, id) {
        if (!seQuedan.has(id)) {
            trabajo.push(function () {
                return pedir('/api/admin/gustos/' + id, { method: 'DELETE' });
            });
        }
    });

    for (var i = 0; i < trabajo.length; i++) {
        await trabajo[i]();
    }
}

/* ------------------------------------------------------------------ */
/* ARRANQUE                                                           */
/* ------------------------------------------------------------------ */

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
