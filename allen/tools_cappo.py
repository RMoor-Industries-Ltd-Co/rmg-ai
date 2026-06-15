"""Cappo delegation — the third tier. ALLIE hands an AMG (Apex Meridian Group) task DOWN to
Cappo, the AMG operations AI who works under her, via a keyed server-to-server call. Cappo
executes in AMG's own systems (ClickUp etc.) and returns a summary. Chain: ALLEN → ALLIE → Cappo."""

import requests

from .config import settings

TOOLS = [
    {
        "name": "delegate_to_cappo",
        "description": (
            "Delegate an AMG (Apex Meridian Group) operations task to Cappo — the AMG AI who works under "
            "you and executes in AMG's own systems (ClickUp, etc.). Use this ONLY for AMG work: managing "
            "AMG tasks, AMG operations, AMG research. Cappo returns what he found and did. Do NOT send RMG, "
            "RMI, or Rahm's personal work to Cappo — that stays with you."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "A clear AMG task for Cappo, with the AMG context he needs to execute it.",
                }
            },
            "required": ["task"],
        },
    }
]


def ready() -> bool:
    return bool(settings.cappo_agent_url and settings.cappo_agent_key)


def handle(task: str) -> str:
    if not ready():
        return "Cappo isn't connected yet."
    try:
        r = requests.post(
            settings.cappo_agent_url,
            headers={"x-agent-key": settings.cappo_agent_key, "Content-Type": "application/json"},
            json={"task": task},
            timeout=120,
        )
        if r.status_code == 401:
            return "Cappo rejected the call (auth key mismatch)."
        r.raise_for_status()
        return r.json().get("reply", "(Cappo returned nothing)")
    except Exception as e:
        return f"Cappo call failed: {e}"
