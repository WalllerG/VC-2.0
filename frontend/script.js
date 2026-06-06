const homeButton = document.getElementById("home-btn");

homeButton.addEventListener('click', () => {
   window.location.href = "homepage.html";
});  

// Added event listener to the home button to navigate back to homepage.html but MOVE IT LATER TO SCRIPT2.JS

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

startBtn.addEventListener('click', ()=>{
    if(isListening) {
        recognition.stop();
        isListening = false;

    } else{
        recognition.start();
        isListening = true;
    }
});


recognition.onresult = async (event) => {
    const text = event.results[0][0].transcript
    console.log("You said:", text)
    
    // send to FastAPI
    const response = await fetch("http://localhost:8000/create-event", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ text: text })
    })
  
    const data = await response.json()
    // show confirmation to user
    document.getElementById("status").innerText = "Event created!"
  }