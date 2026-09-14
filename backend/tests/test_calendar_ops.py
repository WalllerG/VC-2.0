"""The Google Calendar layer: time conversion, body shaping, scoped deletes."""
import pytest
from conftest import TZ, FakeService, http_error

import calendar_ops


# ---------- time conversion ----------

def test_naive_local_time_gains_the_users_offset():
    # September is EDT, so Toronto is UTC-4.
    assert calendar_ops.to_rfc3339("2026-09-19T12:00:00", TZ).endswith("-04:00")


def test_winter_date_uses_standard_time_not_a_fixed_offset():
    assert calendar_ops.to_rfc3339("2026-01-15T12:00:00", TZ).endswith("-05:00")


def test_existing_offset_is_preserved():
    assert calendar_ops.to_rfc3339("2026-09-19T12:00:00+09:00", TZ).endswith("+09:00")


def test_unknown_timezone_falls_back_instead_of_raising():
    assert calendar_ops.to_rfc3339("2026-09-19T12:00:00", "Mars/Olympus")


# ---------- event bodies ----------

def test_empty_optional_fields_are_dropped():
    body = calendar_ops.build_event_body({
        "summary": "Lunch",
        "start_datetime": "2026-09-19T12:00:00",
        "end_datetime": "2026-09-19T13:00:00",
        "location": "",
        "description": "   ",
        "recurrence": [],
    }, TZ)
    assert "location" not in body and "description" not in body
    assert "recurrence" not in body
    assert body["start"] == {"dateTime": "2026-09-19T12:00:00", "timeZone": TZ}


def test_populated_fields_are_kept():
    body = calendar_ops.build_event_body({
        "summary": "Gym",
        "start_datetime": "2026-09-21T07:00:00",
        "end_datetime": "2026-09-21T08:00:00",
        "location": "YMCA",
        "description": "leg day",
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4"],
    }, TZ)
    assert body["location"] == "YMCA"
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4"]


def test_missing_summary_gets_a_placeholder_rather_than_failing():
    body = calendar_ops.build_event_body({
        "summary": "",
        "start_datetime": "2026-09-19T12:00:00",
        "end_datetime": "2026-09-19T13:00:00",
    }, TZ)
    assert body["summary"] == "Untitled event"


# ---------- creating ----------

def test_creating_several_events_inserts_each_one(service):
    made = calendar_ops.create_events(service, [
        {"summary": "Dentist", "start_datetime": "2026-09-15T15:00:00",
         "end_datetime": "2026-09-15T16:00:00"},
        {"summary": "Haircut", "start_datetime": "2026-09-17T17:00:00",
         "end_datetime": "2026-09-17T18:00:00"},
    ], TZ)
    assert [e["summary"] for e in made] == ["Dentist", "Haircut"]
    assert len(service.inserted) == 2


def test_recurring_event_is_flagged_in_the_result(service):
    made = calendar_ops.create_events(service, [
        {"summary": "Standup", "start_datetime": "2026-09-21T09:00:00",
         "end_datetime": "2026-09-21T09:15:00",
         "recurrence": ["RRULE:FREQ=DAILY;COUNT=5"]},
    ], TZ)
    assert made[0]["recurring"] is True


# ---------- searching ----------

def test_search_expands_recurring_events_and_orders_them(service):
    calendar_ops.search_events(service, "2026-09-14T00:00:00", "2026-09-21T00:00:00", "", TZ)
    params = service.list_params[0]
    assert params["singleEvents"] is True
    assert params["orderBy"] == "startTime"


def test_blank_query_is_omitted_so_the_whole_window_comes_back(service):
    calendar_ops.search_events(service, "2026-09-14T00:00:00", "2026-09-21T00:00:00", "  ", TZ)
    assert "q" not in service.list_params[0]


def test_query_is_passed_through_when_given(service):
    calendar_ops.search_events(service, "2026-09-14T00:00:00", "2026-09-21T00:00:00", "dentist", TZ)
    assert service.list_params[0]["q"] == "dentist"


def test_search_surfaces_the_series_id_for_recurring_instances():
    service = FakeService(items=[{
        "id": "inst_1", "summary": "Standup",
        "start": {"dateTime": "2026-09-21T09:00:00-04:00"},
        "recurringEventId": "series_1",
    }])
    found = calendar_ops.search_events(service, "2026-09-21T00:00:00", "2026-09-22T00:00:00", "", TZ)
    assert found[0]["recurring_event_id"] == "series_1"


# ---------- deleting ----------

def test_this_event_scope_deletes_exactly_the_given_ids(service):
    outcome = calendar_ops.delete_events(service, ["a", "b"], "this_event")
    assert service.deleted == ["a", "b"]
    assert outcome["deleted"] == ["a", "b"]


def test_all_events_scope_deletes_the_series_not_the_instance():
    service = FakeService(items=[
        {"id": "inst_1", "recurringEventId": "series_1"},
    ])
    calendar_ops.delete_events(service, ["inst_1"], "all_events")
    assert service.deleted == ["series_1"]


def test_all_events_collapses_siblings_into_one_delete():
    service = FakeService(items=[
        {"id": "inst_1", "recurringEventId": "series_1"},
        {"id": "inst_2", "recurringEventId": "series_1"},
        {"id": "inst_3", "recurringEventId": "series_1"},
    ])
    calendar_ops.delete_events(service, ["inst_1", "inst_2", "inst_3"], "all_events")
    assert service.deleted == ["series_1"]


def test_non_recurring_event_is_unaffected_by_all_events_scope():
    service = FakeService(items=[{"id": "solo_1"}])
    calendar_ops.delete_events(service, ["solo_1"], "all_events")
    assert service.deleted == ["solo_1"]


def test_already_deleted_event_counts_as_missing_not_failed(service):
    service.delete_errors["gone"] = http_error(410)
    outcome = calendar_ops.delete_events(service, ["gone"], "this_event")
    assert outcome["missing"] == ["gone"]
    assert outcome["failed"] == []


def test_one_bad_id_does_not_stop_the_others(service):
    service.delete_errors["boom"] = http_error(500)
    outcome = calendar_ops.delete_events(service, ["ok1", "boom", "ok2"], "this_event")
    assert service.deleted == ["ok1", "ok2"]
    assert len(outcome["failed"]) == 1
