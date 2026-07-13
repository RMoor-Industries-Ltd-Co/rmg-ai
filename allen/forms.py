"""Virtual forms — ALLEN's structured "slot-filling" tools for common personal, project,
and business requests (schedule an appointment, open a PIAAR initiative, log a business
task, ...). Each stored form becomes its own dynamically-generated tool (submit_form_<key>)
with its own required fields, so Claude's native tool-calling enforces "ask if a required
field is missing" rather than ALLEN guessing or inventing values — no bespoke UI needed,
the "form" is the tool schema itself.

ALLEN can also define NEW forms himself via the define_virtual_form meta-tool, so this
list grows with him rather than requiring a code deploy for every new structured request
type. New forms default to action='note' (logged as a memory) until a maintainer wires a
dedicated backend for them, same as the seeded starter forms below route to real actions."""

import re

from . import db

# Supported backend actions a form can route a submission to. 'note' is the safe
# fallback for anything without a dedicated integration yet (including ALLEN's own
# newly-defined forms) — it never fails to configure, unlike calendar/ClickUp/GitHub.
ACTIONS = {"calendar_event", "clickup_task", "github_initiative", "milestone_update", "note"}
DOMAINS = {"personal", "project", "business"}

# Starter forms — seeded per-namespace on first use. created_by='system'.
SEED_FORMS = [
    {
        "key": "schedule_appointment",
        "label": "Schedule an appointment",
        "domain": "personal",
        "action": "calendar_event",
        "fields": [
            {"name": "summary", "type": "string", "required": True, "description": "What is this appointment?"},
            {"name": "start", "type": "string", "required": True,
             "description": "Start date/time, ISO format (e.g. 2026-07-10T14:00:00) or a date for all-day"},
            {"name": "end", "type": "string", "required": False, "description": "End date/time, ISO format"},
            {"name": "location", "type": "string", "required": False},
            {"name": "notes", "type": "string", "required": False, "description": "Any extra detail"},
        ],
    },
    {
        "key": "personal_reminder",
        "label": "Save a personal reminder",
        "domain": "personal",
        "action": "note",
        "fields": [
            {"name": "title", "type": "string", "required": True, "description": "What to remember"},
            {"name": "details", "type": "string", "required": False},
            {"name": "due_date", "type": "string", "required": False, "description": "YYYY-MM-DD, if it's time-bound"},
        ],
    },
    {
        "key": "piaar_initiative",
        "label": "Open a new PIAAR initiative",
        "domain": "project",
        "action": "github_initiative",
        "fields": [
            {"name": "name", "type": "string", "required": True, "description": "Initiative name"},
            {"name": "repos", "type": "string", "required": True, "description": "Repo(s) touched, comma-separated"},
            {"name": "branch", "type": "string", "required": False, "description": "Branch name, if known yet"},
            {"name": "owner", "type": "string", "required": False, "description": "Who's driving — Rahm, Claude Code, or ALLEN"},
            {"name": "goal", "type": "string", "required": True, "description": "One-line goal"},
        ],
    },
    {
        "key": "project_milestone_step",
        "label": "Log a PIAAR project milestone step",
        "domain": "project",
        "action": "milestone_update",
        "fields": [
            {"name": "project_key", "type": "string", "required": True,
             "description": "PIAAR project key, e.g. connection-circle, rmg-ai, cappo-meridian (see allen/usage.py's PIAAR_PROJECTS for the full list)"},
            {"name": "milestone_title", "type": "string", "required": True, "description": "The milestone this step belongs to, e.g. 'User profile enhancements for contact management'"},
            {"name": "goal", "type": "string", "required": False, "description": "The milestone's completion/validation goal, e.g. 'Ship the invite feature'"},
            {"name": "step_title", "type": "string", "required": True, "description": "The specific step/subtask being logged"},
            {"name": "done", "type": "boolean", "required": True, "description": "Whether this step is now complete"},
        ],
    },
    {
        "key": "business_task",
        "label": "Create a business task (ClickUp)",
        "domain": "business",
        "action": "clickup_task",
        "fields": [
            {"name": "list_id", "type": "string", "required": True, "description": "ClickUp list id (use clickup_hierarchy to find it)"},
            {"name": "name", "type": "string", "required": True, "description": "Task title"},
            {"name": "description", "type": "string", "required": False},
            {"name": "due_date", "type": "string", "required": False, "description": "YYYY-MM-DD"},
            {"name": "priority", "type": "string", "required": False, "description": "urgent|high|normal|low"},
        ],
    },
]

# Meta-tools: always available, not per-form. Let ALLEN see and extend his own form set.
META_TOOLS = [
    {
        "name": "list_virtual_forms",
        "description": "List your available virtual forms (structured request types) — each shows its "
                       "domain, what it does, and its required fields. Check this before assuming a form "
                       "doesn't exist for something Rahm asked for.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "define_virtual_form",
        "description": "Create a NEW virtual form for a recurring type of structured request that doesn't "
                       "have one yet. CONFIRM with Rahm before creating a form he hasn't asked for — this is "
                       "for when he agrees a new one is worth having, not a silent background action. Provide "
                       "key (short slug, e.g. 'travel_request'), label, domain (personal|project|business), "
                       "and fields: a list of {name, type, required, description}. Leave action unset (or "
                       "'note') unless you know it should route to calendar/clickup/github — a maintainer can "
                       "wire a dedicated backend for it later; 'note' always works in the meantime.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "label": {"type": "string"},
                "domain": {"type": "string", "enum": sorted(DOMAINS)},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                            "required": {"type": "boolean"},
                            "description": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "action": {"type": "string", "enum": sorted(ACTIONS)},
            },
            "required": ["key", "label", "domain", "fields"],
        },
    },
]

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def ensure_seed_forms(namespace: str) -> None:
    if not db.db_ready():
        return
    existing = {f["key"] for f in db.list_forms(namespace)}
    for f in SEED_FORMS:
        if f["key"] not in existing:
            db.upsert_form(namespace, f["key"], f["label"], f["domain"], f["action"], f["fields"], created_by="system")


def build_tool_schemas(namespace: str) -> list[dict]:
    """One dynamically-generated tool per stored form, named submit_form_<key>. Anthropic's
    tool-calling won't invoke a tool without its required params — that's the enforcement."""
    if not db.db_ready():
        return []
    tools = []
    for f in db.list_forms(namespace):
        props = {}
        required = []
        for field in f["fields"]:
            props[field["name"]] = {
                "type": field.get("type") or "string",
                "description": field.get("description") or "",
            }
            if field.get("required"):
                required.append(field["name"])
        tools.append({
            "name": f"submit_form_{f['key']}",
            "description": f"[{f['domain']}] {f['label']}. If a required field below is missing from what "
                           f"Rahm told you, ASK him for it — never guess, invent, or leave it blank.",
            "input_schema": {"type": "object", "properties": props, "required": required},
        })
    return tools


def list_forms_summary(namespace: str) -> str:
    forms = db.list_forms(namespace)
    if not forms:
        return "No virtual forms yet."
    lines = []
    for f in forms:
        req = [fld["name"] for fld in f["fields"] if fld.get("required")]
        opt = [fld["name"] for fld in f["fields"] if not fld.get("required")]
        lines.append(
            f"- {f['key']} [{f['domain']}] — {f['label']} "
            f"(required: {', '.join(req) or 'none'}; optional: {', '.join(opt) or 'none'})"
            + (" [ALLEN-defined]" if f.get("created_by") == "allen" else "")
        )
    return "\n".join(lines)


def define_form(namespace: str, args: dict) -> str:
    key = (args.get("key") or "").strip().lower()
    if not _KEY_RE.match(key):
        return "Invalid key — use lowercase letters/numbers/underscores, 3-40 chars, starting with a letter."
    domain = (args.get("domain") or "").strip().lower()
    if domain not in DOMAINS:
        return f"domain must be one of: {', '.join(sorted(DOMAINS))}"
    action = (args.get("action") or "note").strip().lower()
    if action not in ACTIONS:
        return f"action must be one of: {', '.join(sorted(ACTIONS))} (default 'note' if unsure)"
    fields = args.get("fields") or []
    if not isinstance(fields, list) or not fields:
        return "fields must be a non-empty list of {name, type, required, description}."
    clean_fields = []
    for fld in fields:
        if not isinstance(fld, dict) or not fld.get("name"):
            return "each field needs at least a 'name'."
        clean_fields.append({
            "name": fld["name"],
            "type": fld.get("type") or "string",
            "required": bool(fld.get("required")),
            "description": fld.get("description") or "",
        })
    label = (args.get("label") or key).strip()
    db.upsert_form(namespace, key, label, domain, action, clean_fields, created_by="allen")
    return f"Created form '{key}' [{domain}] — call it as submit_form_{key}."


def _initiative_row(values: dict, next_num: int) -> str:
    name = values.get("name", "").strip()
    repos = values.get("repos", "").strip()
    branch = values.get("branch", "").strip() or "TBD"
    owner = values.get("owner", "").strip() or "TBD"
    goal = values.get("goal", "").strip()
    return f"| {next_num} | {name} | {repos} | `{branch}` | Planning | {owner} | {goal} |"


def _dispatch_github_initiative(values: dict) -> str:
    from . import tools_github

    if not settings_github_ready():
        return "GitHub is not configured yet (allen-piaar-control-bot App credentials missing)."
    path = "docs/INITIATIVES.md"
    content = tools_github.read_file_full("rmg-piaar-system", path)
    if content is None:
        return f"Could not read {path} from rmg-piaar-system (unexpected: it's a directory?)."
    row_matches = list(re.finditer(r"^\|\s*(\d+)\s*\|", content, re.MULTILINE))
    next_num = (max(int(m.group(1)) for m in row_matches) + 1) if row_matches else 0
    new_row = _initiative_row(values, next_num)
    if row_matches:
        last = row_matches[-1]
        insert_at = content.index("\n", last.start()) + 1
        updated = content[:insert_at] + new_row + "\n" + content[insert_at:]
    else:
        updated = content.rstrip() + "\n" + new_row + "\n"
    msg = f"Add Initiative #{next_num}: {values.get('name', '').strip()} (via ALLEN)"
    return tools_github.handle("github_update_file", {"repo": "rmg-piaar-system", "path": path, "content": updated, "message": msg})


def settings_github_ready() -> bool:
    from .config import settings

    return settings.github_ready


def dispatch_submit(namespace: str, tool_name: str, args: dict) -> str:
    key = tool_name[len("submit_form_"):] if tool_name.startswith("submit_form_") else tool_name
    form = db.get_form(namespace, key)
    if not form:
        return f"Unknown form: {key}"
    action = form["action"]
    args = args or {}

    if action == "calendar_event":
        from . import tools_calendar

        return tools_calendar.handle("calendar_create_event", {
            "summary": args.get("summary", ""),
            "start": args.get("start", ""),
            "end": args.get("end"),
            "location": args.get("location"),
            "description": args.get("notes"),
        })

    if action == "clickup_task":
        from . import tools_clickup

        return tools_clickup.handle("clickup_create_task", args)

    if action == "github_initiative":
        return _dispatch_github_initiative(args)

    if action == "milestone_update":
        from . import db as _db

        project_key = args.get("project_key", "")
        milestone_title = args.get("milestone_title", "")
        step_title = args.get("step_title", "")
        done = bool(args.get("done"))
        if not (project_key and milestone_title and step_title):
            return "Missing project_key, milestone_title, or step_title."
        goal = args.get("goal") or ""
        if goal and not _db.get_milestone(project_key, milestone_title):
            _db.upsert_milestone(project_key, milestone_title, goal, [], created_by="allen")
        m = _db.set_step_done(project_key, milestone_title, step_title, done)
        if not m:
            return f"Could not find or create milestone '{milestone_title}' for {project_key}."
        status = "done" if done else "not done"
        return f"Logged: {project_key} · {milestone_title} · {step_title} → {status}."

    # 'note' — the universal fallback, including every form ALLEN defines himself
    # until a maintainer wires it to a dedicated backend.
    from . import db as _db

    title = args.get("title") or args.get("name") or form["label"]
    body_bits = [f"{k}: {v}" for k, v in args.items() if v]
    content = f"[{key}] {title}" + ("\n" + "\n".join(body_bits) if body_bits else "")
    _db.add_memory(namespace, content, memory_class="commitment", source="allen_form")
    return f"Saved '{title}' as a memory (form '{key}' has no dedicated backend yet)."
