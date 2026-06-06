# Deploying VoiceCal so friends can use it

The app is now set up to deploy as **one Render web service** that serves both the
API and the frontend from the same domain. Follow these steps once.

## 1. Push your code to GitHub
The `credentials.json`, `token.json`, `.env`, and `users.db` files are gitignored on
purpose — never commit them. Push the rest:
```
git add -A
git commit -m "Make app deployable"
git push
```

## 2. Create the service on Render
1. Go to https://render.com → sign up (free) → **New +** → **Blueprint**.
2. Connect your GitHub repo. Render reads `render.yaml` and creates the web service
   **and** a free Postgres database automatically.
3. When prompted, set the secret env var:
   - `ANTHROPIC_API_KEY` = your Claude API key (the value from `backend/.env`).
4. Click **Apply**. The first deploy takes a few minutes.

## 3. Upload your Google credentials as a Secret File
Render won't have `credentials.json` (it's gitignored). Add it securely:
1. In Render → your `voicecal` service → **Environment** → **Secret Files**.
2. Add a file named `credentials.json` with the contents of your local
   `backend/credentials.json`. Mount path: `credentials.json`.

## 4. Get your public URL
After deploy, Render gives you a URL like `https://voicecal.onrender.com`.
That's the link you'll share. `BASE_URL` auto-detects this — nothing to set.

## 5. Update Google Cloud Console (most important step)
Go to https://console.cloud.google.com → your project → **APIs & Services**.

**a) Authorized redirect URI** (under *Credentials* → your OAuth client):
   add `https://voicecal.onrender.com/callback` (use your real URL).

**b) Add your friends as test users** (under *OAuth consent screen*):
   - Keep the app in **Testing** mode (do NOT publish — that needs Google's
     verification because of the Calendar scope).
   - Under **Test users**, add each friend's Gmail address. Up to 100 allowed.
   - Only those emails will be able to log in. That's exactly what you want.

## 6. Share the link
Send friends `https://voicecal.onrender.com`. They click **Login with Google**,
approve calendar access, and start adding events by voice.

> Note: voice input uses the Web Speech API, which works in **Chrome and Edge**
> (not Firefox/Safari). HTTPS is required for the mic — Render provides it.

---

## Local development still works unchanged
- Backend: `cd backend && uvicorn main:app --reload` (http://127.0.0.1:8000)
- Frontend: open `frontend/homepage.html` with VS Code Live Server (port 5500)
The code auto-detects port 5500 and talks to the local backend.

## Heads up: Render free tier
Free services sleep after ~15 min idle, so the first visit after a pause takes
~30–60s to wake up. Fine for friends; upgrade to a paid instance if you want it
always-on.
