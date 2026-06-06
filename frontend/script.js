const speechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

if (!speechRecognition) {
    alert("Your browser does not support Speech Recognition. Please use a compatible browser.");
}

const recognition = new speechRecognition();
let isListening = false;

recognition.continuous = false;
recognition.lang = 'en-US';
recognition.interimResults = false;
recognition.maxAlternatives = 1;

const startBtn = document.querySelector('.primary-button');
const descriptionElement = document.querySelector('.container-desc3');

startBtn.addEventListener('click', ()=>{
    if(isListening) {
        recognition.stop();
        isListening = false;

    } else{
        recognition.start();
        isListening = true;
    }
});


recognition.onresult = (event) => {
    const spokenText = event.results[0][0].transcript;
    descriptionElement.innerHTML = `"${spokenText}"`;

};
