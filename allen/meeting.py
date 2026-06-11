"""ALLEN Transcriber — turn a raw meeting transcript into a useful brief:
a summary, action items, and durable highlights worth remembering."""

import json
import re
from typing import Optional

from .llm import get_llm


def _parse_obj(raw: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def summarize(transcript: str, brand: Optional[str] = None) -> dict:
    system = (
        "You are ALLEN, summarizing a meeting transcript for Rahm. Be tight and useful. "
        "Return STRICT JSON only with keys: "
        '"summary" (a 3-6 sentence plain-English recap), '
        '"action_items" (array of short imperative to-dos, naming the owner if clear), '
        '"highlights" (array of the most important durable facts or decisions worth remembering '
        "long-term). No prose outside the JSON."
    )
    raw = get_llm().complete(
        system=system,
        user=f"{'Brand context: ' + brand + chr(10) if brand else ''}Transcript:\n{transcript[:14000]}",
        max_tokens=1200,
    )
    obj = _parse_obj(raw)
    return {
        "summary": str(obj.get("summary", ""))[:4000],
        "action_items": [str(x)[:300] for x in (obj.get("action_items") or [])][:25],
        "highlights": [str(x)[:300] for x in (obj.get("highlights") or [])][:15],
    }
