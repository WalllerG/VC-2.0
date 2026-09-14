"""Google Calendar operations.

Every function takes an already-built `service` so the agent and the tests can
drive them without touching the network.
"""
import datetime

from googleapiclient.errors import HttpError

from vcparser import resolve_timezone

# Google caps events.list at 2500; we only ever need enough for the model to
# pick the right event out of a window, and a huge list just burns tokens.
MAX_SEARCH_RESULTS = 25


def to_rfc3339(local_iso: str, tz_name: str) -> str:
    """Turn 'YYYY-MM-DDTHH:MM:SS' in the user's zone into an offset-aware stamp.

    events.list rejects timestamps without an offset, and the model is asked for
    plain local times because offsets are exactly the thing it gets wrong.
    """
    _, tz = resolve_timezone(tz_name)
    text = (local_iso or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.datetime.fromisoformat(text[:19])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.isoformat()


def build_event_body(spec: dict, tz_name: str) -> dict:
    """Map the agent's flat event shape onto a Google Calendar event resource.

    The tool schema is strict, so the model sends every field every time and
    fills the irrelevant ones with "". Those get dropped here rather than
    written to the calendar as empty strings.
    """
    body = {
        "summary": (spec.get("summary") or "Untitled event").strip(),
        "start": {"dateTime": spec["start_datetime"], "timeZone": tz_name},
        "end": {"dateTime": spec["end_datetime"], "timeZone": tz_name},
    }
    for field in ("location", "description"):
        value = (spec.get(field) or "").strip()
        if value:
            body[field] = value
    recurrence = [r for r in (spec.get("recurrence") or []) if r and r.strip()]
    if recurrence:
        body["recurrence"] = recurrence
    return body


def create_events(service, specs: list, tz_name: str) -> list:
    """Insert each event, returning a compact record of what landed."""
    created = []
    for spec in specs:
        event = service.events().insert(
            calendarId="primary",
            body=build_event_body(spec, tz_name),
        ).execute()
        created.append({
            "id": event.get("id"),
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime")
                     or (event.get("start") or {}).get("date"),
            "link": event.get("htmlLink"),
            "recurring": bool(event.get("recurrence")),
        })
    return created


def search_events(service, time_min: str, time_max: str, query: str, tz_name: str) -> list:
    """List events in a window, optionally narrowed by Google's free-text search.

    singleEvents expands a recurring series into its instances, which is what
    makes "cancel Tuesday's standup" addressable; it is also required for
    orderBy=startTime.
    """
    params = {
        "calendarId": "primary",
        "timeMin": to_rfc3339(time_min, tz_name),
        "timeMax": to_rfc3339(time_max, tz_name),
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": MAX_SEARCH_RESULTS,
    }
    # `q` is a literal text match, not a semantic one, so an unmatched guess
    # returns nothing. Sending it only when the user named something concrete
    # lets the model do the matching over the full window instead.
    if (query or "").strip():
        params["q"] = query.strip()

    items = service.events().list(**params).execute().get("items", [])
    return [{
        "id": e.get("id"),
        "summary": e.get("summary") or "(no title)",
        "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
        "location": e.get("location") or "",
        # Present only on an instance of a repeating series — it is the handle
        # for "delete the whole thing" as opposed to "delete this one".
        "recurring_event_id": e.get("recurringEventId") or "",
    } for e in items]


def _series_id(service, event_id: str) -> str:
    """The id of the series an instance belongs to, or the instance itself."""
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
    except HttpError:
        return event_id
    return event.get("recurringEventId") or event_id


def delete_events(service, event_ids: list, scope: str = "this_event") -> dict:
    """Delete events, reporting per-id outcomes instead of failing the batch.

    scope="all_events" swaps each id for its parent series, because deleting an
    instance id only cancels that one occurrence. Several instances of the same
    series collapse to a single delete.

    One already-removed event should not abort the rest of the request, so each
    id is handled on its own and 404/410 counts as success, not failure.
    """
    targets: list = []
    for event_id in event_ids:
        target = _series_id(service, event_id) if scope == "all_events" else event_id
        if target not in targets:
            targets.append(target)

    deleted, missing, failed = [], [], []
    for target in targets:
        try:
            service.events().delete(calendarId="primary", eventId=target).execute()
            deleted.append(target)
        except HttpError as error:
            if getattr(error, "status_code", None) in (404, 410):
                missing.append(target)
            else:
                failed.append({"id": target, "error": str(error)})
    return {"deleted": deleted, "missing": missing, "failed": failed}
