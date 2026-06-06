// API base: during local dev the frontend runs on Live Server (:5500) while the
// backend runs on :8000. In production both are served from the same origin, so
// an empty string (relative URLs) is correct.
const API = (location.port === "5500") ? "http://127.0.0.1:8000" : ""

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition

let recognition = null

if (SpeechRecognition) {
    recognition = new SpeechRecognition()
    recognition.interimResults = false
    recognition.lang = 'en-US'

    recognition.onresult = async (event) => {
        const text = event.results[0][0].transcript
        document.getElementById("status").innerText = `You said: ${text}`
        
        const response = await fetch(`${API}/create-event`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ text: text })
        })
        
        const data = await response.json()
        document.getElementById("status").innerText = "✅ Event created!"
    }
}

// ===== LOGIN / SESSION CHECK =====
window.onload = async () => {
    const res = await fetch(`${API}/me`, {
        credentials: "include"
    })
    const data = await res.json()
    
    // login page
    if (document.getElementById("loginButton")) {
        if (data.loggedIn) {
            window.location.href = "index.html"
        }
        document.getElementById("loginButton").onclick = () => {
            window.location.href = `${API}/login`
        }
    }

    // voice page
    if (document.getElementById("micButton")) {
        if (!data.loggedIn) {
            window.location.href = "homepage.html"
        }
        document.getElementById("status").innerText = `Logged in as ${data.email}`
        
        document.getElementById("micButton").onclick = () => {
            if (recognition) {
                recognition.start()
            } else {
                document.getElementById("status").innerText = "Please use Chrome or Edge"
            }
        }
    }
}