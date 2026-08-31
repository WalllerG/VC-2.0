import anthropic
import datetime
import os
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

load_dotenv()

# Used when the user's Google Calendar timezone can't be read.
DEFAULT_TIMEZONE = "America/Toronto"


def resolve_timezone(name):
    """Return (name, tzinfo) for a timezone, falling back if it isn't usable.

    Google can hand back a zone this machine doesn't know, and a missing tzdata
    makes even the default unusable, so this never raises.
    """
    for candidate in (name, DEFAULT_TIMEZONE):
        if not candidate:
            continue
        try:
            return candidate, ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return "UTC", datetime.timezone.utc


def parse_speech_to_event(text: str, timezone: str = DEFAULT_TIMEZONE):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # The server runs in UTC, so an unzoned "today" is already tomorrow for
    # anyone speaking in the evening in a western timezone.
    tz_name, tz = resolve_timezone(timezone)
    now = datetime.datetime.now(tz)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""Parse this into a Google Calendar event JSON.
                Right now it is {now:%A, %B %d, %Y} at {now:%I:%M %p} in {tz_name}.
                Timezone is {tz_name}.

                Return ONLY valid JSON, nothing else.

                FIRST decide whether the user is actually asking to schedule or create
                a calendar event/reminder. Speech that is small talk, a question, a
                random comment, or otherwise has nothing to do with scheduling an event
                is NOT an event. If it is NOT an event, return exactly:
                {{"not_event": true}}

                Only if it IS an event, return the event JSON below.
                Include only the fields that are relevant based on what the user said.

                Possible fields:
                - summary: event title (always required)
                - location: physical address or place name (if mentioned)
                - description: any extra details or notes (if mentioned)
                - start: {{"dateTime": "...", "timeZone": "{tz_name}"}} (always required)
                - end: {{"dateTime": "...", "timeZone": "{tz_name}"}} (always required)
                - recurrence: list of RRULE strings, e.g. ["RRULE:FREQ=WEEKLY;COUNT=4"] (if repeating)
                - attendees: list of {{"email": "..."}} (if emails mentioned)
                - reminders: {{"useDefault": false, "overrides": [{{"method": "popup", "minutes": 10}}]}} (if reminder mentioned)

                Recurrence examples:
                - "every day for a week" → RRULE:FREQ=DAILY;COUNT=7
                - "every monday for a month" → RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4
                - "every year" → RRULE:FREQ=YEARLY

                User said: "{text}"
                """
            }
        ]
    )

    raw = message.content[0].text
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)
