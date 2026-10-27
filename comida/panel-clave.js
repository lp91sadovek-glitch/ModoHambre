/* MODO HAMBRE — CLAVE DEL PANEL
 *
 * El panel de pedidos muestra datos de los clientes (nombre, telefono y
 * direccion), asi que el servidor pide una clave antes de devolverlos. Este
 * archivo se encarga de eso en las dos paginas del dueno: admin.html y
 * archivo.html.
 *
 * Funciona como el bloqueo de pantalla del celular: la clave queda solo en la
 * memoria de la pestaña abierta. Si se actualiza la página, se cierra la
 * pestaña o se pasa a otra página del panel, se vuelve a pedir.
 */

var PanelClave = (function () {
    var LLAVE = 'modo-hambre-clave';
    var CABECERA = 'X-Clave-Panel';

    // La clave vive solo acá: al recargar o cerrar la pestaña se pierde.
    var enMemoria = '';

    // Antes la clave quedaba guardada en el navegador: se borra la que haya.
    try { window.localStorage.removeItem(LLAVE); } catch (e) {}

    /* Un número al azar que identifica a este navegador. Si desde un equipo
       nuevo se escribe mal la clave 5 veces, el servidor bloquea este número
       hasta que un desarrollador lo habilite. */
    var dispositivo = (function () {
        var llave = 'modo-hambre-dispositivo';
        try {
            var guardado = window.localStorage.getItem(llave);
            if (guardado) return guardado;
        } catch (e) {}
        var bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        var nuevo = Array.prototype.map.call(bytes, function (b) {
            return ('0' + b.toString(16)).slice(-2);
        }).join('');
        try { window.localStorage.setItem(llave, nuevo); } catch (e) {}
        return nuevo;
    })();

    // Funciones que se avisan cuando la clave queda aceptada. Las usa el editor
    // del menu, que no puede mostrar nada hasta que entra la clave.
    var alEntrar = [];

    function id(nombre) {
        return document.getElementById(nombre);
    }

    function obtener() {
        return enMemoria;
    }

    function guardar(clave) {
        enMemoria = clave || '';
    }

    /* Se agrega a cada pedido al host. Sin esto el servidor responde 401. */
    function cabeceras(adicionales) {
        var cabeceras = { 'X-Dispositivo': dispositivo };
        var clave = obtener();
        if (clave) cabeceras[CABECERA] = clave;
        if (adicionales) {
            for (var campo in adicionales) {
                if (Object.prototype.hasOwnProperty.call(adicionales, campo)) {
                    cabeceras[campo] = adicionales[campo];
                }
            }
        }
        return cabeceras;
    }

    function mostrar(mensaje) {
        var fondo = id('clave-fondo');
        if (fondo) fondo.hidden = false;
        var caja = id('clave-error');
        if (caja) caja.textContent = mensaje || '';
    }

    function ocultar() {
        var fondo = id('clave-fondo');
        if (fondo) fondo.hidden = true;
        var caja = id('clave-error');
        if (caja) caja.textContent = '';
    }

    /* Se avisa a las paginas que estaban esperando la clave. Si una falla no
       se corta el resto: son paginas distintas y una rota no puede tappingar
       la entrada de las otras. */
    function avisarQueEntro() {
        for (var i = 0; i < alEntrar.length; i++) {
            try {
                alEntrar[i]();
            } catch (e) {}
        }
    }

    function comprobar(alAceptar) {
        var entrada = id('clave-input');
        if (!entrada) return;
        var clave = (entrada.value || '').trim();
        if (!clave) {
            mostrar('Escribí la clave del local.');
            return;
        }

        mostrar('Comprobando...');
        var cabecerasPrueba = cabeceras();
        cabecerasPrueba[CABECERA] = clave;
        fetch('/api/panel/estado', { headers: cabecerasPrueba })
            .then(async function (respuesta) {
                if (!respuesta.ok) {
                    guardar('');
                    // El servidor dice cuántos intentos quedan, o que se
                    // bloqueó por 15 minutos después de 5 claves equivocadas.
                    var datos = {};
                    try { datos = await respuesta.json(); } catch (e) {}
                    if (datos.codigo === 'dispositivo_bloqueado') {
                        mostrarDispositivoBloqueado();
                        return;
                    }
                    if (respuesta.status === 429 || respuesta.status === 403) {
                        mostrar(datos.error || 'Demasiados intentos. Esperá unos minutos.');
                    } else if (datos.intentos_restantes != null) {
                        mostrar(datos.mensaje || ('Esa clave no es correcta. Te quedan ' + datos.intentos_restantes +
                            (datos.intentos_restantes === 1 ? ' intento.' : ' intentos.')));
                    } else {
                        mostrar('Esa clave no es correcta.');
                    }
                    if (entrada) {
                        entrada.value = '';
                        entrada.focus();
                    }
                    return;
                }
                guardar(clave);
                ocultar();
                avisarQueEntro();
                if (alAceptar) alAceptar();
            })
            .catch(function () {
                guardar('');
                mostrar('No se pudo conectar con el servidor. Revisá tu internet y probá de nuevo.');
            });
    }

    /* El servidor respondio 401. Si venia con una clave guardada, es que ya no
       sirve (o se cambio): se borra y se vuelve a pedir. Si no venia con ninguna,
       es el primer intento y todavia no hay que molestar al usuario. */
    function errorDeClave() {
        if (!obtener()) {
            // solo se muestra la pantalla: sin borrar el aviso que ya estaba
            // (por ejemplo, cuántos intentos quedan)
            var fondo = id('clave-fondo');
            if (fondo) fondo.hidden = false;
            return;
        }
        guardar('');
        mostrar('Esa clave no es correcta.');
    }

    /* 5 claves equivocadas: en vez de la pantalla de la clave queda un cartel
       sin lugar para escribir. Vuelve a la normalidad recién cuando un
       desarrollador lo habilita y se actualiza la página. */
    function mostrarDispositivoBloqueado() {
        var fondo = id('clave-fondo');
        if (!fondo) return;
        fondo.hidden = false;
        var caja = fondo.querySelector('.clave-caja');
        if (!caja || caja.classList.contains('clave-bloqueada')) return;
        caja.classList.add('clave-bloqueada');
        caja.innerHTML =
            '<div class="clave-bloqueada-icono">🔒</div>' +
            '<h1 class="clave-titulo">Dispositivo bloqueado</h1>' +
            '<p class="clave-bloqueada-motivo">5 intentos fallidos con la clave</p>' +
            '<p class="clave-ayuda">Por seguridad, este dispositivo ya no puede entrar al panel. ' +
            'Si sos el dueño del local, pedile a los desarrolladores de la página que lo habiliten ' +
            'y después actualizá la página.</p>';
    }

    /* Si el servidor frenó el pedido (15 minutos de espera, o el dispositivo
       bloqueado), muestra en la pantalla de la clave lo que explicó. */
    function revisarBloqueo(respuesta) {
        if (respuesta.status !== 429 && respuesta.status !== 403) return;
        respuesta.clone().json().then(function (datos) {
            if (datos && datos.codigo === 'dispositivo_bloqueado') {
                mostrarDispositivoBloqueado();
                return;
            }
            mostrar((datos && datos.error) || 'Demasiados intentos con la clave equivocada.');
        }).catch(function () {
            mostrar('Demasiados intentos con la clave equivocada.');
        });
    }

    function conectar() {
        var entrada = id('clave-input');
        var boton = id('clave-boton');
        if (!entrada || !boton) return;

        if (obtener()) {
            ocultar();
        } else {
            mostrar();
            entrada.focus();
        }

        boton.addEventListener('click', function () {
            comprobar();
        });

        // Enter tambien entra, sin mirar el boton
        entrada.addEventListener('keydown', function (evento) {
            if (evento.key === 'Enter') {
                evento.preventDefault();
                comprobar();
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', conectar);
    } else {
        conectar();
    }

    return {
        obtener: obtener,
        guardar: guardar,
        cabeceras: cabeceras,
        mostrar: mostrar,
        ocultar: ocultar,
        errorDeClave: errorDeClave,
        revisarBloqueo: revisarBloqueo,
        alEntrar: function (funcion) {
            alEntrar.push(funcion);
        }
    };
})();
