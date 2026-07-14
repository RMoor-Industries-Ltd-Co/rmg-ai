"""Thoth — axis-tekhen's gap-scanner manager (rmg-piaar-system contract 22). Pull-only status
read: GET /stocks/thoth/candidates merges ALLIE's pushed feed signals (tools_market_feed.py,
a completely separate non-agentic pipeline from this file) with axis-tekhen's own always-on
gap-scanner worker — both sources are already continuously fresh, so this cheap read-time
merge never needs a separate proactive-refresh job. This tool just reads it; it never
triggers a rescan."""

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
        candidates = data if isinstance(data, list) else data.get("candidates", [])
        if not candidates:
            return "No hot candidates on Thoth's board right now."
        lines = []
        for c in candidates[:20]:
            ticker = c.get("ticker", "?")
            score = c.get("compositeScore")
            feed_signals = c.get("feedSignals") or []
            reason = (feed_signals[0].get("reason", "") if feed_signals else "") or ""
            bits = [f"score {score}"] if score is not None else []
            if reason:
                bits.append(reason)
            lines.append(f"- {ticker}" + (f" ({', '.join(bits)})" if bits else ""))
        return "\n".join(lines)
    except Exception as e:
        return f"Thoth call failed: {e}"
