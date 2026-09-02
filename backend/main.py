import os
import json
import os.path
import secrets
import hashlib
import base64
from vcparser import parse_speech_to_event, ConfigError, DEFAULT_TIMEZONE
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from database import Session, User

# Configuration (from environment, with local-dev defaults)
# BASE_URL = public URL of THIS backend (used to build the OAuth redirect URI).
# Render injects RENDER_EXTERNAL_URL automatically, so it works without manual config.
BASE_URL = os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000"
# FRONTEND_URL = where to send the user after login. Empty string = same origin.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5500/frontend")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-secret-change-me")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://127.0.0.1:5500").split(",")

IS_HTTPS = BASE_URL.startswith("https://")
REDIRECT_URI = f"{BASE_URL}/callback"

if not IS_HTTPS:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # allow http for local dev only
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"  # don't error if granted scopes differ

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
SCOPES = [CALENDAR_SCOPE,
          "https://www.googleapis.com/auth/userinfo.email",
          "openid"]


def granted_scopes(flow, creds):
    """Scopes Google actually granted, which can be narrower than SCOPES.

    The consent screen shows one checkbox per sensitive scope, so a user can
    approve sign-in while declining calendar access. Google's token response is
    the authoritative record of what came back.
    """
    scope = (flow.oauth2session.token or {}).get("scope")
    if isinstance(scope, str):
        return scope.split()
    if isinstance(scope, (list, tuple)):
        return list(scope)
    return list(creds.scopes or [])

def calendar_timezone(service):
    """The timezone the user's Google Calendar is set to, or None.

    "Tomorrow at 9" has to be resolved in the user's timezone, not the server's,
    and the calendar itself is the authority on which one that is.
    """
    try:
        return service.settings().get(setting="timezone").execute().get("value")
    except HttpError:
        return None


app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=IS_HTTPS,        # only send the session cookie over HTTPS in production
    same_site="lax",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

class EventRequest(BaseModel):
    text: str

# frontend redirects user here to start login
@app.get("/login")
def login(request: Request):
    # generate PKCE code verifier and challenge
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        code_challenge=code_challenge,
        code_challenge_method="S256"
    )
    
    # save both state and verifier in session
    request.session["state"] = state
    request.session["code_verifier"] = code_verifier
    
    return RedirectResponse(auth_url)


@app.get("/callback")
def callback(request: Request):
    # get state from URL params instead of session
    state = request.query_params.get("state")
    code_verifier = request.session.get("code_verifier")
    
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state  # from URL, not session
    )
    
    flow.fetch_token(
        authorization_response=str(request.url),
        code_verifier=code_verifier
    )
    creds = flow.credentials

    # Storing a token without calendar access just defers the failure to the
    # first event the user speaks, where it surfaces as an opaque 403.
    if CALENDAR_SCOPE not in granted_scopes(flow, creds):
        request.session.clear()
        return RedirectResponse(f"{FRONTEND_URL}/homepage.html?error=calendar_scope")

    import google.oauth2.id_token
    import google.auth.transport.requests
    id_info = google.oauth2.id_token.verify_oauth2_token(
        creds.id_token,
        google.auth.transport.requests.Request()
    )
    email = id_info["email"]

    db = Session()
    try:
        user = db.query(User).filter_by(email=email).first()
        if not user:
            user = User(email=email)
        user.token = creds.to_json()
        db.add(user)
        db.commit()
    finally:
        db.close()

    request.session["email"] = email
    return RedirectResponse(f"{FRONTEND_URL}/index.html")

# create event for logged in user
@app.post("/create-event")
def create_event(request: Request, body: EventRequest):
    email = request.session.get("email")
    if not email:
        return {"status": "error", "message": "Not logged in", "relogin": True}

    db = Session()
    try:
        user = db.query(User).filter_by(email=email).first()
        # The signed session cookie outlives the users table whenever the database
        # is reset (a fresh SQLite file after a redeploy, a wiped Postgres). Treat
        # that as logged out instead of blowing up on user.token.
        if not user or not user.token:
            request.session.clear()
            return {"status": "error",
                    "message": "Session expired — please sign in again.",
                    "relogin": True}

        creds = Credentials.from_authorized_user_info(json.loads(user.token))
        # Google access tokens expire after an hour. Refresh here and store the
        # result so the next request starts from a valid token.
        if not creds.valid and creds.refresh_token:
            try:
                creds.refresh(GoogleRequest())
            except RefreshError:
                request.session.clear()
                return {"status": "error",
                        "message": "Google access was revoked — please sign in again.",
                        "relogin": True}
            user.token = creds.to_json()
            db.commit()
    finally:
        db.close()

    try:
        service = build("calendar", "v3", credentials=creds)

        # Looked up once per session — it only changes if the user changes it in
        # Google Calendar, and re-reading it on every utterance costs a round trip.
        timezone = request.session.get("timezone")
        if not timezone:
            timezone = calendar_timezone(service) or DEFAULT_TIMEZONE
            request.session["timezone"] = timezone

        event_data = parse_speech_to_event(body.text, timezone)
        # The parser flags speech that isn't about scheduling so don't create
        # junk calendar events from small talk or unrelated comments.
        if event_data.get("not_event"):
            return {"status": "ignored", "message": "That didn't sound like an event."}
        event = service.events().insert(calendarId='primary', body=event_data).execute()
        return {"status": "created", "link": event.get('htmlLink')}
    except HttpError as error:
        # A token issued before calendar access was granted still authenticates,
        # it just can't write events.
        if error.status_code == 403:
            request.session.clear()
            return {"status": "error",
                    "message": "VoiceCal doesn't have calendar access — sign in again and allow it.",
                    "relogin": True}
        return {"status": "error", "message": str(error)}
    except ConfigError as error:
        # Server-side misconfiguration: say so in the logs, don't blame the user.
        print(f"CONFIG ERROR: {error}", flush=True)
        return {"status": "error", "message": "VoiceCal is misconfigured — check the server logs."}
    except (json.JSONDecodeError, IndexError, KeyError):
        # Claude returned something that wasn't the event JSON we asked for.
        return {"status": "error", "message": "Couldn't understand that — try again."}

@app.get("/me")
def get_user(request: Request):
    email = request.session.get("email")
    if not email:
        return {"loggedIn": False}

    # calendarAccess makes a partially-granted token visible before the user
    # tries to speak an event.
    db = Session()
    try:
        user = db.query(User).filter_by(email=email).first()
        scopes = json.loads(user.token).get("scopes", []) if user and user.token else []
    finally:
        db.close()

    return {"loggedIn": True, "email": email, "calendarAccess": CALENDAR_SCOPE in scopes}

# Serve the frontend from this same app (single origin = no CORS/cookie headaches).
# Mounted LAST so the API routes above take priority. html=True serves homepage.html
# for "/" and resolves bare paths like /index.html.
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")