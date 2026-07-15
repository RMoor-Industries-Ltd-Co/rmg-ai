"""Constance — Connection Circle's project-owner agent (rmg-piaar-system contract:
governance/brands/ai-universe/CONSTANCE.md). ALLIE hands Constance a Connection Circle
task DOWN via a keyed server-to-server call, or pulls her cached executive status.
Chain: ALLEN → ALLIE → Constance.

PRIVACY RULE — Constance's own implementation is scoped to aggregate, non-PII product
metrics only (see connection-circle/CLAUDE.md). Never send her a request for an
individual user's private relationship/reflection data; she has no access to it and the
request would just fail."""

import requests

from .config import settings

TOOLS = [
    {
        "name": "delegate_to_constance",
        "description": (
            "Delegate a Connection Circle product/operational question to Constance — the "
            "Connection Circle AI who works under you. She reasons only over aggregate product "
            "metrics (user counts, engagement, plan tiers) — never ask her about an individual "
            "user's private relationship data, she can't see it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "A clear Connection Circle product/operational question for Constance.",
                }
            },
            "required": ["task"],
        },
    },
]

# Separate from TOOLS: constance_get_report needs its own CONSTANCE_REPORT_URL configured
# (independent of delegate_to_constance's CONSTANCE_AGENT_URL). Gate this on
# settings.constance_report_ready specifically — not just tools_constance.ready() — so it's
# never advertised (and silently no-op'd) before it's wired up. Mirrors tools_cappo.py/
# tools_vale.py's TOOLS/REPORT_TOOLS split.
REPORT_TOOLS = [
    {
        "name": "constance_get_report",
        "description": (
            "Pull Constance's latest cached Connection Circle executive status report — already "
            "generated on a schedule, instant to read. Use this for 'what's going on in Connection "
            "Circle' instead of delegate_to_constance, which does live work."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def ready() -> bool:
    return settings.constance_ready


def handle(task: str) -> str:
    if not ready():
        return "Constance isn't connected yet."
    try:
        r = requests.post(
            settings.constance_agent_url,
            headers={"x-agent-key": settings.constance_agent_key, "Content-Type": "application/json"},
            json={"task": task},
            timeout=120,
        )
        if r.status_code == 401:
            return "Constance rejected the call (auth key mismatch)."
        r.raise_for_status()
        return r.json().get("reply", "(Constance returned nothing)")
    except Exception as e:
        return f"Constance call failed: {e}"


def get_report() -> str:
    if not settings.constance_report_ready:
        return "Constance's cached report isn't connected yet."
    try:
        r = requests.get(
            settings.constance_report_url,
            headers={"x-agent-key": settings.constance_agent_key},
            timeout=30,
        )
        if r.status_code == 401:
            return "Constance rejected the call (auth key mismatch)."
        r.raise_for_status()
        d = r.json()
        return d.get("reportText") or d.get("report_text") or "(no report cached yet)"
    except Exception as e:
        return f"Constance report pull failed: {e}"
