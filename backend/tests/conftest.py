"""Test doubles for the two services VoiceCal talks to.

Neither Google Calendar nor the Anthropic API is reachable from a test run, so
both are replaced with fakes that record what they were asked to do. That makes
"did the agent try to delete anything?" an assertion rather than a hope.
"""
import os
import pathlib
import sys

import httplib2
import pytest
from googleapiclient.errors import HttpError

BACKEND = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Set before importing app modules: database.py builds an engine at import time.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
os.environ.setdefault("SECRET_KEY", "test-secret")

TZ = "America/Toronto"


def http_error(status):
    return HttpError(resp=httplib2.Response({"status": status}), content=b"{}")


class _Pending:
    """Mimics the googleapiclient request objects, which defer until execute()."""

    def __init__(self, result, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class FakeEvents:
    def __init__(self, service):
        self.service = service

    def insert(self, calendarId, body):
        self.service.inserted.append(body)
        event_id = f"evt{len(self.service.inserted)}"
        return _Pending({
            "id": event_id,
            "summary": body.get("summary"),
            "start": body.get("start"),
            "htmlLink": f"https://calendar.example/{event_id}",
            "recurrence": body.get("recurrence"),
        })

    def list(self, **params):
        self.service.list_params.append(params)
        return _Pending({"items": self.service.items})

    def get(self, calendarId, eventId):
        event = self.service.by_id.get(eventId)
        if event is None:
            return _Pending(None, http_error(404))
        return _Pending(event)

    def delete(self, calendarId, eventId):
        error = self.service.delete_errors.get(eventId)
        if error:
            return _Pending(None, error)
        self.service.deleted.append(eventId)
        return _Pending("")


class FakeSettings:
    def __init__(self, service):
        self.service = service

    def get(self, setting):
        return _Pending({"value": self.service.timezone})


class FakeService:
    """Records every write so tests can assert the calendar was left alone."""

    def __init__(self, items=None, timezone=TZ):
        self.items = items or []
        self.timezone = timezone
        self.inserted = []
        self.deleted = []
        self.list_params = []
        self.delete_errors = {}
        self.by_id = {e["id"]: e for e in self.items if e.get("id")}

    def events(self):
        return FakeEvents(self)

    def settings(self):
        return FakeSettings(self)


class Block:
    def __init__(self, type, **fields):
        self.type = type
        for key, value in fields.items():
            setattr(self, key, value)


def text_block(text):
    return Block("text", text=text)


def tool_block(name, payload, block_id="toolu_1"):
    return Block("tool_use", name=name, input=payload, id=block_id)


class Response:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


def says(text):
    return Response([text_block(text)], "end_turn")


def calls(*blocks, note=""):
    content = ([text_block(note)] if note else []) + list(blocks)
    return Response(content, "tool_use")


class FakeClient:
    """Replays a scripted list of responses and records each request."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.requests = []

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.queue:
            raise AssertionError("agent made more model calls than the test scripted")
        return self.queue.pop(0)


@pytest.fixture
def service():
    return FakeService()
