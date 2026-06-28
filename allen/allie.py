"""ALLIE — Adaptive Language and Learning Intelligence Expert. Rahm's Director of
Operations / Project Manager / Intelligence Engine, operating UNDER ALLEN in the chain
Rahm -> ALLEN -> ALLIE. She handles operational research, project management, records,
data, and execution across the BUSINESS worlds (RMG + RMI). By design she is grounded in
ALLEN's business memory only — never Rahm's personal/sensitive context (the gatekeeper rule)."""

import json
from typing import Optional

from . import db, memory
from .llm import get_llm

_SYSTEM = (
    "You are ALLIE — \"Adaptive Language and Learning Intelligence Expert\" — Rahm's Director of "
    "Operations, Project Manager, and Intelligence Engine. You operate UNDER ALLEN (Rahm's Chief of "
    "Staff and Product Owner) in the chain of command: Rahm -> ALLEN -> ALLIE.\n"
    "YOUR DOMAIN: operational research, investigation, project management, records and governance "
    "support, facts, data, statistics, communications, and organized execution across Rahm's BUSINESS "
    "worlds — RMG (the creative brand house) and RMI (RMoor Industries). You protect MOVEMENT: keep the "
    "work organized, accurate, and progressing.\n"
    "YOUR BOUNDARY: you are NOT Rahm's personal assistant. You do NOT govern his private/personal life, "
    "health, family, executive priorities, or final decisions — those belong to ALLEN. You only have, "
    "and only need, the business context required for the task. If something is personal or an executive "
    "call, defer it to ALLEN rather than answering.\n"
    "HOW YOU WORK: precise, organized, research-backed. Use clear structure (headings, short lists, "
    "tables) — your output is operational and read on screen, not spoken aloud. Cite the facts you are "
    "using from what you know. Surface risks, gaps, and recommendations crisply so ALLEN can decide what "
    "reaches Rahm. If you are missing a fact, say exactly what you'd need — never invent business facts, "
    "names, numbers, or client details."
)


def _build_system(context: Optional[str]) -> str:
    system = _SYSTEM
    if context:
        system += (
            "\n\nWHAT YOU KNOW (ALLEN's business knowledge — RMG, RMI, brands, projects; treat as ground "
            "truth, and never invent beyond it):\n" + context[:9000]
        )
    return system


def respond(
    message: str,
    history: Optional[list[dict]] = None,
    context: Optional[str] = None,
    max_tokens: int = 900,
) -> str:
    convo = ""
    for m in (history or [])[-8:]:
        role = "ALLIE" if m.get("role") == "assistant" else "Rahm"
        convo += f"{role}: {m.get('content', '')}\n"
    user = (convo + f"Rahm: {message}\nALLIE:").strip()
    return get_llm().complete(system=_build_system(context), user=user, max_tokens=max_tokens)


def run(task: str, namespace: str) -> str:
    """Delegation entrypoint — ALLEN hands ALLIE a task. She works it AGENTICALLY: pulling live data
    from ClickUp, Notion, Gmail, Calendar, and Drive before answering, then returns organized findings
    for ALLEN to synthesize."""
    from . import google_auth, tools_calendar, tools_cappo, tools_clickup, tools_gdrive, tools_gmail, tools_notion, tools_youtube
    from .config import settings

    context = memory.allie_context(namespace)
    tools: list = []
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS + tools_clickup.WRITE_TOOLS
    if settings.notion_ready:
        tools += tools_notion.TOOLS
    if tools_cappo.ready():
        tools += tools_cappo.TOOLS
    if tools_youtube.ready():
        tools += tools_youtube.TOOLS
    if google_auth.oauth_ready():
        tools += tools_gmail.TOOLS       # ALLIE is the email workhorse
        tools += tools_gdrive.TOOLS      # Drive research across all accounts
        tools += tools_calendar.TOOLS    # Calendar monitoring and scheduling support
    if not tools:
        return respond(task, history=[], context=context, max_tokens=1200)

    system = _build_system(context) + (
        "\n\nLIVE TOOLS — you can READ and CHANGE Rahm's real operational systems. You have full autonomy "
        "to act in the BUSINESS spaces (RMG, RMI). Personal/AMG are out of bounds unless explicitly tasked.\n"
        "• ClickUp READ: clickup_hierarchy to find lists, then clickup_list_tasks and clickup_get_task.\n"
        "• ClickUp WRITE: clickup_create_task, clickup_update_task (status, due_date YYYY-MM-DD, priority, "
        "name, description), clickup_comment_task, clickup_create_list, clickup_create_folder, "
        "clickup_delete_task.\n"
        "• Notion READ: notion_search, then notion_get_page.\n"
        "• AMG: do NOT touch AMG directly — delegate via delegate_to_cappo.\n"
        "• YouTube INGEST: youtube_ingest(url) saves audio + transcript + optional video to Drive. "
        "include_video=true only when visuals are explicitly needed.\n"
        "• GMAIL (all accounts): gmail_search to find emails, gmail_read to read them, gmail_send to send, "
        "gmail_reply to reply, gmail_archive to clean up. All tools accept an optional `account` param — "
        "default is rahmind.consulting@rmoorind.com. Use gmail_list_accounts to check what's connected. "
        "You are the workhorse for inbox monitoring and triage. Archive aggressively when tasked with cleanup. "
        "For business emails, surface findings to ALLEN; do NOT send emails without explicit instruction.\n"
        "• GOOGLE DRIVE (all accounts): drive_search to find files, drive_list_folder to browse a folder, "
        "drive_read_file to read content (Docs, Sheets, Slides, plain text). All accept optional `account`.\n"
        "• GOOGLE CALENDAR (all accounts): calendar_list_events, calendar_create_event, "
        "calendar_update_event, calendar_delete_event. All accept optional `account`. "
        "Use for monitoring upcoming events and scheduling support. ALWAYS confirm with ALLEN before "
        "creating or deleting calendar events unless explicitly authorized.\n"
        "DISCIPLINE: read first, then write. Make exactly the changes the task calls for, nothing extra. "
        "Delete only when clearly asked. Return a tight summary of FINDINGS and CHANGES to ALLEN."
    )

    def runner(name: str, inp: dict) -> str:
        inp = inp or {}
        if name.startswith("clickup_"):
            res = tools_clickup.handle(name, inp, scope="business")
            if name in tools_clickup.WRITE_NAMES:
                db.add_audit(namespace, "allie", name, json.dumps(inp), res)
            return res
        if name.startswith("notion_"):
            return tools_notion.handle(name, inp, business_only=True)
        if name == "delegate_to_cappo":
            res = tools_cappo.handle(inp.get("task", ""))
            db.add_audit(namespace, "allie", "delegate_to_cappo", inp.get("task", ""), res)
            return res
        if name.startswith("youtube_"):
            res = tools_youtube.handle(name, inp)
            db.add_audit(namespace, "allie", name, inp.get("url", ""), res[:200])
            return res
        if name.startswith("gmail_"):
            res = tools_gmail.handle(name, inp)
            if name in tools_gmail.WRITE_NAMES:
                db.add_audit(namespace, "allie", name, json.dumps(inp), res[:200])
            return res
        if name.startswith("drive_"):
            res = tools_gdrive.handle(name, inp)
            if name in tools_gdrive.WRITE_NAMES:
                db.add_audit(namespace, "allie", name, json.dumps(inp), res)
            return res
        if name.startswith("calendar_"):
            res = tools_calendar.handle(name, inp)
            if name in tools_calendar.WRITE_NAMES:
                db.add_audit(namespace, "allie", name, json.dumps(inp), res)
            return res
        return f"(unknown tool: {name})"

    messages = [{"role": "user", "content": f"Task from ALLEN: {task}"}]
    return get_llm().run_agent(system, messages, tools, runner, max_rounds=7, max_tokens=1300)
