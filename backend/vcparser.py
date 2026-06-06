import anthropic
import datetime
import os
import json
from dotenv import load_dotenv

load_dotenv()

def parse_speech_to_event(text: str):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""Parse this into a Google Calendar event JSON.
                Today is {datetime.date.today()}.
                Timezone is America/Toronto.

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
                - start: {{"dateTime": "...", "timeZone": "America/Toronto"}} (always required)
                - end: {{"dateTime": "...", "timeZone": "America/Toronto"}} (always required)
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