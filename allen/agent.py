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
    "• Full CRUD over Rahm's PERSONAL SYSTEMS ClickUp (appointments, health, home, errands) — create, "
    "update, delete his personal tasks directly. Read first for correct ids; make exactly the change asked. "
    "This personal layer is yours, not ALLIE's.\n"
    "Rule: business operational legwork → delegate to ALLIE; personal tasks → you. Answer Rahm in your own "
    "natural spoken voice. NEVER mention tools, ALLIE, or ClickUp — to Rahm it is simply you, getting it done.\n"
)

_CLICKUP_AND_CALENDAR_NOTE = (
    "• Full CRUD over Rahm's PERSONAL SYSTEMS ClickUp (appointments, health, home, errands) — create, "
    "update, delete his personal tasks directly. Read first for correct ids; make exactly the change asked. "
    "This personal layer is yours, not ALLIE's.\n"
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
    "Rule: business operational legwork → delegate to ALLIE; personal tasks + all calendar scheduling → you. "
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
    youtube_ready: bool, gdrive_ready: bool, github_ready: bool,
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
    if github_ready:
        note += _GITHUB_NOTE
    note += _FORMS_NOTE
    return note


def respond_agentic(
    message: str,
    history: Optional[list[dict]],
    context: Optional[str],
    namespace: str,
    max_tokens: int = 900,
    model: Optional[str] = None,
) -> str:
    from . import tools_calendar, tools_clickup, tools_gdrive, tools_github, tools_notion, tools_web, tools_youtube
    from .config import settings

    calendar_ready = tools_calendar.ready()
    youtube_ready = tools_youtube.ready()
    gdrive_ready = tools_gdrive.ready()

    tools = list(ALLEN_TOOLS)
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS + tools_clickup.WRITE_TOOLS  # full CRUD on Rahm's PERSONAL spaces
    if settings.notion_ready:
        tools += tools_notion.TOOLS
    if calendar_ready:
        tools += tools_calendar.TOOLS  # ALLEN manages Rahm's personal calendar
    tools += tools_web.TOOLS  # web fetch always available
    if youtube_ready:
        tools += tools_youtube.TOOLS  # YouTube ingest → Drive
    if gdrive_ready:
        tools += tools_gdrive.TOOLS  # Drive read + CRUD (TOOLS already includes WRITE_TOOLS)
    if settings.github_ready:
        tools += tools_github.TOOLS + tools_github.WRITE_TOOLS  # allen-piaar-control-bot — PIAAR org visibility

    forms.ensure_seed_forms(namespace)
    tools += forms.build_tool_schemas(namespace) + forms.META_TOOLS

    delegation_note = _build_delegation_note(
        clickup_ready=settings.clickup_ready, notion_ready=settings.notion_ready,
        calendar_ready=calendar_ready, youtube_ready=youtube_ready,
        gdrive_ready=gdrive_ready, github_ready=settings.github_ready,
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
        if name.startswith("clickup_"):
            res = tools_clickup.handle(name, inp, scope="personal")  # ALLEN direct = personal systems only
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
