const speechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

if (!speechRecognition) {
    alert("Your browser does not support Speech Recognition. Please use a compatible browser.");
}

const recognition = new speechRecognition();

recognition.continuous = false;
recognition.lang = 'en-US';
recognition.interimResults = false;
recognition.maxAlternatives = 1;

const startBtn = document.querySelector('.primary-button');
const descriptionElement = document.querySelector('.container-desc3');

startBtn.addEventListener('click', ()=>{
    recognition.start();
});


recognition.onresult = (event) => {
    const spokenText = event.results[0][0].transcript;
    descriptionElement.innerHTML = `"${spokenText}"`;

};

