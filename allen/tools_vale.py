"""Vale — HVN Havenry's public-facing concierge (rmg-piaar-system contract:
governance/brands/ai-universe/VALE.md). ALLIE hands Vale an HVN/showroom question DOWN
via a keyed server-to-server call, or pulls her cached HVN<->AMG activity report.
Chain: ALLEN -> ALLIE -> Vale.

Vale's PUBLIC surface (hvnhavenry-com's POST /api/vale) is deliberately restricted to a
fixed set of suggested prompts, no free text -- this M2M surface is separate, keyed, and
only reachable by trusted internal agents, so a free-text task is fine here. Vale reasons
only over aggregate showroom interaction counts + the static product catalog, never a
specific visitor's conversation (no visitor identity is ever collected in the first
place)."""

import requests

from .config import settings

TOOLS = [
    {
        "name": "delegate_to_vale",
        "description": (
            "Delegate an HVN Havenry showroom/product question to Vale — the HVN concierge AI who "
            "works under you. She reasons only over aggregate showroom interaction data and the "
            "static product catalog — never a specific visitor's conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "A clear HVN Havenry showroom/product question for Vale.",
                }
            },
            "required": ["task"],
        },
    },
]

# Separate from TOOLS for the same reason as tools_cappo.py's REPORT_TOOLS split: this
# needs its own report URL configured, independent of the live-delegation URL.
REPORT_TOOLS = [
    {
        "name": "vale_get_report",
        "description": (
            "Pull Vale's latest cached HVN showroom activity report — already generated on a "
            "schedule, instant to read. Use this for 'what's going on at HVN' instead of "
            "delegate_to_vale, which does live work."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def ready() -> bool:
    return bool(settings.vale_agent_url and settings.vale_agent_key)


def handle(task: str) -> str:
    if not ready():
        return "Vale isn't connected yet."
    try:
        r = requests.post(
            settings.vale_agent_url,
            headers={"x-agent-key": settings.vale_agent_key, "Content-Type": "application/json"},
            json={"task": task},
            timeout=120,
        )
        if r.status_code == 401:
            return "Vale rejected the call (auth key mismatch)."
        r.raise_for_status()
        return r.json().get("reply", "(Vale returned nothing)")
    except Exception as e:
        return f"Vale call failed: {e}"


def get_report() -> str:
    if not settings.vale_report_ready:
        return "Vale's cached report isn't connected yet."
    try:
        r = requests.get(
            settings.vale_report_url,
            headers={"x-agent-key": settings.vale_agent_key},
            timeout=30,
        )
        if r.status_code == 401:
            return "Vale rejected the call (auth key mismatch)."
        r.raise_for_status()
        d = r.json()
        return d.get("reportText") or d.get("report_text") or "(no report cached yet)"
    except Exception as e:
        return f"Vale report pull failed: {e}"
