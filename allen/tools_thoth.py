"""Thoth — axis-tekhen's gap-scanner manager (rmg-piaar-system contract 22). Pull-only status
read: Thoth's candidate board is already built/cached inside axis-tekhen (rebuilt reactively
whenever ALLIE's feed-watch job pushes a hot symbol via tools_market_feed.py — a completely
separate, non-agentic pipeline from this file). This tool just reads what's already there;
it never triggers a rebuild."""

import requests

from .config import settings

TOOLS = [
    {
        "name": "thoth_get_status",
        "description": (
            "Pull Thoth's current candidate board from AXIS (axis-tekhen) — hot instruments Thoth "
            "has already flagged and documented. Read-only; does not trigger any new scan."
        ),
        "input_schema": {"type": "object", "properties": {}},
    }
]


def ready() -> bool:
    return settings.thoth_status_ready


def handle(_name: str, _args: dict) -> str:
    if not ready():
        return "Thoth's status feed isn't connected yet."
    headers = {}
    if settings.thoth_status_token:
        headers["Authorization"] = f"Bearer {settings.thoth_status_token}"
    try:
        r = requests.get(settings.thoth_status_url, headers=headers, timeout=30)
        if r.status_code == 401:
            return "Thoth rejected the call (auth mismatch)."
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates", data if isinstance(data, list) else [])
        if not candidates:
            return "No hot candidates on Thoth's board right now."
        lines = []
        for c in candidates[:20]:
            ticker = c.get("ticker") or c.get("symbol", "?")
            reason = c.get("reason", "")
            lines.append(f"- {ticker}: {reason}" if reason else f"- {ticker}")
        return "\n".join(lines)
    except Exception as e:
        return f"Thoth call failed: {e}"
