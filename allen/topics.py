"""ALLIE topic suggestions — the always-on 'next topic per brand' engine. v1 is
Claude grounded in brand voice; pass `context` (RSS/trend signals) once ALLIE's
feed ingestion exists to make them current with events."""

import json
import re
from typing import Optional

from .brands import _PRESETS
from .llm import get_llm


def _parse_array(raw: str) -> list:
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return []


def suggest(brand: str, count: int = 6, context: Optional[str] = None) -> list[dict]:
    b = _PRESETS["brands"].get((brand or "").lower(), {})
    tone = b.get("tone_rules", "")
    system = (
        "You are ALLIE, the content strategist for the RMG brand ecosystem. Propose fresh, "
        "high-engagement SHORT-FORM video topics for this brand — true to its voice and audience, "
        "specific (not generic), and worth filming now.\n"
        f"Brand voice rules: {tone[:700]}\n"
        + (f"Current trend/event signals to draw from:\n{context[:1000]}\n" if context else "")
        + f"Return STRICT JSON only: an array of {count} objects, each with keys "
        '"title" (the topic, punchy), "hook" (a scroll-stopping first line), '
        '"angle" (one short phrase on the take). No prose, JSON only.'
    )
    raw = get_llm().complete(system=system, user=f"Brand: {brand}. Give {count} distinct topic ideas.", max_tokens=1000)
    out = []
    for it in _parse_array(raw)[:count]:
        if isinstance(it, dict) and it.get("title"):
            out.append(
                {
                    "title": str(it["title"])[:140],
                    "hook": str(it.get("hook", ""))[:200],
                    "angle": str(it.get("angle", ""))[:160],
                }
            )
    return out
