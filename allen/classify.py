"""Classify a memory into a life LANE (business | personal), a business UNIT
(rmg | rmi, for the business lane only), and a granular SILO — so ALLEN separates
Rahm's worlds, pulls the right context per topic, and routes archives to the
right Google Drive (personal → personal Drive, RMG → RMG Drive, RMI → RMI Drive)."""

import json
import re

from .llm import get_llm

LANES = ("business", "personal")
UNITS = ("rmg", "rmi")
CLASSES = ("core", "profile", "project", "commitment", "session", "sensitive")
SENSITIVITIES = ("low", "medium", "high")

_SYSTEM = (
    "You sort a personal-assistant memory into Rahm's life. Pick exactly one LANE, one SILO, one "
    "MEMORY_CLASS, one SENSITIVITY, and (only when the lane is business) one UNIT.\n"
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
    "MEMORY_CLASS = the kind of memory it is:\n"
    "  core = identity, purpose, operating doctrine, non-negotiable standards (rare; usually set by Rahm directly).\n"
    "  profile = stable facts about Rahm — preferences, roles, businesses, active domains.\n"
    "  project = facts about a specific project/world (RMG, RMI, Master Atelier, ALLIE, Axis, etc.).\n"
    "  commitment = a promise, deadline, follow-up, reminder, obligation, or open loop.\n"
    "  session = recent, possibly-fleeting context that may expire unless it proves stable.\n"
    "  sensitive = health, family, finance, legal, credentials-adjacent, or private personal matters.\n"
    "SENSITIVITY = low | medium | high (high for health, finance, legal, family, credentials-adjacent).\n"
    "SILO = a short lowercase tag (1-2 words) for the specific area. Prefer these when they fit:\n"
    "  personal: health, appointments, home, family, finance, leisure, relationships, errands\n"
    "  business: rmg, youtube, content, finance, operations, strategy, clients\n"
    "Use a new concise tag only if none fit.\n"
    'Return STRICT JSON only: {"lane":"...","unit":"rmg|rmi|null","silo":"...","memory_class":"...","sensitivity":"..."}'
)


def classify_memory(content: str) -> dict:
    try:
        raw = get_llm().complete(system=_SYSTEM, user=(content or "")[:600], max_tokens=110)
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
    memory_class = str(obj.get("memory_class", "")).lower().strip()
    if memory_class not in CLASSES:
        memory_class = "session"  # safest default: don't durably promote unclassified notes (policy #2)
    sensitivity = str(obj.get("sensitivity", "")).lower().strip()
    if sensitivity not in SENSITIVITIES:
        sensitivity = "high" if memory_class == "sensitive" else "low"
    return {"lane": lane, "unit": unit, "silo": silo, "memory_class": memory_class, "sensitivity": sensitivity}
