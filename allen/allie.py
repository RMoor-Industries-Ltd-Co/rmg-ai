"""ALLIE — Adaptive Language and Learning Intelligence Expert. Rahm's Director of
Operations / Project Manager / Intelligence Engine, operating UNDER ALLEN in the chain
Rahm -> ALLEN -> ALLIE. She handles operational research, project management, records,
data, and execution across the BUSINESS worlds (RMG + RMI). By design she is grounded in
ALLEN's business memory only — never Rahm's personal/sensitive context (the gatekeeper rule)."""

from typing import Optional

from . import memory
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
    from ClickUp (projects) and Notion (knowledge base) before answering, scoped to the business
    spaces, then returns organized findings for ALLEN to synthesize."""
    from . import tools_clickup, tools_notion
    from .config import settings

    context = memory.allie_context(namespace)
    tools: list = []
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS
    if settings.notion_ready:
        tools += tools_notion.TOOLS
    if not tools:  # no live sources configured — reason over memory
        return respond(task, history=[], context=context, max_tokens=1200)

    system = _build_system(context) + (
        "\n\nLIVE TOOLS — you can read Rahm's real operational systems before answering, and you should:\n"
        "• ClickUp (the project/task framework): clickup_hierarchy to find lists, then clickup_list_tasks "
        "and clickup_get_task.\n"
        "• Notion (the knowledge base / 'bank of wisdom'): notion_search, then notion_get_page.\n"
        "Pull REAL data — never guess names, tasks, dates, or facts you can look up. You are scoped to the "
        "BUSINESS spaces (RMG, RMI); personal/AMG are out of bounds. When finished, hand ALLEN a tight, "
        "organized findings summary (with the concrete facts) that he can relay to Rahm."
    )

    def runner(name: str, inp: dict) -> str:
        if name.startswith("clickup_"):
            return tools_clickup.handle(name, inp, business_only=True)
        if name.startswith("notion_"):
            return tools_notion.handle(name, inp, business_only=True)
        return f"(unknown tool: {name})"

    messages = [{"role": "user", "content": f"Task from ALLEN: {task}"}]
    return get_llm().run_agent(system, messages, tools, runner, max_rounds=7, max_tokens=1300)
