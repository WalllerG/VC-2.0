import os.path
from vcparser import parse_speech_to_event
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar"]
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class EventRequest(BaseModel):
    text: str

def get_credentials():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds

@app.post("/create-event")
def create_event(request: EventRequest):
    try:
        creds = get_credentials()
        service = build("calendar", "v3", credentials=creds)
        event_data = parse_speech_to_event(request.text)
        event = service.events().insert(calendarId='primary', body=event_data).execute()
        return {"status": "created", "link": event.get('htmlLink')}
    except HttpError as error:
        return {"status": "error", "message": str(error)}