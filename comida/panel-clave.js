/* MODO HAMBRE — CLAVE DEL PANEL
 *
 * El panel de pedidos muestra datos de los clientes (nombre, telefono y
 * direccion), asi que el servidor pide una clave antes de devolverlos. Este
 * archivo se encarga de eso en las dos paginas del dueno: admin.html y
 * archivo.html.
 *
 * La clave queda guardada en el navegador para no escribirla cada vez que se
 * abre el panel.
 */

var PanelClave = (function () {
    var LLAVE = 'modo-hambre-clave';
    var CABECERA = 'X-Clave-Panel';

    // Se usa cuando el navegador no deja guardar nada (modo privado, etc.)
    var enMemoria = '';

    // Funciones que se avisan cuando la clave queda aceptada. Las usa el editor
    // del menu, que no puede mostrar nada hasta que entra la clave.
    var alEntrar = [];

    function id(nombre) {
        return document.getElementById(nombre);
    }

    function obtener() {
        try {
            return window.localStorage.getItem(LLAVE) || enMemoria;
        } catch (e) {
            return enMemoria;
        }
    }

    function guardar(clave) {
        enMemoria = clave || '';
        try {
            if (clave) {
                window.localStorage.setItem(LLAVE, clave);
            } else {
                window.localStorage.removeItem(LLAVE);
            }
        } catch (e) {}
    }

    /* Se agrega a cada pedido al host. Sin esto el servidor responde 401. */
    function cabeceras(adicionales) {
        var cabeceras = {};
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
                    if (respuesta.status === 429) {
                        mostrar(datos.error || 'Demasiados intentos. Esperá unos minutos.');
                    } else if (datos.intentos_restantes != null) {
                        mostrar('Esa clave no es correcta. Te quedan ' + datos.intentos_restantes +
                            (datos.intentos_restantes === 1 ? ' intento.' : ' intentos.'));
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
            mostrar();
            return;
        }
        guardar('');
        mostrar('Esa clave no es correcta.');
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
        alEntrar: function (funcion) {
            alEntrar.push(funcion);
        }
    };
})();
