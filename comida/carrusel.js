const slides = document.querySelectorAll(".slide");

let current = 0;
let autoplay = null;

const INTERVALO = 4000;

/* Mostrar slide */
function showSlide(index) {
    slides.forEach(slide => {
        slide.classList.remove("active");
    });

    slides[index].classList.add("active");
}

/* Auto-avance */
function arrancarAuto() {
    if (autoplay === null) {
        autoplay = setInterval(nextSlide, INTERVALO);
    }
}

function detenerAuto() {
    clearInterval(autoplay);
    autoplay = null;
}

/* Siguiente */
function nextSlide() {
    current++;

    if (current >= slides.length) {
        current = 0;
    }

    showSlide(current);
}

/* Anterior */
function prevSlide() {
    current--;

    if (current < 0) {
        current = slides.length - 1;
    }

    showSlide(current);
}

/* Los botones manuales reinician el temporizador para que la imagen no se cambie enseguida */
function siguienteManual() {
    nextSlide();
    detenerAuto();
    arrancarAuto();
}

function anteriorManual() {
    prevSlide();
    detenerAuto();
    arrancarAuto();
}

/* La página (idle móvil) controla cuándo arranca o se detiene */
window.carruselArrancar = arrancarAuto;
window.carruselDetener = detenerAuto;

/* Iniciar automático */
arrancarAuto();