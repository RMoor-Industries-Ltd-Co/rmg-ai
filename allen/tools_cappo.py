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
    },
    {
        "name": "cappo_get_report",
        "description": (
            "Pull Cappo's latest cached AMG executive status report — already generated on a schedule, "
            "instant to read. Use this for 'what's going on in AMG' instead of delegate_to_cappo, which "
            "does live work; this just reads what Cappo already prepared."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def ready() -> bool:
    return bool(settings.cappo_agent_url and settings.cappo_agent_key)


def handle(task: str) -> str:
    """delegate_to_cappo — live, synchronous task delegation. Kept as a plain (task) signature
    since this is the original, most-used call shape (allie.py calls it directly)."""
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


def get_report() -> str:
    """cappo_get_report — pull-only, reads Cappo's already-cached executive report. Distinct
    endpoint from delegate_to_cappo's live task endpoint; never triggers live work."""
    if not settings.cappo_report_ready:
        return "Cappo's cached report isn't connected yet."
    try:
        r = requests.get(
            settings.cappo_report_url,
            headers={"x-agent-key": settings.cappo_agent_key},
            timeout=30,
        )
        if r.status_code == 401:
            return "Cappo rejected the call (auth key mismatch)."
        r.raise_for_status()
        d = r.json()
        return d.get("report_text") or d.get("report") or "(no report cached yet)"
    except Exception as e:
        return f"Cappo report pull failed: {e}"
