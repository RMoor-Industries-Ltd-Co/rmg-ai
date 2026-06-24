"""Google Calendar tool client — multi-account CRUD over Rahm's calendars.

Each tool accepts an optional `account` param (default: rahmind.consulting@rmoorind.com).
Tokens are stored in app_config via google_auth; legacy single-account tokens remain
honored for the default account.
"""

import requests

from . import db, google_auth
from .config import settings

CAL_BASE = "https://www.googleapis.com/calendar/v3"
_TZ = "America/New_York"

TOOLS = [
    {
        "name": "calendar_list_events",
        "description": (
            "List Rahm's upcoming calendar events between time_min and time_max "
            "(ISO date or datetime, e.g. 2026-06-14 or 2026-06-14T09:00:00). "
            "Defaults to the next 7 days. Optionally specify account "
            "(default: rahmind.consulting@rmoorind.com)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
                "account": {
                    "type": "string",
                    "description": "which of Rahm's Google accounts to query",
                },
            },
        },
    },
    {
        "name": "calendar_create_event",
        "description": (
            "Create a calendar event. Provide summary, start and end (ISO datetime like "
            "2026-06-20T14:00:00, or a date like 2026-06-20 for all-day); "
            "optional description, location, account."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["summary", "start"],
        },
    },
    {
        "name": "calendar_update_event",
        "description": (
            "Update/reschedule an event by event_id. "
            "Provide any of: summary, start, end, description, location, account."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "summary": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_delete_event",
        "description": "Delete a calendar event by event_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
]

WRITE_NAMES = {"calendar_create_event", "calendar_update_event", "calendar_delete_event"}


def ready() -> bool:
    """True if OAuth client is configured and the default account has a token."""
    return google_auth.oauth_ready() and bool(
        google_auth.refresh_token_for(google_auth.default_account())
    )


def _when(value: str) -> dict:
    """ISO datetime -> {dateTime, timeZone}; date-only -> {date} (all-day)."""
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
    elif args.get("start"):
        body["end"] = _when(args["start"])
    return body


def _cal(account: str) -> str:
    if account == google_auth.default_account():
        return settings.google_calendar_id or "primary"
    return "primary"


def _iso(v: str) -> str:
    v = (v or "").strip()
    if len(v) == 10 and v.count("-") == 2:
        return v + "T00:00:00Z"
    return v


def _list_events(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    params: dict = {"singleEvents": "true", "orderBy": "startTime", "maxResults": 20}
    if args.get("time_min"):
        params["timeMin"] = _iso(args["time_min"])
    if args.get("time_max"):
        params["timeMax"] = _iso(args["time_max"])
    r = requests.get(
        f"{CAL_BASE}/calendars/{_cal(account)}/events",
        headers=google_auth.auth_headers(account),
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return f"No events in that window for {account}."
    lines = [f"Calendar ({account}):"]
    for e in items:
        start = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date") or "?"
        lines.append(f"- {start} — {e.get('summary', '(no title)')} (id {e.get('id')})")
    return "\n".join(lines)


def _create(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    r = requests.post(
        f"{CAL_BASE}/calendars/{_cal(account)}/events",
        headers=google_auth.auth_headers(account),
        json=_event_body(args),
        timeout=30,
    )
    r.raise_for_status()
    e = r.json()
    return (
        f"Created event '{e.get('summary')}' (id {e.get('id')}) on {account}"
        f" — {e.get('htmlLink', '')}"
    )


def _update(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    body = _event_body({k: v for k, v in args.items() if k not in ("event_id", "account")})
    if not body:
        return "Nothing to update."
    r = requests.patch(
        f"{CAL_BASE}/calendars/{_cal(account)}/events/{args['event_id']}",
        headers=google_auth.auth_headers(account),
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return f"Updated event {args['event_id']} on {account}."


def _delete(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    r = requests.delete(
        f"{CAL_BASE}/calendars/{_cal(account)}/events/{args['event_id']}",
        headers=google_auth.auth_headers(account),
        timeout=30,
    )
    if r.status_code not in (200, 204):
        r.raise_for_status()
    return f"Deleted event {args['event_id']} from {account}."


def handle(name: str, args: dict) -> str:
    if not google_auth.oauth_ready():
        return "Google OAuth not configured (needs GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET)."
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
    except RuntimeError as e:
        return str(e)
    except requests.HTTPError as e:
        return f"Calendar API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"Calendar call failed: {e}"
    return f"(unknown calendar tool: {name})"
