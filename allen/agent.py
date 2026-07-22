"""ALLEN's agentic layer. Rahm speaks only to ALLEN; ALLEN decides how to answer — and when a
request needs operational legwork (research, lookups, project/records/data across RMG or RMI) he
DELEGATES to ALLIE behind the scenes, then synthesizes her findings into his own spoken reply.

This wraps chat.build_system/build_user (ALLEN's exact persona) in a tool-use loop whose only tool,
for now, is delegate_to_allie. As ALLIE gains ClickUp/Notion tools, ALLEN's reach grows for free."""

import json
from typing import Optional

from . import allie, chat, db, forms
from .llm import get_llm


def _format_audit(rows: list) -> str:
    if not rows:
        return "No recent activity has been logged."
    lines = []
    for r in rows:
        ts = str(r.get("created_at"))[:16]
        what = (r.get("result") or r.get("detail") or "").replace("\n", " ")[:160]
        lines.append(f"[{ts}] {r['actor'].upper()} · {r['action']} — {what}")
    return "\n".join(lines)


def _send_alert(namespace: str, message: str) -> str:
    from . import whatsapp

    if not message.strip():
        return "No message given to send."
    whatsapp.send_message(f"🔔 {message}")
    db.add_audit(namespace, "allen", "send_alert", message, "sent")
    return "Sent."


def _schedule_reminder(namespace: str, message: str, due_at: str) -> str:
    from datetime import datetime

    if not message.strip():
        return "No reminder message given."
    try:
        due = datetime.fromisoformat(due_at.strip())
    except ValueError:
        return f"Couldn't parse due_at '{due_at}' as an ISO 8601 datetime — try again with an explicit offset."
    row = db.create_reminder(namespace, message, due)
    db.add_audit(namespace, "allen", "schedule_reminder", f"{message} @ {due_at}", row["id"])
    return f"Reminder scheduled for {due_at} (id {row['id']})."


def _format_reminders(rows: list) -> str:
    if not rows:
        return "No pending reminders."
    lines = [f"- [{r['id']}] {r['due_at']}: {r['message']}" for r in rows]
    return "\n".join(lines)


def _format_agent_rollup(rows: list) -> str:
    if not rows:
        return "No agent rollup has been generated yet — no PIAAR domain sources are configured."
    by_source = {r["source"]: r for r in rows}
    rollup = by_source.pop("allen_rollup", None)
    lines = []
    if rollup and rollup.get("report_text"):
        lines.append(rollup["report_text"])
    for source, r in by_source.items():
        status = "" if r.get("ok", True) else " (last pull failed)"
        lines.append(f"\n{source.upper()}{status}: {r.get('report_text') or '(no report yet)'}")
    return "\n".join(lines) if lines else "No agent rollup has been generated yet."

ALLEN_TOOLS = [
    {
        "name": "delegate_to_allie",
        "description": (
            "Hand an operational task to ALLIE, your Director of Operations / agentic engine, who works "
            "across Rahm's business worlds (RMG and RMI). Use her for anything needing legwork: research, "
            "looking things up, gathering or organizing facts/data/statistics, project tracking, records or "
            "governance support, drafting operational materials. She returns findings; you synthesize them "
            "into your spoken reply to Rahm. Do NOT use her for casual conversation or anything personal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "A clear, self-contained instruction for ALLIE. Include only the business context she "
                        "needs to do it — never Rahm's personal or private details."
                    ),
                }
            },
            "required": ["task"],
        },
    },
    {
        "name": "review_activity",
        "description": "Review the recent operational activity log — what you and ALLIE actually CHANGED in "
                       "ClickUp and the calendar (creates, updates, deletes) and what was delegated. Use when "
                       "Rahm asks what was done, what changed, or what ALLIE has been up to.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "how many recent entries (default 20)"}},
        },
    },
    {
        "name": "get_agent_rollup",
        "description": (
            "Read your latest PIAAR ecosystem executive rollup — a short synthesis across Cappo (AMG), "
            "Anpu, and Thoth (AXIS), already generated on a schedule and instant to read. Use this when "
            "Rahm asks what's going on across the ecosystem, PIAAR status, or a cross-domain summary — "
            "don't delegate to ALLIE just to check on things that are already cached here."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

# Gated on settings.whatsapp_ready and settings.database_url (see respond_agentic) rather
# than always advertised — reminders need both outbound delivery and persistence, and a
# tool ALLEN can call but that silently fails is worse than one he doesn't have.
REMINDER_TOOLS = [
    {
        "name": "send_alert",
        "description": (
            "Push a WhatsApp message to Rahm's phone RIGHT NOW — for something urgent or worth flagging "
            "the moment you notice it, not on the daily briefing schedule. Use sparingly; this interrupts him."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "The alert text to send."}},
            "required": ["message"],
        },
    },
    {
        "name": "schedule_reminder",
        "description": (
            "Schedule a WhatsApp reminder for later — Rahm asking 'remind me to X at/in Y' or "
            "'text me about this tomorrow morning'. Compute due_at as an absolute ISO 8601 datetime "
            "(e.g. 2026-07-15T15:00:00-04:00) from the CURRENT DATE/TIME in your context plus what Rahm "
            "asked for — never guess at the current date, always derive it from that line."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "What to remind Rahm about."},
                "due_at": {"type": "string", "description": "Absolute ISO 8601 datetime to send the reminder."},
            },
            "required": ["message", "due_at"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List Rahm's pending (not-yet-sent) scheduled reminders.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a pending reminder by its id (from list_reminders).",
        "input_schema": {
            "type": "object",
            "properties": {"reminder_id": {"type": "string"}},
            "required": ["reminder_id"],
        },
    },
]

_ALWAYS_ON_NOTE = "\n\nYOUR REACH — Rahm speaks ONLY to you; he never sees the machinery. You have:\n"

_ALLIE_LIVE_NOTE = (
    "• ALLIE, your agentic Director of Operations (delegate_to_allie). She OWNS operational execution. For "
    "ANYTHING in the BUSINESS worlds (RMG or RMI) that needs live data or legwork — ClickUp projects/tasks, "
    "Notion knowledge, research, organizing facts, records work — DELEGATE to ALLIE. Give her only the "
    "business context she needs, never Rahm's personal details.\n"
)

_ALLIE_MEMORY_ONLY_NOTE = (
    "• ALLIE, your Director of Operations (delegate_to_allie), exists but currently has no live ClickUp/"
    "Notion access configured — she can only reason over what's already in business memory, not pull fresh "
    "data. Delegate to her for research/organizing over known facts, but don't expect her to look anything "
    "up live until that's configured.\n"
)

_CLICKUP_ONLY_NOTE = (
    "• Full CRUD over EVERY ClickUp space Rahm runs — his PERSONAL SYSTEMS (appointments, health, home, "
    "errands), the BUSINESS worlds (RMG, RMI), AND AMG (Apex Meridian Group). You are the overseer: you can "
    "create, update, delete tasks directly in any of these spaces. Read first for correct ids; make exactly "
    "the change asked.\n"
    "Rule: you can act directly anywhere, but for heavy business/AMG legwork (research, multi-step organizing) "
    "you may still DELEGATE to ALLIE to keep yourself free — your call. Personal tasks stay with you. Answer "
    "Rahm in your own natural spoken voice. NEVER mention tools, ALLIE, or ClickUp — to Rahm it is simply you, "
    "getting it done.\n"
)

_CLICKUP_AND_CALENDAR_NOTE = (
    "• Full CRUD over EVERY ClickUp space Rahm runs — his PERSONAL SYSTEMS (appointments, health, home, "
    "errands), the BUSINESS worlds (RMG, RMI), AND AMG (Apex Meridian Group). You are the overseer: create, "
    "update, delete tasks directly in any of these spaces. Read first for correct ids; make exactly the "
    "change asked.\n"
    "\n"
    "CALENDAR WORKFLOW — Rahm's calendar is rahmind.consulting@rmoorind.com, and ClickUp is already synced "
    "to it: ANY ClickUp task with a TIMED due date automatically appears on that calendar. So when Rahm "
    "wants something scheduled, decide the right home for it:\n"
    "  – Trackable work or anything with follow-up → make it a ClickUp TASK with a timed due date (personal "
    "→ you; business → delegate to ALLIE). It shows on the calendar via the integration, so do NOT also add "
    "a separate calendar event — that double-books.\n"
    "  – A pure one-off with nothing to track (mentorship meeting, publisher interview, a call) → put it "
    "DIRECTLY on his calendar with the calendar tools.\n"
    "  – When it's genuinely unclear, ASK him first: 'want that tracked as a ClickUp task, or just on your "
    "calendar?' Don't assume.\n"
    "\n"
    "Rule: you can act directly in any ClickUp space (personal, RMG/RMI, AMG) and own all calendar "
    "scheduling; for heavy business/AMG legwork you may still delegate to ALLIE to stay free — your call. "
    "Answer Rahm in your own natural spoken voice. NEVER mention tools, ALLIE, ClickUp/Notion, the calendar "
    "API, or that you delegated — to Rahm it is simply you, getting it done.\n"
)

_NOTION_NOTE = "You can also read Notion directly when needed.\n"

_CALENDAR_ONLY_NOTE = (
    "CALENDAR — Rahm's calendar is rahmind.consulting@rmoorind.com. Use the calendar tools to schedule "
    "one-off events directly. Answer Rahm in your own natural spoken voice.\n"
)

_YOUTUBE_NOTE = (
    "\n"
    "YOUTUBE — when Rahm pastes or mentions a YouTube URL (youtube.com/watch, youtu.be, or similar), "
    "IMMEDIATELY call youtube_ingest on it without asking. Do not wait for him to say 'save this' or "
    "'ingest this' — a YouTube link in chat is always an intent to capture it. After ingesting, tell him "
    "concisely what was saved (title + Drive links). If you want ALLIE to research or summarize the "
    "transcript, delegate to her after ingesting.\n"
)

_DRIVE_NOTE = (
    "\n"
    "DRIVE — use drive_search, drive_list_folder, drive_read_file to look things up in Rahm's Google Drive. "
    "Use drive_create_folder, drive_create_file, drive_update_file, drive_move_file, drive_delete_file to "
    "organize, save, or manage files directly. Write ops are audit-logged.\n"
)

_RMI_VAULT_NOTE_TMPL = (
    "\n"
    "RMI RECORDS BOOK — CLOSING WORKFLOW. Rahm periodically tells you a Records Book document is complete "
    "and filed to the RMI vault (Google Drive folder id {vault} — the store of FINAL copies of RMI "
    "governance/records-book documents). When he names a specific completed document, run this sequence "
    "yourself, then report back concisely (which page you closed, and whether it completed a Volume):\n"
    "  1. VERIFY it is really in the vault: drive_list_folder {vault} (or drive_search within it) and "
    "confirm a file for that document is present. If it isn't there, tell Rahm and STOP — never close a "
    "page whose final copy you cannot find.\n"
    "  2. LEGAL AGREEMENTS → mirror to AMG: if the document is a Volume III Legal Agreement (its code is "
    "RMI-LEG-###), copy its final file from the vault into the AMG legal-agreements Drive folder (id {amg}) "
    "with drive_copy_file — the vault copy stays put. Do this ONLY for RMI-LEG documents; no other type is "
    "mirrored to AMG.\n"
    "  3. CLOSE THE PAGE: in the 'RMI Records Book' ClickUp list (id 901714524235, under RMI HQ ADMIN → "
    "OPERATIONS), find the task whose name starts with that document's code (e.g. 'RMI-RES-002'), set its "
    "status to complete, and add a comment stamping the completion time from the current date/time in your "
    "context — e.g. 'Completed & filed to vault — <YYYY-MM-DD HH:MM ET>'.\n"
    "  4. CHECK THE VOLUME: read the whole list (clickup_list_tasks, include_closed true) and decide whether "
    "EVERY document in that document's Volume is now complete. Volume mapping: every task in the RMI Records "
    "Book list is Volume I (Corporate Records Book); RMI-GOV-001 is its own separate top line; Volumes II–V "
    "have no page-tasks yet, so ignore them until they do.\n"
    "  5. CLOSE THE AMG BOX only if the whole Volume is complete: read the description of the AMG 'Governance "
    "Agreements for RMI' task (id 86e22c5ef), change that Volume's markdown checkbox from '- [ ]' to '- [x]' "
    "(leave every other line exactly as-is), and write the full description back with clickup_update_task. "
    "Never tick a Volume box while any page in it is still open.\n"
)

_GITHUB_NOTE = (
    "\n"
    "GITHUB — you are allen-piaar-control-bot, with your own identity across every repo in the "
    "RMoor-Industries-Ltd-Co org. Use github_list_issues/github_get_issue/github_list_pull_requests/"
    "github_get_pull_request/github_read_file to check on an initiative's status (see "
    "rmg-piaar-system/docs/INITIATIVES.md for the registry of what's active where). Use github_create_issue "
    "or github_comment_issue to flag something for Claude Code to pick up next session — that's the handoff: "
    "you open or comment on an issue in the relevant repo, Claude Code reads it there. You can update file "
    "contents ONLY in rmg-piaar-system (github_update_file) — never on a code repo; you read code everywhere "
    "but only Claude Code writes it. Write ops are audit-logged.\n"
)

_REMINDER_NOTE = (
    "\n"
    "ALERTS & REMINDERS — send_alert pushes a WhatsApp message to Rahm's phone immediately (use sparingly, "
    "only for something worth interrupting him for). schedule_reminder sends one later — compute due_at from "
    "the CURRENT DATE/TIME given in your context, never guess it. list_reminders/cancel_reminder manage what's "
    "pending. This is DIFFERENT from the submit_form_personal_reminder form below, which just files a note in "
    "memory — use these tools instead whenever Rahm actually wants to be notified/texted, not just reminded "
    "the next time he asks you.\n"
)

_FORMS_NOTE = (
    "\n"
    "VIRTUAL FORMS — for structured personal/project/business requests (schedule an appointment, open a "
    "PIAAR initiative, log a business task, save a reminder, ...), use your submit_form_* tools instead of "
    "freelancing the details. Call list_virtual_forms if you're unsure what's available — check it before "
    "assuming a form doesn't exist for something Rahm asked for. If a submit_form_* tool is missing a "
    "required field from what Rahm told you, ASK him for it — never guess, invent, or leave it blank. If "
    "none of the existing forms fit a recurring type of request, you may propose defining a new one with "
    "define_virtual_form — but CONFIRM with Rahm first; only create it once he agrees it's worth having, "
    "never as a silent background action."
)


def _build_delegation_note(
    *, clickup_ready: bool, notion_ready: bool, calendar_ready: bool,
    youtube_ready: bool, gdrive_ready: bool, github_ready: bool, reminders_ready: bool = False,
    forms_ready: bool = True, rmi_vault_ready: bool = False,
    vault_folder_id: str = "", amg_legal_folder_id: str = "",
) -> str:
    """Every section here describes a real, currently-attached tool — nothing is claimed
    that isn't actually in this turn's tool list. A prior version described every
    capability unconditionally regardless of whether the underlying integration was
    ready, so a misconfigured/unready integration read to ALLEN as "I have this tool"
    right up until he tried to call it and found it wasn't there."""
    note = _ALWAYS_ON_NOTE
    note += _ALLIE_LIVE_NOTE if (clickup_ready or notion_ready) else _ALLIE_MEMORY_ONLY_NOTE
    if clickup_ready and calendar_ready:
        note += _CLICKUP_AND_CALENDAR_NOTE
    elif clickup_ready:
        note += _CLICKUP_ONLY_NOTE
    elif calendar_ready:
        note += _CALENDAR_ONLY_NOTE
    if notion_ready:
        note += _NOTION_NOTE
    if youtube_ready:
        note += _YOUTUBE_NOTE
    if gdrive_ready:
        note += _DRIVE_NOTE
    if rmi_vault_ready:
        note += _RMI_VAULT_NOTE_TMPL.format(vault=vault_folder_id, amg=amg_legal_folder_id)
    if github_ready:
        note += _GITHUB_NOTE
    if reminders_ready:
        note += _REMINDER_NOTE
    if forms_ready:
        note += _FORMS_NOTE
    return note


def respond_agentic(
    message: str,
    history: Optional[list[dict]],
    context: Optional[str],
    namespace: str,
    max_tokens: int = 900,
    model: Optional[str] = None,
    tool_scope: Optional[set[str]] = None,
) -> str:
    from . import (
        tools_calendar,
        tools_clickup,
        tools_gdrive,
        tools_github,
        tools_notion,
        tools_web,
        tools_youtube,
    )
    from .config import settings

    # tool_scope=None → full interactive tool set (unchanged). A scoped call (e.g. the
    # scheduled morning brief) attaches only the named categories, so a background job
    # doesn't pay to send the full GitHub/Drive/YouTube/forms schemas it never uses. The
    # delegation note is built from the SAME effective flags, preserving the invariant that
    # it only describes tools actually attached this turn.
    full = tool_scope is None

    def want(cat: str) -> bool:
        return full or cat in tool_scope

    calendar_on = tools_calendar.ready() and want("calendar")
    youtube_on = tools_youtube.ready() and want("youtube")
    gdrive_on = tools_gdrive.ready() and want("gdrive")
    clickup_on = settings.clickup_ready and want("clickup")
    notion_on = settings.notion_ready and want("notion")
    github_on = settings.github_ready and want("github")
    reminders_on = bool(settings.whatsapp_ready and settings.database_url) and want("reminders")
    web_on = want("web")
    forms_on = want("forms")

    tools = list(ALLEN_TOOLS)
    if reminders_on:
        tools += REMINDER_TOOLS  # push alerts + scheduled WhatsApp reminders
    if clickup_on:
        tools += tools_clickup.TOOLS  # read tools always; writes only on full (interactive) calls
        if full:
            tools += tools_clickup.WRITE_TOOLS  # full CRUD across all ClickUp spaces (personal + RMG/RMI + AMG)
    if notion_on:
        tools += tools_notion.TOOLS
    if calendar_on:
        tools += tools_calendar.TOOLS  # ALLEN manages Rahm's personal calendar
    if web_on:
        tools += tools_web.TOOLS  # web fetch (full interactive set)
    if youtube_on:
        tools += tools_youtube.TOOLS  # YouTube ingest → Drive
    if gdrive_on:
        tools += tools_gdrive.TOOLS  # Drive read + CRUD (TOOLS already includes WRITE_TOOLS)
    if github_on:
        tools += tools_github.TOOLS + tools_github.WRITE_TOOLS  # allen-piaar-control-bot — PIAAR org visibility

    if forms_on:
        forms.ensure_seed_forms(namespace)
        tools += forms.build_tool_schemas(namespace) + forms.META_TOOLS

    delegation_note = _build_delegation_note(
        clickup_ready=clickup_on, notion_ready=notion_on,
        calendar_ready=calendar_on, youtube_ready=youtube_on,
        gdrive_ready=gdrive_on, github_ready=github_on,
        reminders_ready=reminders_on, forms_ready=forms_on,
        rmi_vault_ready=(clickup_on and gdrive_on and bool(settings.rmi_vault_folder_id)),
        vault_folder_id=settings.rmi_vault_folder_id,
        amg_legal_folder_id=settings.amg_legal_agreements_folder_id,
    )
    system = chat.build_system(None, None, context) + delegation_note
    messages = [{"role": "user", "content": chat.build_user(message, history)}]

    def runner(name: str, inp: dict) -> str:
        inp = inp or {}
        if name == "delegate_to_allie":
            task = inp.get("task", "")
            res = allie.run(task, namespace)
            db.add_audit(namespace, "allen", "delegate", task, res)
            return res
        if name == "review_activity":
            return _format_audit(db.list_audit(namespace, inp.get("limit", 20)))
        if name == "get_agent_rollup":
            return _format_agent_rollup(db.list_agent_reports())
        if name == "send_alert":
            return _send_alert(namespace, inp.get("message", ""))
        if name == "schedule_reminder":
            return _schedule_reminder(namespace, inp.get("message", ""), inp.get("due_at", ""))
        if name == "list_reminders":
            return _format_reminders(db.list_upcoming_reminders(namespace))
        if name == "cancel_reminder":
            ok = db.cancel_reminder(namespace, inp.get("reminder_id", ""))
            return "Cancelled." if ok else "No pending reminder with that id."
        if name.startswith("clickup_"):
            res = tools_clickup.handle(name, inp, scope="all")  # ALLEN direct = full reach (personal + RMG/RMI + AMG)
            if name in tools_clickup.WRITE_NAMES:
                db.add_audit(namespace, "allen", name, json.dumps(inp), res)
            return res
        if name.startswith("notion_"):
            return tools_notion.handle(name, inp)  # ALLEN sees all Notion (overseer)
        if name.startswith("calendar_"):
            res = tools_calendar.handle(name, inp)
            if name in tools_calendar.WRITE_NAMES:
                db.add_audit(namespace, "allen", name, json.dumps(inp), res)
            return res
        if name.startswith("web_"):
            return tools_web.run_tool(name, inp)
        if name.startswith("youtube_"):
            return tools_youtube.handle(name, inp)
        if name.startswith("drive_"):
            res = tools_gdrive.handle(name, inp)
            if name in tools_gdrive.WRITE_NAMES:
                db.add_audit(namespace, "allen", name, json.dumps(inp), res)
            return res
        if name.startswith("github_"):
            res = tools_github.handle(name, inp)
            if name in tools_github.WRITE_NAMES:
                db.add_audit(namespace, "allen", name, json.dumps(inp), res)
            return res
        if name == "list_virtual_forms":
            return forms.list_forms_summary(namespace)
        if name == "define_virtual_form":
            res = forms.define_form(namespace, inp)
            db.add_audit(namespace, "allen", name, json.dumps(inp), res)
            return res
        if name.startswith("submit_form_"):
            res = forms.dispatch_submit(namespace, name, inp)
            db.add_audit(namespace, "allen", name, json.dumps(inp), res)
            return res
        return f"(unknown tool: {name})"

    llm = get_llm()
    if model and hasattr(llm, "model") and model != llm.model:
        # Swap model for this single call without mutating the shared provider.
        old = llm.model
        llm.model = model
        try:
            return llm.run_agent(
                system, messages, tools, runner, max_rounds=6, max_tokens=max_tokens,
                namespace=namespace, feature="allen_agent",
            )
        finally:
            llm.model = old
    return llm.run_agent(
        system, messages, tools, runner, max_rounds=6, max_tokens=max_tokens,
        namespace=namespace, feature="allen_agent",
    )
