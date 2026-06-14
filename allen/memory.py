"""Shared memory-context builders for ALLEN and ALLIE.

ALLEN sees everything; ALLIE sees the GATEKEEPER-filtered business view only (core directives +
business knowledge, never Rahm's personal lane or sensitive-class memories). Kept in its own module
so both the web layer and the agent layer can use it without import cycles."""

from collections import OrderedDict
from typing import Optional

from . import db


def format_memories(mems: list) -> Optional[str]:
    """Render a memory list grouped by lane → silo (with ids)."""
    if not mems:
        return None
    pinned = [m for m in mems if m.get("pinned")]
    rest = [m for m in mems if not m.get("pinned")]
    out: list[str] = []
    if pinned:
        out.append("CORE PURPOSE & DIRECTIVES — always honor these; they define who you are and what you serve:")
        for m in pinned:
            out.append(f"  ★ [id:{m['id']}] {m['content']}")
        out.append("")
    if rest:
        lanes: "OrderedDict[str, OrderedDict[str, list]]" = OrderedDict()
        for m in rest:
            lane = (m.get("lane") or "personal").upper()
            silo = m.get("silo") or "general"
            lanes.setdefault(lane, OrderedDict()).setdefault(silo, []).append(m)
        out.append("Known facts about Rahm — use the lane and silo relevant to the topic:")
        for lane, silos in lanes.items():
            out.append(lane)
            for silo, items in silos.items():
                for m in items:
                    tags = " | ".join(t for t in [m.get("memory_class"), m.get("unit"), silo] if t)
                    out.append(f"  [{tags} | id:{m['id']}] {m['content']}")
    return "\n".join(out)


def allen_context(namespace: str) -> Optional[str]:
    """ALLEN's full view — everything he remembers, across business and personal."""
    if not db.db_ready():
        return None
    return format_memories(db.list_memories(namespace))


def allie_context(namespace: str) -> Optional[str]:
    """ALLIE's view — the GATEKEEPER boundary in code: core directives + BUSINESS knowledge only,
    never Rahm's personal lane or any sensitive-class memory."""
    if not db.db_ready():
        return None
    mems = [
        m for m in db.list_memories(namespace)
        if m.get("pinned") or (m.get("lane") == "business" and m.get("memory_class") != "sensitive")
    ]
    return format_memories(mems)
