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
    "\n\nYOU HAVE ALLIE — your Director of Operations, an agentic engine working under you across RMG and "
    "RMI. Rahm speaks ONLY to you and never sees ALLIE. When his request needs operational legwork — "
    "research, looking things up, gathering/organizing facts or data, project tracking, or records work — "
    "DELEGATE it to ALLIE with the delegate_to_allie tool, then weave her findings into your own spoken "
    "answer. Pass her only the business context she needs, never Rahm's personal/private details. For "
    "quick conversational or personal replies, just answer yourself. NEVER mention the tool, ALLIE's "
    "mechanics, or that you delegated — to Rahm it is simply you, getting it done."
)


def respond_agentic(
    message: str,
    history: Optional[list[dict]],
    context: Optional[str],
    namespace: str,
    max_tokens: int = 900,
) -> str:
    system = chat.build_system(None, None, context) + _DELEGATION_NOTE
    messages = [{"role": "user", "content": chat.build_user(message, history)}]

    def runner(name: str, inp: dict) -> str:
        if name == "delegate_to_allie":
            return allie.run((inp or {}).get("task", ""), namespace)
        return f"(unknown tool: {name})"

    return get_llm().run_agent(system, messages, ALLEN_TOOLS, runner, max_rounds=5, max_tokens=max_tokens)
