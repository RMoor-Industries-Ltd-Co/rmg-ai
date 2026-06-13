"""Classify a memory into a life LANE (business | personal) and a granular SILO,
so ALLEN separates Rahm's two worlds and pulls the right context per topic."""

import json
import re

from .llm import get_llm

LANES = ("business", "personal")

_SYSTEM = (
    "You sort a personal-assistant memory into Rahm's life. Pick exactly one LANE and one SILO.\n"
    "LANE = business | personal.\n"
    "  business = RMG brands, YouTube, content production, the company, work finances, ops, strategy.\n"
    "  personal = health, appointments, home & chores, family, personal finances, leisure / personal "
    "time, relationships, errands.\n"
    "SILO = a short lowercase tag (1-2 words) for the specific area. Prefer these when they fit:\n"
    "  personal: health, appointments, home, family, finance, leisure, relationships, errands\n"
    "  business: rmg, youtube, content, finance, operations, strategy, clients\n"
    "Use a new concise tag only if none fit.\n"
    'Return STRICT JSON only: {"lane":"...","silo":"..."}'
)


def classify_memory(content: str) -> dict:
    try:
        raw = get_llm().complete(system=_SYSTEM, user=(content or "")[:600], max_tokens=60)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        obj = json.loads(m.group(0)) if m else {}
    except Exception:
        obj = {}
    lane = str(obj.get("lane", "")).lower().strip()
    if lane not in LANES:
        lane = "personal"
    silo = str(obj.get("silo", "")).lower().strip().replace(" ", "-")[:24] or "general"
    return {"lane": lane, "silo": silo}
