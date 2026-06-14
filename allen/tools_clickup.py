"""ClickUp tool client — ALLIE's (and ALLEN's) window into the project-management framework.
Read-only: workspace structure, list tasks, read a task. `business_only` scopes ALLIE away from
the PERSONAL SYSTEMS and AMG spaces (the gatekeeper boundary, enforced at the tool layer)."""

import requests

from .config import settings

BASE = "https://api.clickup.com/api/v2"
_PERSONAL_SPACES = ("personal", "amg")  # name fragments ALLIE must not enter

TOOLS = [
    {
        "name": "clickup_hierarchy",
        "description": "List the ClickUp workspace structure — spaces, folders, and lists with their ids. "
                       "Start here to find where a project, task list, or record lives.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "clickup_list_tasks",
        "description": "List the tasks in a ClickUp list. Provide list_id (from clickup_hierarchy). Set "
                       "include_closed true to also see completed tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "ClickUp list id"},
                "include_closed": {"type": "boolean"},
            },
            "required": ["list_id"],
        },
    },
    {
        "name": "clickup_get_task",
        "description": "Get one ClickUp task in full — name, status, description, dates, assignees. Provide task_id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "ClickUp task id"}},
            "required": ["task_id"],
        },
    },
]


def _h() -> dict:
    return {"Authorization": settings.clickup_api_token}


def _get(path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{BASE}{path}", headers=_h(), params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _is_personal(name: str) -> bool:
    n = (name or "").lower()
    return any(p in n for p in _PERSONAL_SPACES)


def _hierarchy(business_only: bool) -> str:
    spaces = _get(f"/team/{settings.clickup_team_id}/space", {"archived": "false"}).get("spaces", [])
    out: list[str] = []
    for s in spaces:
        if business_only and _is_personal(s.get("name", "")):
            continue
        out.append(f"SPACE: {s['name']} (id {s['id']})")
        try:
            folders = _get(f"/space/{s['id']}/folder", {"archived": "false"}).get("folders", [])
        except Exception:
            folders = []
        for f in folders:
            out.append(f"  FOLDER: {f['name']} (id {f['id']})")
            for lst in f.get("lists", []):
                out.append(f"    LIST: {lst['name']} (id {lst['id']})")
        try:
            loose = _get(f"/space/{s['id']}/list", {"archived": "false"}).get("lists", [])
        except Exception:
            loose = []
        for lst in loose:
            out.append(f"  LIST: {lst['name']} (id {lst['id']})")
    return "\n".join(out) or "No spaces found."


def _list_tasks(list_id: str, include_closed: bool) -> str:
    data = _get(f"/list/{list_id}/task", {"include_closed": "true" if include_closed else "false", "subtasks": "true"})
    tasks = data.get("tasks", [])
    if not tasks:
        return "No tasks in that list."
    lines = []
    for t in tasks[:60]:
        status = (t.get("status") or {}).get("status", "?")
        due = t.get("due_date")
        lines.append(f"- [{status}] {t.get('name','(untitled)')} (id {t['id']})" + (f" due:{due}" if due else ""))
    return "\n".join(lines)


def _get_task(task_id: str) -> str:
    t = _get(f"/task/{task_id}")
    status = (t.get("status") or {}).get("status", "?")
    assignees = ", ".join(a.get("username", "") for a in t.get("assignees", [])) or "none"
    desc = (t.get("text_content") or t.get("description") or "").strip() or "(no description)"
    return (
        f"Task: {t.get('name','')}\nStatus: {status}\nAssignees: {assignees}\n"
        f"Due: {t.get('due_date')}\n\nDescription:\n{desc[:4000]}"
    )


def handle(name: str, args: dict, business_only: bool = False) -> str:
    if not settings.clickup_ready:
        return "ClickUp is not configured."
    args = args or {}
    try:
        if name == "clickup_hierarchy":
            return _hierarchy(business_only)
        if name == "clickup_list_tasks":
            return _list_tasks(args["list_id"], bool(args.get("include_closed")))
        if name == "clickup_get_task":
            return _get_task(args["task_id"])
    except requests.HTTPError as e:
        return f"ClickUp API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"ClickUp call failed: {e}"
    return f"(unknown ClickUp tool: {name})"
