"""ClickUp tool client — ALLIE's (and ALLEN's) window into the project-management framework.
Read-only: workspace structure, list tasks, read a task. `business_only` scopes ALLIE away from
the PERSONAL SYSTEMS and AMG spaces (the gatekeeper boundary, enforced at the tool layer)."""

from datetime import datetime, timezone

import requests

from .config import settings

BASE = "https://api.clickup.com/api/v2"


def _category(name: str) -> str:
    """Classify a space: 'personal' (Rahm's life), 'amg' (Cappo's separate system), else 'business'."""
    n = (name or "").lower()
    if "personal" in n:
        return "personal"
    if "amg" in n:
        return "amg"
    return "business"

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


WRITE_TOOLS = [
    {
        "name": "clickup_create_task",
        "description": "Create a new task in a ClickUp list. Provide list_id (from clickup_hierarchy) and name; "
                       "optionally description, status, due_date (YYYY-MM-DD), priority (urgent|high|normal|low).",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string"}, "name": {"type": "string"},
                "description": {"type": "string"}, "status": {"type": "string"},
                "due_date": {"type": "string"}, "priority": {"type": "string"},
            },
            "required": ["list_id", "name"],
        },
    },
    {
        "name": "clickup_update_task",
        "description": "Update an existing task. Provide task_id and any of: name, description, status, "
                       "due_date (YYYY-MM-DD), priority (urgent|high|normal|low).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"}, "name": {"type": "string"},
                "description": {"type": "string"}, "status": {"type": "string"},
                "due_date": {"type": "string"}, "priority": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "clickup_comment_task",
        "description": "Add a comment/note to a task. Provide task_id and comment.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}, "comment": {"type": "string"}},
            "required": ["task_id", "comment"],
        },
    },
    {
        "name": "clickup_create_list",
        "description": "Create a list. Provide name and EITHER folder_id OR space_id (for a folderless list).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "folder_id": {"type": "string"}, "space_id": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "clickup_create_folder",
        "description": "Create a folder in a space. Provide space_id and name.",
        "input_schema": {
            "type": "object",
            "properties": {"space_id": {"type": "string"}, "name": {"type": "string"}},
            "required": ["space_id", "name"],
        },
    },
    {
        "name": "clickup_delete_task",
        "description": "Permanently delete a task. Provide task_id. Use carefully — this cannot be undone.",
        "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
    },
]

WRITE_NAMES = {t["name"] for t in WRITE_TOOLS}  # mutating tools — recorded in the audit log

_PRIORITY = {"urgent": 1, "high": 2, "normal": 3, "low": 4}


def _h() -> dict:
    return {"Authorization": settings.clickup_api_token}


def _get(path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{BASE}{path}", headers=_h(), params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _send(method: str, path: str, body: dict) -> dict:
    r = requests.request(method, f"{BASE}{path}", headers={**_h(), "Content-Type": "application/json"}, json=body, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}


def _to_ms(due) -> int | None:
    if not due:
        return None
    s = str(due).strip()
    if s.isdigit():
        return int(s)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return None


def _prio(p) -> int | None:
    if p is None or p == "":
        return None
    if isinstance(p, str) and p.lower() in _PRIORITY:
        return _PRIORITY[p.lower()]
    try:
        return int(p)
    except (ValueError, TypeError):
        return None


def _task_body(args: dict) -> dict:
    body: dict = {}
    for k in ("name", "description", "status"):
        if args.get(k):
            body[k] = args[k]
    ms = _to_ms(args.get("due_date"))
    if ms:
        body["due_date"] = ms
    pr = _prio(args.get("priority"))
    if pr:
        body["priority"] = pr
    return body


def _create_task(args: dict) -> str:
    body = _task_body(args)
    t = _send("POST", f"/list/{args['list_id']}/task", body)
    return f"Created task '{t.get('name')}' (id {t.get('id')}) — {t.get('url','')}"


def _update_task(args: dict) -> str:
    body = _task_body(args)
    if not body:
        return "Nothing to update — provide a field (name, status, due_date, priority, description)."
    _send("PUT", f"/task/{args['task_id']}", body)
    return f"Updated task {args['task_id']}: " + ", ".join(f"{k}={v}" for k, v in body.items())


def _comment_task(args: dict) -> str:
    _send("POST", f"/task/{args['task_id']}/comment", {"comment_text": args["comment"]})
    return f"Comment added to task {args['task_id']}."


def _create_list(args: dict) -> str:
    if args.get("folder_id"):
        lst = _send("POST", f"/folder/{args['folder_id']}/list", {"name": args["name"]})
    elif args.get("space_id"):
        lst = _send("POST", f"/space/{args['space_id']}/list", {"name": args["name"]})
    else:
        return "Provide folder_id or space_id."
    return f"Created list '{lst.get('name')}' (id {lst.get('id')})."


def _create_folder(args: dict) -> str:
    f = _send("POST", f"/space/{args['space_id']}/folder", {"name": args["name"]})
    return f"Created folder '{f.get('name')}' (id {f.get('id')})."


def _delete_task(args: dict) -> str:
    _send("DELETE", f"/task/{args['task_id']}", {})
    return f"Deleted task {args['task_id']}."


def _in_scope(name: str, scope: str) -> bool:
    cat = _category(name)
    if scope == "all":
        return True
    if scope == "personal":
        return cat == "personal"
    if scope == "business":
        # ALLIE: business spaces; AMG only once enabled (Cappo maturing under her)
        return cat == "business" or (cat == "amg" and settings.allie_amg_enabled)
    return False


def _hierarchy(scope: str) -> str:
    spaces = _get(f"/team/{settings.clickup_team_id}/space", {"archived": "false"}).get("spaces", [])
    out: list[str] = []
    for s in spaces:
        if not _in_scope(s.get("name", ""), scope):
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


def handle(name: str, args: dict, scope: str = "all") -> str:
    """scope: 'all' | 'business' (RMG/RMI, ALLIE) | 'personal' (PERSONAL SYSTEMS, ALLEN direct)."""
    if not settings.clickup_ready:
        return "ClickUp is not configured."
    args = args or {}
    try:
        if name == "clickup_hierarchy":
            return _hierarchy(scope)
        if name == "clickup_list_tasks":
            return _list_tasks(args["list_id"], bool(args.get("include_closed")))
        if name == "clickup_get_task":
            return _get_task(args["task_id"])
        # writes
        if name == "clickup_create_task":
            return _create_task(args)
        if name == "clickup_update_task":
            return _update_task(args)
        if name == "clickup_comment_task":
            return _comment_task(args)
        if name == "clickup_create_list":
            return _create_list(args)
        if name == "clickup_create_folder":
            return _create_folder(args)
        if name == "clickup_delete_task":
            return _delete_task(args)
    except requests.HTTPError as e:
        return f"ClickUp API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"ClickUp call failed: {e}"
    return f"(unknown ClickUp tool: {name})"
