"""Classify a memory into a life LANE (business | personal), a business UNIT
(rmg | rmi, for the business lane only), and a granular SILO — so ALLEN separates
Rahm's worlds, pulls the right context per topic, and routes archives to the
right Google Drive (personal → personal Drive, RMG → RMG Drive, RMI → RMI Drive)."""

import json
import re

from .llm import get_llm

LANES = ("business", "personal")
UNITS = ("rmg", "rmi")

_SYSTEM = (
    "You sort a personal-assistant memory into Rahm's life. Pick exactly one LANE, one SILO, and "
    "(only when the lane is business) one UNIT.\n"
    "LANE = business | personal.\n"
    "  business = RMG brands, YouTube, content production, the company, work finances, ops, strategy, "
    "consulting / advisory clients.\n"
    "  personal = health, appointments, home & chores, family, personal finances, leisure / personal "
    "time, relationships, errands.\n"
    "UNIT (business lane only; null for personal) = rmg | rmi.\n"
    "  rmg = Renaissance Masters Group — the creator/content side: the RMG brands, YouTube, video "
    "production, publishing, audience.\n"
    "  rmi = RMoor Industries — the consulting / advisory side: clients, engagements, advisory work, "
    "RMI company operations. When a business memory isn't clearly consulting, default UNIT to rmg.\n"
    "SILO = a short lowercase tag (1-2 words) for the specific area. Prefer these when they fit:\n"
    "  personal: health, appointments, home, family, finance, leisure, relationships, errands\n"
    "  business: rmg, youtube, content, finance, operations, strategy, clients\n"
    "Use a new concise tag only if none fit.\n"
    'Return STRICT JSON only: {"lane":"...","unit":"rmg|rmi|null","silo":"..."}'
)


def classify_memory(content: str) -> dict:
    try:
        raw = get_llm().complete(system=_SYSTEM, user=(content or "")[:600], max_tokens=80)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        obj = json.loads(m.group(0)) if m else {}
    except Exception:
        obj = {}
    lane = str(obj.get("lane", "")).lower().strip()
    if lane not in LANES:
        lane = "personal"
    silo = str(obj.get("silo", "")).lower().strip().replace(" ", "-")[:24] or "general"
    unit = str(obj.get("unit", "")).lower().strip()
    if lane == "business":
        unit = unit if unit in UNITS else "rmg"  # business defaults to RMG unless clearly consulting
    else:
        unit = None
    return {"lane": lane, "unit": unit, "silo": silo}
