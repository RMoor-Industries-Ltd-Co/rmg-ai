"""ALLEN's agentic layer. Rahm speaks only to ALLEN; ALLEN decides how to answer — and when a
request needs operational legwork (research, lookups, project/records/data across RMG or RMI) he
DELEGATES to ALLIE behind the scenes, then synthesizes her findings into his own spoken reply.

This wraps chat.build_system/build_user (ALLEN's exact persona) in a tool-use loop whose only tool,
for now, is delegate_to_allie. As ALLIE gains ClickUp/Notion tools, ALLEN's reach grows for free."""

from typing import Optional

from . import allie, chat
from .llm import get_llm

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
    }
]

_DELEGATION_NOTE = (
    "\n\nYOUR REACH — Rahm speaks ONLY to you; he never sees the machinery. You have:\n"
    "• ALLIE, your agentic Director of Operations (delegate_to_allie). She OWNS operational execution. For "
    "ANYTHING in the BUSINESS worlds (RMG or RMI) that needs live data or legwork — ClickUp projects/tasks, "
    "Notion knowledge, research, organizing facts, records work — DELEGATE to ALLIE. Give her only the "
    "business context she needs, never Rahm's personal details.\n"
    "• Full CRUD over Rahm's PERSONAL side — his PERSONAL SYSTEMS ClickUp (appointments, health, home, "
    "errands) and his calendar. You can create, update, reschedule, and delete his personal tasks and "
    "events directly. Read first to get correct ids; make exactly the change asked. This personal layer is "
    "yours, not ALLIE's. You can also read Notion directly when needed.\n"
    "Rule: business/operational → delegate to ALLIE; personal (tasks + calendar) → handle yourself. Either "
    "way, answer Rahm in your own natural spoken voice. NEVER mention tools, ALLIE, ClickUp/Notion, the "
    "calendar API, or that you delegated — to Rahm it is simply you, getting it done."
)


def respond_agentic(
    message: str,
    history: Optional[list[dict]],
    context: Optional[str],
    namespace: str,
    max_tokens: int = 900,
) -> str:
    from . import tools_calendar, tools_clickup, tools_notion
    from .config import settings

    tools = list(ALLEN_TOOLS)
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS + tools_clickup.WRITE_TOOLS  # full CRUD on Rahm's PERSONAL spaces
    if settings.notion_ready:
        tools += tools_notion.TOOLS
    if tools_calendar.ready():
        tools += tools_calendar.TOOLS  # ALLEN manages Rahm's personal calendar

    system = chat.build_system(None, None, context) + _DELEGATION_NOTE
    messages = [{"role": "user", "content": chat.build_user(message, history)}]

    def runner(name: str, inp: dict) -> str:
        if name == "delegate_to_allie":
            return allie.run((inp or {}).get("task", ""), namespace)
        if name.startswith("clickup_"):
            return tools_clickup.handle(name, inp, scope="personal")  # ALLEN direct = personal systems only
        if name.startswith("notion_"):
            return tools_notion.handle(name, inp)  # ALLEN sees all Notion (overseer)
        if name.startswith("calendar_"):
            return tools_calendar.handle(name, inp)
        return f"(unknown tool: {name})"

    return get_llm().run_agent(system, messages, tools, runner, max_rounds=6, max_tokens=max_tokens)
