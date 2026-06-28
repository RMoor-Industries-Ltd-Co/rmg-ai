"""ALLEN's agentic layer. Rahm speaks only to ALLEN; ALLEN decides how to answer — and when a
request needs operational legwork (research, lookups, project/records/data across RMG or RMI) he
DELEGATES to ALLIE behind the scenes, then synthesizes her findings into his own spoken reply.

This wraps chat.build_system/build_user (ALLEN's exact persona) in a tool-use loop whose only tool,
for now, is delegate_to_allie. As ALLIE gains ClickUp/Notion tools, ALLEN's reach grows for free."""

import json
from typing import Optional

from . import allie, chat, db
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
]

_DELEGATION_NOTE = (
    "\n\nYOUR REACH — Rahm speaks ONLY to you; he never sees the machinery. You have:\n"
    "• ALLIE, your agentic Director of Operations (delegate_to_allie). She OWNS operational execution. For "
    "ANYTHING in the BUSINESS worlds (RMG or RMI) that needs live data or legwork — ClickUp projects/tasks, "
    "Notion knowledge, research, organizing facts, records work — DELEGATE to ALLIE. Email triage, inbox "
    "monitoring, calendar cleanup, and Drive research can also be delegated to her.\n"
    "• Full CRUD over Rahm's PERSONAL SYSTEMS ClickUp (appointments, health, home, errands) — create, "
    "update, delete his personal tasks directly. Read first for correct ids; make exactly the change asked. "
    "This personal layer is yours, not ALLIE's. You can also read Notion directly when needed.\n"
    "\n"
    "GOOGLE ACCOUNTS — Rahm has 7 Google accounts. The default is rahmind.consulting@rmoorind.com. "
    "All calendar, Gmail, and Drive tools accept an optional `account` param to target any account:\n"
    "  rmoorind@rmoorind.com | rahmind.consulting@rmoorind.com (default) | rmoorindustries@gmail.com\n"
    "  amg@apex-meridian-group.com | rahm@rmasters.group | kingrahjah@gmail.com | rmooreking@gmail.com\n"
    "Use gmail_list_accounts to check which accounts are currently connected.\n"
    "\n"
    "CALENDAR WORKFLOW — rahmind.consulting@rmoorind.com is Rahm's primary calendar. ClickUp is synced "
    "to it: ANY ClickUp task with a TIMED due date automatically appears on that calendar. Decide:\n"
    "  – Trackable work with follow-up → ClickUp TASK with timed due date (personal → you; business → "
    "ALLIE). It shows on calendar automatically; do NOT also add a separate calendar event — that double-books.\n"
    "  – Pure one-off with nothing to track → put it DIRECTLY on calendar with the calendar tools.\n"
    "  – When unclear, ASK: 'want that tracked as a task, or just on your calendar?'\n"
    "\n"
    "GMAIL — you can search, read, send, and reply across all of Rahm's inboxes. For inbox triage, "
    "archiving, and background monitoring, delegate to ALLIE — that is her domain. For personal replies "
    "or emails Rahm asks you to send directly, handle those yourself.\n"
    "\n"
    "DRIVE — you can search and read files across all accounts. For deep Drive research or organizing, "
    "delegate to ALLIE.\n"
    "\n"
    "Rule: business operational legwork → delegate to ALLIE; personal tasks + calendar scheduling + "
    "direct emails → you. Answer Rahm in your own natural spoken voice. NEVER mention tools, ALLIE, "
    "ClickUp/Notion, the calendar API, or that you delegated — to Rahm it is simply you, getting it done.\n"
    "\n"
    "YOUTUBE — when Rahm pastes or mentions a YouTube URL (youtube.com/watch, youtu.be, or similar), "
    "IMMEDIATELY call youtube_ingest on it without asking. Do not wait for him to say 'save this' or "
    "'ingest this' — a YouTube link in chat is always an intent to capture it. After ingesting, tell him "
    "concisely what was saved (title + Drive links). If you want ALLIE to research or summarize the "
    "transcript, delegate to her after ingesting."
)


def respond_agentic(
    message: str,
    history: Optional[list[dict]],
    context: Optional[str],
    namespace: str,
    max_tokens: int = 900,
) -> str:
    from . import tools_calendar, tools_clickup, tools_gdrive, tools_gmail, tools_notion, tools_web, tools_youtube
    from .config import settings
    from . import google_auth

    tools = list(ALLEN_TOOLS)
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS + tools_clickup.WRITE_TOOLS  # full CRUD on Rahm's PERSONAL spaces
    if settings.notion_ready:
        tools += tools_notion.TOOLS
    if tools_calendar.ready():
        tools += tools_calendar.TOOLS  # ALLEN manages Rahm's personal calendar
    if google_auth.oauth_ready():
        tools += tools_gmail.TOOLS  # Gmail across all accounts
        tools += tools_gdrive.TOOLS  # Drive search/read across all accounts
    tools += tools_web.TOOLS  # web fetch always available
    if tools_youtube.ready():
        tools += tools_youtube.TOOLS  # YouTube ingest → Drive

    system = chat.build_system(None, None, context) + _DELEGATION_NOTE
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
        if name.startswith("gmail_"):
            res = tools_gmail.handle(name, inp)
            if name in tools_gmail.WRITE_NAMES:
                db.add_audit(namespace, "allen", name, json.dumps(inp), res[:200])
            return res
        if name.startswith("drive_"):
            res = tools_gdrive.handle(name, inp)
            if name in tools_gdrive.WRITE_NAMES:
                db.add_audit(namespace, "allen", name, json.dumps(inp), res)
            return res
        if name.startswith("web_"):
            return tools_web.run_tool(name, inp)
        if name.startswith("youtube_"):
            return tools_youtube.handle(name, inp)
        return f"(unknown tool: {name})"

    return get_llm().run_agent(system, messages, tools, runner, max_rounds=6, max_tokens=max_tokens)
