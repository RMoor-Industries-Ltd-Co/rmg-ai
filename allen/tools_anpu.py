"""Anpu — axis-tekhen's autonomous LLM oversight agent (rmg-piaar-system contract 21). Pull-only:
Anpu is its own always-on worker (backend/cli/run_anpu_agent.py), completely independent of
ALLEN-I-VERSE — ALLIE never triggers Anpu to run, she only reads what he's already produced and
persisted (anpu_reviews, schema anpu.review.v1). This mirrors tools_cappo.py's request/auth
shape but is read-only, since Anpu's autonomy stays entirely inside axis-tekhen."""

import requests

from .config import settings

TOOLS = [
    {
        "name": "anpu_get_reviews",
        "description": (
            "Pull Anpu's latest oversight reviews from AXIS (axis-tekhen) — proposed remediations "
            "for trading-system incidents Anpu has already triaged. Read-only; does not trigger Anpu "
            "to do anything, just reads what he's already produced."
        ),
        "input_schema": {"type": "object", "properties": {}},
    }
]


def ready() -> bool:
    return settings.anpu_reviews_ready


def handle(_name: str, _args: dict) -> str:
    if not ready():
        return "Anpu isn't connected yet."
    headers = {}
    if settings.anpu_reviews_token:
        headers["Authorization"] = f"Bearer {settings.anpu_reviews_token}"
    try:
        r = requests.get(settings.anpu_reviews_url, headers=headers, timeout=30)
        if r.status_code == 401:
            return "Anpu rejected the call (auth mismatch)."
        r.raise_for_status()
        data = r.json()
        reviews = data.get("reviews", data if isinstance(data, list) else [])
        if not reviews:
            return "No Anpu reviews yet."
        lines = []
        for rv in reviews[:20]:
            summary = rv.get("summary") or rv.get("review", {}).get("summary", "")
            status = rv.get("status", "?")
            confidence = rv.get("confidence") or rv.get("review", {}).get("confidence")
            lines.append(f"- [{status}] {summary}" + (f" (confidence {confidence})" if confidence else ""))
        return "\n".join(lines)
    except Exception as e:
        return f"Anpu call failed: {e}"
