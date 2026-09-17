const slides = document.querySelectorAll(".slide");

let current = 0;
let timer;

/* Mostrar slide */
function showSlide(index){

    slides.forEach(slide => {
        slide.classList.remove("active");
    });

    slides[index].classList.add("active");
}

/* Reiniciar temporizador */
function reiniciarTemporizador(){
    clearInterval(timer);
    timer = setInterval(nextSlide, 6000);
}

/* Siguiente */
function nextSlide(){

    current++;

    if(current >= slides.length){
        current = 0;
    }

    showSlide(current);
}

/* Anterior */
function prevSlide(){

    current--;

    if(current < 0){
        current = slides.length - 1;
    }

    showSlide(current);
}

/* Los botones manuales reinician el temporizador para que la imagen no se cambie enseguida */
function siguienteManual(){
    nextSlide();
    reiniciarTemporizador();
}

function anteriorManual(){
    prevSlide();
    reiniciarTemporizador();
}

/* Iniciar automático */
timer = setInterval(nextSlide, 6000);