"""The command agent: one sentence in, calendar changes out.

Claude picks the tools; this module executes the safe ones and stops at the
destructive one. Deleting is never carried out here — `delete_events` only ever
produces a proposal that a human has to approve, so a misheard sentence (or a
malicious event title picked up during a search) cannot remove anything on its
own.
"""
import datetime
import json

import anthropic

import calendar_ops
from vcparser import api_key, resolve_timezone

MODEL = "claude-opus-5"
# Generous enough for a handful of tool calls plus thinking, small enough that a
# runaway turn doesn't leave someone staring at a spinner.
MAX_TOKENS = 8192
# Each pass is a round trip. Search -> create -> reply is three; anything past
# six means the model is stuck rather than working.
MAX_TURNS = 6
# A delete proposal rides in a signed session cookie, so it has to stay small.
MAX_PENDING_DELETES = 20

TOOLS = [
    {
        "name": "create_events",
        "description": (
            "Add one or more events to the user's calendar. Pass every event the "
            "user asked for in a single call — one sentence often describes several. "
            "Use the recurrence field for anything that repeats."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "description": "The events to create, in the order the user mentioned them.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "Event title, e.g. 'Lunch with Sarah'.",
                            },
                            "start_datetime": {
                                "type": "string",
                                "description": "Local start time as YYYY-MM-DDTHH:MM:SS. No timezone offset.",
                            },
                            "end_datetime": {
                                "type": "string",
                                "description": "Local end time as YYYY-MM-DDTHH:MM:SS. No timezone offset.",
                            },
                            "location": {
                                "type": "string",
                                "description": "Place name or address. Empty string if not mentioned.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Extra notes. Empty string if not mentioned.",
                            },
                            "recurrence": {
                                "type": "array",
                                "description": (
                                    "RRULE strings for repeating events, e.g. "
                                    "['RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4']. "
                                    "Empty array for a one-off event."
                                ),
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "summary", "start_datetime", "end_datetime",
                            "location", "description", "recurrence",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["events"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_events",
        "description": (
            "List the user's events in a time window. Call this before changing or "
            "deleting anything — it is the only way to get real event ids. "
            "The query field is a literal text match against titles and locations, "
            "not a semantic one, so prefer leaving it empty and picking the right "
            "event yourself from the returned window."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "time_min": {
                    "type": "string",
                    "description": "Window start, local time as YYYY-MM-DDTHH:MM:SS.",
                },
                "time_max": {
                    "type": "string",
                    "description": "Window end, local time as YYYY-MM-DDTHH:MM:SS.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional literal text filter. Empty string lists the whole window.",
                },
            },
            "required": ["time_min", "time_max", "query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_events",
        "description": (
            "Propose deleting events the user asked to remove or cancel. Only pass "
            "ids returned by search_events — never invent one. The deletion does not "
            "happen when you call this: the user is shown your summary and has to "
            "approve it, so do not ask them to confirm yourself."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "event_ids": {
                    "type": "array",
                    "description": "Event ids from search_events.",
                    "items": {"type": "string"},
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "One short line naming what will be deleted, shown to the "
                        "user on the confirm button, e.g. 'Dentist on Fri Sep 19'."
                    ),
                },
                "scope": {
                    "type": "string",
                    "description": (
                        "'this_event' removes only the occurrences listed. "
                        "'all_events' removes the entire repeating series they belong to. "
                        "Ask the user which they meant if a repeating event is involved "
                        "and they did not say."
                    ),
                    "enum": ["this_event", "all_events"],
                },
            },
            "required": ["event_ids", "summary", "scope"],
            "additionalProperties": False,
        },
    },
]


def system_prompt(now: datetime.datetime, tz_name: str) -> str:
    return f"""You are VoiceCal, a calendar assistant. The user speaks or types one request at a time; carry it out with the tools.

Right now it is {now:%A, %B %d, %Y} at {now:%I:%M %p} in {tz_name}.
Every time you supply must be local {tz_name} time written as YYYY-MM-DDTHH:MM:SS, with no timezone offset.

Creating:
- One sentence can describe several events. Put them all in a single create_events call.
- When the user gives no duration, pick a sensible one: meals, meetings and appointments an hour; a class or workout an hour; anything explicitly stated wins.
- "Every Tuesday", "daily for a week", "monthly" mean a recurrence RRULE, not repeated events.

Changing and removing:
- Always call search_events first to get real ids. Never guess an id.
- Then call delete_events. A human approves it afterwards, so do not ask "are you sure".
- If the event repeats and the user was ambiguous about one occurrence versus the series, ask which they meant instead of guessing.
- If nothing matches, say so plainly and suggest what you did look at.

Replying:
- Keep it to one short sentence. The interface already shows the event details, so do not repeat times and titles back.
- If the request has nothing to do with the calendar, just answer briefly in text without calling a tool."""


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


def run_command(client, service, text: str, tz_name: str, now=None) -> dict:
    """Drive one user utterance to completion.

    Returns {reply, created, pending_delete}. `pending_delete` is non-None when
    the user has to approve a deletion before anything is removed.
    """
    tz_name, tz = resolve_timezone(tz_name)
    now = now or datetime.datetime.now(tz)

    messages = [{"role": "user", "content": text}]
    created: list = []

    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt(now, tz_name),
            tools=TOOLS,
            output_config={"effort": "medium"},
            messages=messages,
        )

        # Opus 5's safety classifiers can decline; content is empty or partial
        # when that happens, so check before reading it.
        if response.stop_reason == "refusal":
            return {"reply": "I can't help with that one.", "created": created,
                    "pending_delete": None}

        if response.stop_reason != "tool_use":
            return {"reply": _text_of(response) or "Done.", "created": created,
                    "pending_delete": None}

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        pending_delete = None

        for block in (b for b in response.content if b.type == "tool_use"):
            if block.name == "create_events":
                made = calendar_ops.create_events(
                    service, block.input.get("events", []), tz_name)
                created.extend(made)
                result = {"created": made}

            elif block.name == "search_events":
                found = calendar_ops.search_events(
                    service,
                    block.input.get("time_min", ""),
                    block.input.get("time_max", ""),
                    block.input.get("query", ""),
                    tz_name,
                )
                # Event titles come from the calendar, which anyone who knows the
                # user's address can write to via an invite. They are quoted back
                # to the model as data; the confirm gate below is what keeps a
                # hostile title from being able to act.
                result = {"events": found, "count": len(found)}

            elif block.name == "delete_events":
                ids = [i for i in block.input.get("event_ids", []) if i][:MAX_PENDING_DELETES]
                if ids:
                    pending_delete = {
                        "event_ids": ids,
                        "summary": block.input.get("summary") or "these events",
                        "scope": block.input.get("scope") or "this_event",
                    }
                result = {"status": "awaiting user confirmation"}

            else:
                result = {"error": f"unknown tool {block.name}"}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

        if pending_delete:
            return {"reply": _text_of(response), "created": created,
                    "pending_delete": pending_delete}

        messages.append({"role": "user", "content": tool_results})

    return {"reply": "That took more steps than expected — try asking for one thing at a time.",
            "created": created, "pending_delete": None}


def confirm_delete(service, pending: dict) -> dict:
    """Carry out a delete the user approved.

    For 'all_events' the series id is used where the search returned one, since
    deleting an instance id only cancels that single occurrence.
    """
    return calendar_ops.delete_events(service, pending.get("event_ids", []),
                                      pending.get("scope", "this_event"))


def make_client():
    return anthropic.Anthropic(api_key=api_key())
