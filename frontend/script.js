// ===== TOP-BAR NAVIGATION =====
const voiceButton = document.getElementById("voicepage");
if (voiceButton) {
    voiceButton.addEventListener("click", () => {
        window.location.href = "index.html";
    });
}

const homeButton = document.getElementById("homepage");
if (homeButton) {
    homeButton.addEventListener("click", () => {
        window.location.href = "homepage.html";
    });
}

// API base: during local dev the frontend runs on Live Server (:5500) while the
// backend runs on :8000. In production both are served from the same origin, so
// an empty string (relative URLs) is correct.
const API = (location.port === "5500") ? "http://127.0.0.1:8000" : "";

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = null;
let isRecording = false;

function setStatus(message) {
    const status = document.getElementById("status");
    if (status) status.innerText = message;
}

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    // Recording animation: turn the mic button into a pulsing red square while
    // the browser is actively listening, and restore it when listening stops.
    recognition.onstart = () => {
        isRecording = true;
        document.getElementById("micButton")?.classList.add("recording");
        setStatus("Listening...");
    };

    recognition.onend = () => {
        isRecording = false;
        document.getElementById("micButton")?.classList.remove("recording");
    };

    recognition.onerror = (event) => {
        isRecording = false;
        document.getElementById("micButton")?.classList.remove("recording");
        setStatus(`Mic error: ${event.error}`);
    };

    recognition.onresult = async (event) => {
        const text = event.results[0][0].transcript;
        setStatus(`You said: "${text}"`);

        try {
            const response = await fetch(`${API}/create-event`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({ text: text })
            });
            const data = await response.json();
            if (data.status === "created") {
                setStatus("✅ Event created!");
            } else {
                setStatus(`⚠️ ${data.message || "Could not create event"}`);
            }
        } catch (err) {
            setStatus("⚠️ Network error, please try again");
        }
    };
}

// ===== LOGIN / SESSION CHECK =====
window.onload = async () => {
    let data = { loggedIn: false };
    try {
        const res = await fetch(`${API}/me`, { credentials: "include" });
        data = await res.json();
    } catch (err) {
        // Backend unreachable — treat as logged out.
    }

    // ---- Homepage (landing) ----
    const loginButton = document.getElementById("loginButton");
    if (loginButton) {
        // Don't force-redirect logged-in users away from the homepage; that's
        // what made the "Home" link bounce straight back to the app. Instead,
        // "Get Started" decides where to go on click.
        loginButton.onclick = () => {
            if (data.loggedIn) {
                window.location.href = "index.html";   // already signed in → app
            } else {
                window.location.href = `${API}/login`;  // not signed in → Google
            }
        };
    }

    // ---- Voice page (app) ----
    const micButton = document.getElementById("micButton");
    if (micButton) {
        if (!data.loggedIn) {
            window.location.href = "homepage.html";
            return;
        }

        // Show the calendar button so users can verify events actually landed.
        const calendarBtn = document.getElementById("calendarButton");
        if (calendarBtn) {
            calendarBtn.style.display = "inline-flex";
            calendarBtn.title = `Open Google Calendar (${data.email})`;
            calendarBtn.onclick = () => {
                window.open("https://calendar.google.com", "_blank");
            };
        }

        micButton.onclick = () => {
            if (!recognition) {
                setStatus("Please use Chrome or Edge");
                return;
            }
            if (isRecording) {
                recognition.stop();   // tap again to stop recording
            } else {
                recognition.start();
            }
        };
    }
};
