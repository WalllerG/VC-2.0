# VoiceCal

Speak your plans, and they land on your calendar.

VoiceCal is a voice-first scheduling app. Sign in with Google, tap the mic, and
say something like _"lunch with Sarah next Friday at noon"_ — VoiceCal
transcribes your speech, uses AI to turn it into a structured event, and adds it
straight to your Google Calendar.

---

## How it works

```
🎙️  Speak  →  📝 Transcribe  →  🤖 Parse with AI  →  📅 Add to Google Calendar
```

1. **Speak** — The browser's Web Speech API captures your voice and transcribes
   it to text, right on the page.
2. **Parse** — The text is sent to the backend, where Claude (Anthropic) turns
   natural language into a structured calendar event: title, date, time,
   location, recurrence, reminders, and more.
3. **Schedule** — The event is created in your Google Calendar through the
   Google Calendar API.

If what you said isn't actually about scheduling — small talk, a question, a
random comment — the AI recognizes it and skips creating an event.

---

## Features

- 🎙️ **Hands-free** — create events by voice, no typing
- 🤖 **Natural language** — understands dates, times, recurrence, and reminders
- 🔒 **Sign in with Google** — secure OAuth 2.0 login with PKCE
- 📅 **Direct to your calendar** — events appear instantly in Google Calendar
- 🧠 **Smart filtering** — ignores speech that isn't a real event

---

## Tech stack

| Layer        | Technology                                            |
| ------------ | ----------------------------------------------------- |
| Frontend     | HTML, CSS, vanilla JavaScript, Web Speech API         |
| Backend      | Python, FastAPI, Uvicorn                              |
| AI parsing   | Anthropic Claude                                      |
| Calendar     | Google Calendar API                                   |
| Auth         | Google OAuth 2.0 (PKCE)                               |
| Database     | SQLAlchemy — SQLite locally, PostgreSQL in production |
| Deployment   | Render                                                 |

---

## Getting started

### Prerequisites

- Python 3.12
- A [Google Cloud](https://console.cloud.google.com/) project with the Calendar
  API enabled and OAuth credentials (`credentials.json`)
- An [Anthropic API key](https://console.anthropic.com/)
- A Chromium-based browser (Chrome or Edge) for the Web Speech API

### Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd VC-2.0/backend

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your secrets
#    - Place your Google OAuth credentials in backend/credentials.json
#    - Create backend/.env with your Anthropic API key:
echo "ANTHROPIC_API_KEY=your-key-here" > .env

# 4. Run the server
uvicorn main:app --reload
```

The backend serves the frontend too, so just open **http://127.0.0.1:8000** in
your browser, sign in with Google, and start speaking.

> **Local dev tip:** You can also run the frontend separately on Live Server
> (`:5500`) — the app detects this and points API calls at `:8000`
> automatically.

---

## Deployment

VoiceCal is configured for one-click deployment on [Render](https://render.com)
via [`render.yaml`](render.yaml), which provisions the web service and a managed
PostgreSQL database. Set these in the Render dashboard:

- `ANTHROPIC_API_KEY` — your Claude API key
- Upload your Google `credentials.json`
- Add your deployed callback URL (`<your-url>/callback`) to the authorized
  redirect URIs in Google Cloud

Other variables (`SECRET_KEY`, `DATABASE_URL`, `PYTHON_VERSION`) are wired up
automatically.

---

## Project structure

```
VC-2.0/
├── backend/
│   ├── main.py          # FastAPI app: auth, routes, serves frontend
│   ├── vcparser.py      # Claude prompt — speech text → calendar event JSON
│   ├── database.py      # SQLAlchemy models (User + Google token)
│   └── requirements.txt
├── frontend/
│   ├── homepage.html    # Landing page
│   ├── index.html       # Voice control page
│   ├── script.js        # Speech capture + API calls
│   └── *.css            # Styles
└── render.yaml          # Deployment config
```

---

## Contributors

- **Walter Guo**
- **Joel Saputra**
