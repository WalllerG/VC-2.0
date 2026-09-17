/* VoiceCal front end.
   Speech and typing converge on one input and one endpoint — dictation just
   fills the box and submits it, so there is a single code path to reason about.

   Everything that came from the calendar (event titles, locations) is written
   with textContent, never innerHTML: an event title is attacker-controlled by
   anyone who can send the user an invite. */

// During local dev the frontend runs on Live Server (:5500) while the backend
// runs on :8000. In production both are served from the same origin.
const API = (location.port === "5500") ? "http://127.0.0.1:8000" : "";

const log = document.getElementById("log");
const logScroll = document.getElementById("logScroll");
const opener = document.getElementById("opener");
const composer = document.getElementById("composer");
const input = document.getElementById("commandInput");
const micButton = document.getElementById("micButton");
const sendButton = document.getElementById("sendButton");
const hint = document.getElementById("hint");

let busy = false;

/* ---------- small DOM helpers ---------- */

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function setHint(message) {
    if (hint) hint.textContent = message || "";
}

function scrollToEnd() {
    if (logScroll) logScroll.scrollTop = logScroll.scrollHeight;
}

function clockStamp() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatWhen(iso) {
    if (!iso) return "";
    const when = new Date(iso);
    if (isNaN(when.getTime())) return iso;
    const day = when.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    // All-day events come back as a bare date with no time component.
    if (!String(iso).includes("T")) return `${day} · all day`;
    return `${day} · ${when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

/* ---------- the planner log ---------- */

function addEntry(who, text, modifier) {
    if (opener) opener.hidden = true;
    // The gutter rule only makes sense once something is written in the gutter.
    log.classList.add("log--ruled");

    const entry = el("div", `entry entry--${modifier || who.toLowerCase()}`);
    entry.append(el("time", "entry__time", clockStamp()));

    const body = el("div", "entry__body");
    body.append(el("p", "entry__who", who));
    if (text) body.append(el("p", "entry__text", text));

    entry.append(body);
    log.append(entry);
    scrollToEnd();
    return { entry, body };
}

function showEvents(body, events) {
    if (!events || !events.length) return;
    const list = el("ul", "events");

    for (const event of events) {
        const item = el("li", "event");

        const title = el("div", "event__title");
        title.append(document.createTextNode(event.summary || "Untitled event"));
        if (event.recurring) title.append(el("span", "event__repeat", "repeats"));
        item.append(title);

        item.append(el("div", "event__meta", formatWhen(event.start)));

        if (event.link) {
            const link = el("a", "event__link", "View in Google Calendar");
            link.href = event.link;
            link.target = "_blank";
            link.rel = "noopener";
            item.append(link);
        }
        list.append(item);
    }
    body.append(list);
    scrollToEnd();
}

function showConfirm(body, confirm) {
    const card = el("div", "confirm");
    const count = confirm.count === 1 ? "1 event" : `${confirm.count} events`;
    const scopeNote = confirm.scope === "all_events" ? " and every repeat of it" : "";

    card.append(el("p", "confirm__summary",
        `Delete ${count}${scopeNote}: ${confirm.summary}`));

    const actions = el("div", "confirm__actions");
    const yes = el("button", "btn btn--danger", "Delete");
    const no = el("button", "btn", "Keep it");
    yes.type = "button";
    no.type = "button";

    const resolve = async (accept) => {
        yes.disabled = true;
        no.disabled = true;
        const data = await post("/confirm", { accept });
        card.remove();
        if (data) renderResult(addEntry("VoiceCal", "").body, data);
    };

    yes.addEventListener("click", () => resolve(true));
    no.addEventListener("click", () => resolve(false));
    actions.append(yes, no);
    card.append(actions);
    body.append(card);
    scrollToEnd();
}

/* ---------- talking to the backend ---------- */

async function post(path, payload) {
    try {
        const response = await fetch(`${API}${path}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify(payload),
        });
        return await response.json();
    } catch (err) {
        setHint("Couldn't reach VoiceCal. Check your connection and try again.");
        return null;
    }
}

function renderResult(body, data) {
    if (data.relogin) {
        body.append(el("p", "entry__text", data.message || "Sign in again to continue."));
        setTimeout(() => { window.location.href = "homepage.html"; }, 1800);
        return;
    }

    const message = data.message || (data.status === "error" ? "Something went wrong." : "Done.");
    body.append(el("p", "entry__text", message));

    showEvents(body, data.created);
    if (data.status === "confirm" && data.confirm) showConfirm(body, data.confirm);
    scrollToEnd();
}

async function submitText(text) {
    const trimmed = (text || "").trim();
    if (!trimmed || busy) return;

    busy = true;
    sendButton.disabled = true;
    input.value = "";
    setHint("");

    addEntry("You", trimmed, "you");
    const working = addEntry("VoiceCal", "Working on it…", "pending");

    const data = await post("/command", { text: trimmed });

    working.entry.remove();
    if (data) {
        renderResult(addEntry("VoiceCal", "").body, data);
    } else {
        // Network failure: give the text back so it isn't lost.
        input.value = trimmed;
    }

    busy = false;
    sendButton.disabled = false;
    input.focus();
}

/* ---------- speech ---------- */

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;
let submitAfterStop = false;

if (SpeechRecognition && micButton) {
    recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = true;   // live text in the box while speaking

    recognition.onstart = () => {
        listening = true;
        submitAfterStop = false;
        micButton.classList.add("listening");
        micButton.setAttribute("aria-label", "Stop voice input");
        setHint("Listening — say what you need scheduled.");
    };

    recognition.onresult = (event) => {
        let settled = "";
        let draft = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const result = event.results[i];
            if (result.isFinal) settled += result[0].transcript;
            else draft += result[0].transcript;
        }
        input.value = (settled || draft).trim();
        if (settled) {
            submitAfterStop = true;
            recognition.stop();
        }
    };

    recognition.onerror = (event) => {
        submitAfterStop = false;
        if (event.error === "no-speech") setHint("Didn't catch that — tap the mic and try again.");
        else if (event.error === "not-allowed") setHint("Microphone blocked. Allow it in your browser settings.");
        else if (event.error !== "aborted") setHint(`Microphone error: ${event.error}`);
    };

    recognition.onend = () => {
        listening = false;
        micButton.classList.remove("listening");
        micButton.setAttribute("aria-label", "Start voice input");
        if (submitAfterStop) {
            submitAfterStop = false;
            setHint("");
            submitText(input.value);
        } else if (hint && hint.textContent.startsWith("Listening")) {
            setHint("");
        }
    };

    micButton.addEventListener("click", () => {
        if (listening) {
            recognition.stop();
        } else {
            try {
                recognition.start();
            } catch (err) {
                // start() throws if called while already starting; harmless.
            }
        }
    });
} else if (micButton) {
    micButton.disabled = true;
    micButton.title = "Voice input needs Chrome or Edge — typing works everywhere";
}

/* ---------- wiring ---------- */

if (composer) {
    composer.addEventListener("submit", (event) => {
        event.preventDefault();
        submitText(input.value);
    });
}

const suggestions = document.getElementById("suggestions");
if (suggestions) {
    suggestions.addEventListener("click", (event) => {
        const button = event.target.closest(".suggestion");
        if (button) submitText(button.textContent);
    });
}

window.addEventListener("DOMContentLoaded", async () => {
    let account = { loggedIn: false };
    try {
        const response = await fetch(`${API}/me`, { credentials: "include" });
        account = await response.json();
    } catch (err) {
        // Backend unreachable — treat as signed out.
    }

    // ---- Landing page ----
    const authError = document.getElementById("authError");
    if (authError && new URLSearchParams(location.search).get("error") === "calendar_scope") {
        authError.textContent =
            "VoiceCal needs permission to manage your Google Calendar. " +
            "Sign in again and tick the calendar checkbox.";
        authError.hidden = false;
    }

    const loginButton = document.getElementById("loginButton");
    if (loginButton) {
        loginButton.addEventListener("click", () => {
            window.location.href = account.loggedIn ? "index.html" : `${API}/login`;
        });
    }

    // ---- App page ----
    if (composer) {
        if (!account.loggedIn) {
            window.location.href = "homepage.html";
            return;
        }
        const emailSlot = document.getElementById("userEmail");
        if (emailSlot && account.email) emailSlot.textContent = account.email;
        if (account.calendarAccess === false) {
            setHint("VoiceCal doesn't have calendar permission yet — sign in again to grant it.");
        }
        input.focus();
    }
});
