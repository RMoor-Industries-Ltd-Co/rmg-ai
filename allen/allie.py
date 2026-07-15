"""ALLIE — Adaptive Language and Learning Intelligence Expert. Rahm's Director of
Operations / Project Manager / Intelligence Engine, operating UNDER ALLEN in the chain
Rahm -> ALLEN -> ALLIE. She handles operational research, project management, records,
data, and execution across the BUSINESS worlds (RMG + RMI). By design she is grounded in
ALLEN's business memory only — never Rahm's personal/sensitive context (the gatekeeper rule)."""

import json
from typing import Optional

from . import db, memory
from .clock import now_line
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
    system = _SYSTEM + "\n\n" + now_line()
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
    namespace: str = "",
) -> str:
    convo = ""
    for m in (history or [])[-8:]:
        role = "ALLIE" if m.get("role") == "assistant" else "Rahm"
        convo += f"{role}: {m.get('content', '')}\n"
    user = (convo + f"Rahm: {message}\nALLIE:").strip()
    return get_llm().complete(
        system=_build_system(context), user=user, max_tokens=max_tokens,
        namespace=namespace, feature="allie_chat",
    )


def run(task: str, namespace: str) -> str:
    """Delegation entrypoint — ALLEN hands ALLIE a task. She works it AGENTICALLY: pulling live data
    from ClickUp (projects) and Notion (knowledge base) before answering, scoped to the business
    spaces, then returns organized findings for ALLEN to synthesize."""
    from . import tools_anpu, tools_cappo, tools_clickup, tools_constance, tools_gdrive, tools_notion, tools_thoth, tools_youtube
    from .config import settings

    context = memory.allie_context(namespace)
    tools: list = []
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS + tools_clickup.WRITE_TOOLS
    if settings.notion_ready:
        tools += tools_notion.TOOLS
    if tools_cappo.ready():
        tools += tools_cappo.TOOLS  # delegate AMG work down to Cappo
    if settings.cappo_report_ready:
        tools += tools_cappo.REPORT_TOOLS  # pull his cached report (separate URL from delegation)
    if tools_constance.ready():
        tools += tools_constance.TOOLS  # delegate to Constance (Connection Circle), or pull her cached report
    if tools_anpu.ready():
        tools += tools_anpu.TOOLS  # pull AXIS/Anpu's already-cached oversight reviews
    if tools_thoth.ready():
        tools += tools_thoth.TOOLS  # pull AXIS/Thoth's already-cached candidate board
    if tools_youtube.ready():
        tools += tools_youtube.TOOLS  # YouTube → Drive for research + b-roll
    if tools_gdrive.ready():
        tools += tools_gdrive.TOOLS  # Drive read + CRUD (TOOLS already includes WRITE_TOOLS)
    if not tools:  # no live sources configured — reason over memory
        return respond(task, history=[], context=context, max_tokens=1200, namespace=namespace)

    system = _build_system(context) + (
        "\n\nLIVE TOOLS — you can READ and CHANGE Rahm's real operational systems. You have full autonomy "
        "to act in the BUSINESS spaces (RMG, RMI); personal/AMG are out of bounds.\n"
        "• ClickUp READ: clickup_hierarchy to find lists, then clickup_list_tasks and clickup_get_task.\n"
        "• ClickUp WRITE: clickup_create_task, clickup_update_task (status, due_date YYYY-MM-DD, priority, "
        "name, description), clickup_comment_task, clickup_create_list, clickup_create_folder, "
        "clickup_delete_task.\n"
        "• Notion READ: notion_search, then notion_get_page.\n"
        "• AMG: you do NOT touch AMG directly. For any AMG (Apex Meridian Group) work, DELEGATE to Cappo via "
        "delegate_to_cappo — he is the AMG AI under you who executes in AMG's own systems. Use cappo_get_report "
        "instead when you just need his latest status (already cached, instant — don't delegate live work just "
        "to check on things). You manage and "
        "relay; Cappo does the AMG legwork.\n"
        "• CONNECTION CIRCLE: for anything about Connection Circle, DELEGATE to Constance via "
        "delegate_to_constance, or pull constance_get_report for her latest status. She only reasons over "
        "aggregate product metrics — never ask her about a specific user's private relationship data.\n"
        "• YouTube INGEST: youtube_ingest(url) downloads audio (MP3), transcript (plain text), and optionally "
        "video (MP4) from any YouTube URL and saves the files to Google Drive (rahm@rmasters.group). Use this "
        "when sourcing research material, b-roll references, or script inspiration from YouTube. Set "
        "include_video=true only when the visual content is explicitly needed. The tool returns Drive links "
        "you can pass back to ALLEN so Rahm can access or share them.\n"
        "• DRIVE READ: drive_search, drive_list_folder, drive_read_file — look up files, list folders, "
        "read text content. Use for research, verifying what exists, pulling source material.\n"
        "• DRIVE WRITE: drive_create_folder, drive_create_file, drive_update_file, drive_move_file, "
        "drive_delete_file (moves to Trash). Use for organizing, saving research outputs, or filing records.\n"
        "• AXIS status: anpu_get_reviews and thoth_get_status are read-only pulls of what AXIS's own agents "
        "(Anpu, Thoth) have already found — they run autonomously inside axis-tekhen, you don't trigger them, "
        "just read their latest output when a rollup or status question touches AXIS.\n"
        "DISCIPLINE: always read first to get the correct ids before you change anything — never write to an "
        "id you haven't verified. Make exactly the changes the task calls for, nothing extra. Delete only "
        "when clearly asked. When finished, hand ALLEN a tight summary of what you FOUND and what you CHANGED "
        "(the concrete facts + ids) so he can relay it to Rahm."
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
        if name == "cappo_get_report":
            return tools_cappo.get_report()
        if name == "delegate_to_constance":
            res = tools_constance.handle(inp.get("task", ""))
            db.add_audit(namespace, "allie", "delegate_to_constance", inp.get("task", ""), res)
            return res
        if name == "constance_get_report":
            return tools_constance.get_report()
        if name == "anpu_get_reviews":
            return tools_anpu.handle(name, inp)
        if name == "thoth_get_status":
            return tools_thoth.handle(name, inp)
        if name.startswith("youtube_"):
            res = tools_youtube.handle(name, inp)
            db.add_audit(namespace, "allie", name, inp.get("url", ""), res[:200])
            return res
        if name.startswith("drive_"):
            res = tools_gdrive.handle(name, inp)
            if name in tools_gdrive.WRITE_NAMES:
                db.add_audit(namespace, "allie", name, json.dumps(inp), res)
            return res
        return f"(unknown tool: {name})"

    messages = [{"role": "user", "content": f"Task from ALLEN: {task}"}]
    return get_llm().run_agent(
        system, messages, tools, runner, max_rounds=7, max_tokens=1300,
        namespace=namespace, feature="allie_agent",
    )
