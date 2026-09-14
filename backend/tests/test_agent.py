"""The agent loop: which tools run automatically, and which need a human."""
import datetime
import json

import pytest
from conftest import TZ, FakeClient, FakeService, calls, says, tool_block

import agent

NOW = datetime.datetime(2026, 9, 14, 10, 30)


def run(client, service, text="do the thing"):
    return agent.run_command(client, service, text, TZ, now=NOW)


# ---------- creating ----------

def test_single_event_is_created(service):
    client = FakeClient(
        calls(tool_block("create_events", {"events": [{
            "summary": "Lunch with Sarah",
            "start_datetime": "2026-09-18T12:00:00",
            "end_datetime": "2026-09-18T13:00:00",
            "location": "", "description": "", "recurrence": [],
        }]})),
        says("Added it."),
    )
    result = run(client, service, "lunch with sarah friday at noon")

    assert len(result["created"]) == 1
    assert result["created"][0]["summary"] == "Lunch with Sarah"
    assert result["pending_delete"] is None
    assert result["reply"] == "Added it."


def test_one_sentence_can_create_several_events(service):
    client = FakeClient(
        calls(tool_block("create_events", {"events": [
            {"summary": "Dentist", "start_datetime": "2026-09-15T15:00:00",
             "end_datetime": "2026-09-15T16:00:00",
             "location": "", "description": "", "recurrence": []},
            {"summary": "Haircut", "start_datetime": "2026-09-17T17:00:00",
             "end_datetime": "2026-09-17T18:00:00",
             "location": "", "description": "", "recurrence": []},
        ]})),
        says("Both are on your calendar."),
    )
    result = run(client, service, "dentist tuesday 3pm and haircut thursday 5pm")

    assert [e["summary"] for e in result["created"]] == ["Dentist", "Haircut"]
    assert len(service.inserted) == 2


def test_recurring_event_carries_its_rrule_to_the_calendar(service):
    client = FakeClient(
        calls(tool_block("create_events", {"events": [{
            "summary": "Gym",
            "start_datetime": "2026-09-21T07:00:00",
            "end_datetime": "2026-09-21T08:00:00",
            "location": "", "description": "",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4"],
        }]})),
        says("Set to repeat."),
    )
    result = run(client, service, "gym every monday at 7 for a month")

    assert service.inserted[0]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4"]
    assert result["created"][0]["recurring"] is True


# ---------- deleting always needs a human ----------

def test_delete_is_only_ever_proposed_never_performed():
    service = FakeService(items=[
        {"id": "evt_dentist", "summary": "Dentist",
         "start": {"dateTime": "2026-09-15T15:00:00-04:00"}},
    ])
    client = FakeClient(
        calls(tool_block("search_events", {
            "time_min": "2026-09-14T00:00:00",
            "time_max": "2026-09-30T00:00:00",
            "query": "",
        }, "toolu_search")),
        calls(tool_block("delete_events", {
            "event_ids": ["evt_dentist"],
            "summary": "Dentist on Tue Sep 15",
            "scope": "this_event",
        }, "toolu_delete")),
    )
    result = run(client, service, "cancel my dentist appointment")

    # The proposal came back...
    assert result["pending_delete"]["event_ids"] == ["evt_dentist"]
    assert result["pending_delete"]["scope"] == "this_event"
    # ...and absolutely nothing was removed.
    assert service.deleted == []


def test_search_results_are_handed_back_to_the_model():
    service = FakeService(items=[
        {"id": "evt_1", "summary": "Standup", "start": {"dateTime": "2026-09-15T09:00:00-04:00"}},
    ])
    client = FakeClient(
        calls(tool_block("search_events", {
            "time_min": "2026-09-14T00:00:00", "time_max": "2026-09-21T00:00:00", "query": "",
        })),
        says("You have one event: Standup."),
    )
    run(client, service, "what's on this week")

    # Second request carries the tool_result the search produced.
    follow_up = client.requests[1]["messages"][-1]
    payload = json.loads(follow_up["content"][0]["content"])
    assert payload["count"] == 1
    assert payload["events"][0]["summary"] == "Standup"


def test_delete_proposal_is_capped_so_it_fits_in_the_session_cookie(service):
    many = [f"evt_{i}" for i in range(50)]
    client = FakeClient(
        calls(tool_block("delete_events", {
            "event_ids": many, "summary": "everything", "scope": "this_event",
        })),
    )
    result = run(client, service, "delete everything")

    assert len(result["pending_delete"]["event_ids"]) == agent.MAX_PENDING_DELETES
    assert service.deleted == []


def test_delete_with_no_ids_does_not_produce_a_proposal(service):
    client = FakeClient(
        calls(tool_block("delete_events", {
            "event_ids": [], "summary": "nothing", "scope": "this_event",
        })),
        says("I couldn't find that on your calendar."),
    )
    result = run(client, service, "cancel my imaginary meeting")

    assert result["pending_delete"] is None
    assert service.deleted == []
    # The model is told the call was empty so it can recover, not that a
    # confirmation is pending when none is.
    payload = json.loads(client.requests[1]["messages"][-1]["content"][0]["content"])
    assert "no event ids" in payload["error"]


def test_confirming_a_proposal_is_what_actually_deletes(service):
    outcome = agent.confirm_delete(service, {
        "event_ids": ["evt_a", "evt_b"], "summary": "two things", "scope": "this_event",
    })
    assert service.deleted == ["evt_a", "evt_b"]
    assert outcome["deleted"] == ["evt_a", "evt_b"]


# ---------- non-calendar input ----------

def test_small_talk_creates_nothing(service):
    client = FakeClient(says("I only handle calendar requests."))
    result = run(client, service, "what's the weather like")

    assert result["created"] == []
    assert result["pending_delete"] is None
    assert service.inserted == []


def test_a_refusal_is_reported_without_touching_the_calendar(service):
    from conftest import Response
    client = FakeClient(Response([], "refusal"))
    result = run(client, service, "something disallowed")

    assert "can't help" in result["reply"]
    assert service.inserted == []


# ---------- loop safety ----------

def test_a_model_stuck_in_a_loop_is_cut_off(service):
    # More scripted tool calls than MAX_TURNS allows.
    searching = [
        calls(tool_block("search_events", {
            "time_min": "2026-09-14T00:00:00", "time_max": "2026-09-21T00:00:00", "query": "",
        }, f"toolu_{i}"))
        for i in range(agent.MAX_TURNS + 3)
    ]
    client = FakeClient(*searching)
    result = run(client, service, "go in circles")

    assert len(client.requests) == agent.MAX_TURNS
    assert "one thing at a time" in result["reply"]


def test_unknown_tool_name_is_reported_back_rather_than_crashing(service):
    client = FakeClient(
        calls(tool_block("obliterate_calendar", {})),
        says("I can't do that."),
    )
    result = run(client, service, "obliterate everything")

    payload = json.loads(client.requests[1]["messages"][-1]["content"][0]["content"])
    assert "unknown tool" in payload["error"]
    assert service.deleted == []


# ---------- prompt wiring ----------

def test_the_model_is_told_the_users_local_date_and_zone(service):
    client = FakeClient(says("ok"))
    run(client, service, "hello")

    system = client.requests[0]["system"]
    assert "Monday, September 14, 2026" in system
    assert TZ in system


def test_every_tool_is_offered_on_each_request(service):
    client = FakeClient(says("ok"))
    run(client, service, "hello")

    names = {t["name"] for t in client.requests[0]["tools"]}
    assert names == {"create_events", "search_events", "delete_events"}
