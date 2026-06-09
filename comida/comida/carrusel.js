const slides = document.querySelectorAll(".slide");

let current = 0;

/* Mostrar slide */
function showSlide(index){

    slides.forEach(slide => {
        slide.classList.remove("active");
    });

    slides[index].classList.add("active");
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

setInterval(nextSlide, 3000); 