"""Google Calendar tool client — ALLEN's CRUD over Rahm's personal calendar. Uses an OAuth
refresh token (captured via the /oauth/calendar flow, stored in app_config) to mint access
tokens on demand. Times are ISO 8601; a date-only value makes an all-day event."""

import requests

from . import db
from .config import settings

CAL_BASE = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
_TZ = "America/New_York"

TOOLS = [
    {
        "name": "calendar_list_events",
        "description": "List Rahm's upcoming calendar events between time_min and time_max (ISO date or "
                       "datetime, e.g. 2026-06-14 or 2026-06-14T09:00:00). Defaults to the next 7 days.",
        "input_schema": {
            "type": "object",
            "properties": {"time_min": {"type": "string"}, "time_max": {"type": "string"}},
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Create a calendar event. Provide summary, start and end (ISO datetime like "
                       "2026-06-20T14:00:00, or a date like 2026-06-20 for all-day); optional description, location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                "description": {"type": "string"}, "location": {"type": "string"},
            },
            "required": ["summary", "start"],
        },
    },
    {
        "name": "calendar_update_event",
        "description": "Update/reschedule an event by event_id. Provide any of: summary, start, end, "
                       "description, location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"}, "summary": {"type": "string"},
                "start": {"type": "string"}, "end": {"type": "string"},
                "description": {"type": "string"}, "location": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_delete_event",
        "description": "Delete a calendar event by event_id.",
        "input_schema": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]},
    },
]


WRITE_NAMES = {"calendar_create_event", "calendar_update_event", "calendar_delete_event"}


def refresh_token() -> str | None:
    return db.get_config("google_calendar_refresh_token") or settings.google_calendar_refresh_token or None


def ready() -> bool:
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret and refresh_token())


def _access_token() -> str:
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "refresh_token": refresh_token(),
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _h() -> dict:
    return {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}


def _when(value: str) -> dict:
    """ISO datetime -> {dateTime,timeZone}; date-only -> {date} (all-day)."""
    v = (value or "").strip()
    if len(v) == 10 and v.count("-") == 2:
        return {"date": v}
    return {"dateTime": v, "timeZone": _TZ}


def _event_body(args: dict) -> dict:
    body: dict = {}
    if args.get("summary"):
        body["summary"] = args["summary"]
    if args.get("description"):
        body["description"] = args["description"]
    if args.get("location"):
        body["location"] = args["location"]
    if args.get("start"):
        body["start"] = _when(args["start"])
    if args.get("end"):
        body["end"] = _when(args["end"])
    elif args.get("start"):  # default end = start (calendar needs both); all-day or same instant
        body["end"] = _when(args["start"])
    return body


def _cal() -> str:
    return settings.google_calendar_id or "primary"


def _list_events(args: dict) -> str:
    params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": 20}
    if args.get("time_min"):
        params["timeMin"] = _iso(args["time_min"])
    if args.get("time_max"):
        params["timeMax"] = _iso(args["time_max"])
    r = requests.get(f"{CAL_BASE}/calendars/{_cal()}/events", headers=_h(), params=params, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return "No events in that window."
    lines = []
    for e in items:
        start = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date") or "?"
        lines.append(f"- {start} — {e.get('summary','(no title)')} (id {e.get('id')})")
    return "\n".join(lines)


def _iso(v: str) -> str:
    v = (v or "").strip()
    if len(v) == 10 and v.count("-") == 2:
        return v + "T00:00:00Z"
    return v


def _create(args: dict) -> str:
    r = requests.post(f"{CAL_BASE}/calendars/{_cal()}/events", headers=_h(), json=_event_body(args), timeout=30)
    r.raise_for_status()
    e = r.json()
    return f"Created event '{e.get('summary')}' (id {e.get('id')}) — {e.get('htmlLink','')}"


def _update(args: dict) -> str:
    body = _event_body({k: v for k, v in args.items() if k != "event_id"})
    if not body:
        return "Nothing to update."
    r = requests.patch(f"{CAL_BASE}/calendars/{_cal()}/events/{args['event_id']}", headers=_h(), json=body, timeout=30)
    r.raise_for_status()
    return f"Updated event {args['event_id']}."


def _delete(args: dict) -> str:
    r = requests.delete(f"{CAL_BASE}/calendars/{_cal()}/events/{args['event_id']}", headers=_h(), timeout=30)
    if r.status_code not in (200, 204):
        r.raise_for_status()
    return f"Deleted event {args['event_id']}."


def handle(name: str, args: dict) -> str:
    if not ready():
        return "Calendar isn't connected yet (needs the one-time authorization)."
    args = args or {}
    try:
        if name == "calendar_list_events":
            return _list_events(args)
        if name == "calendar_create_event":
            return _create(args)
        if name == "calendar_update_event":
            return _update(args)
        if name == "calendar_delete_event":
            return _delete(args)
    except requests.HTTPError as e:
        return f"Calendar API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"Calendar call failed: {e}"
    return f"(unknown calendar tool: {name})"
