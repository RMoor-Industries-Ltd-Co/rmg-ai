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


def _brand_grounding(b: dict) -> str:
    """Compose the brand's real content identity (pillars/formats/audience) so
    suggestions stay in-lane and reflect what the brand actually makes."""
    parts = []
    if b.get("name"):
        parts.append(f"BRAND: {b['name']}")
    if b.get("tagline"):
        parts.append(f"TAGLINE: {b['tagline']}")
    if b.get("system_block"):
        parts.append(f"WHAT THIS BRAND IS:\n{b['system_block'][:900]}")
    if b.get("audience"):
        parts.append(f"AUDIENCE: {b['audience']}")
    pillars = b.get("content_pillars") or []
    if pillars:
        parts.append("CONTENT PILLARS (stay inside these lanes):\n- " + "\n- ".join(pillars))
    formats = b.get("content_formats") or []
    if formats:
        parts.append("FORMATS: " + "; ".join(formats))
    examples = b.get("example_topics") or []
    if examples:
        parts.append(
            "EXAMPLE TOPICS (match this style/subject matter; do NOT copy verbatim):\n- "
            + "\n- ".join(examples)
        )
    if b.get("tone_rules"):
        parts.append(f"TONE: {b['tone_rules'][:500]}")
    return "\n\n".join(parts)


def suggest(brand: str, count: int = 6, context: Optional[str] = None) -> list[dict]:
    b = _PRESETS["brands"].get((brand or "").lower(), {})
    grounding = _brand_grounding(b) or f"Brand: {brand} (no preset on file)."
    system = (
        "You are ALLIE, the content strategist for the RMG brand ecosystem. Propose fresh, "
        "high-engagement SHORT-FORM video topics that are UNMISTAKABLY this brand — drawn from its "
        "content pillars, formats, and subject matter below. Be specific (name real places, formats, "
        "verdicts where the brand does that), not generic. If the brand is a review brand, suggest "
        "reviews/verdicts/guides — not abstract motivational takes.\n\n"
        f"{grounding}\n\n"
        + (f"CURRENT TREND/EVENT SIGNALS to draw from:\n{context[:1000]}\n\n" if context else "")
        + f"Return STRICT JSON only: an array of {count} objects, each with keys "
        '"title" (the topic, punchy), "hook" (a scroll-stopping first line), '
        '"angle" (one short phrase on the take). Every topic MUST sit inside the brand\'s pillars. '
        "No prose, JSON only."
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
