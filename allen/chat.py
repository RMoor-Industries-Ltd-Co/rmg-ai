"""ALLEN conversational layer — talk to ALLEN, hear it answer. The reply is
written for the EAR (it gets spoken by ElevenLabs), not the screen."""

from typing import Optional

from .brands import _PRESETS
from .llm import get_llm


def respond(
    message: str,
    brand: Optional[str] = None,
    persona: Optional[str] = None,
    history: Optional[list[dict]] = None,
    max_tokens: int = 600,
) -> str:
    b = _PRESETS["brands"].get((brand or "").lower(), {}) if brand else {}
    voice_line = ""
    if b:
        voice_line = (
            f"\nAnswer in the {b.get('name', brand)} brand voice. "
            f"Tone: {(b.get('tone_rules') or '')[:400]}"
        )
    system = (
        "You are ALLEN — the in-house AI partner inside RMG Creator OS, and the brain behind ALLIE, "
        "the content strategist. You help Rahm run the whole content pipeline: brand strategy, topic "
        "ideas, scripts, voice direction, posting, and decisions. Be warm, sharp, and concise — a "
        "trusted creative partner, not a corporate assistant.\n"
        "CRITICAL: your reply is spoken ALOUD by ElevenLabs, so write natural SPOKEN language. No "
        "markdown, no bullet points, no numbered lists, no emojis, no headings, no stage directions, "
        "no URLs. Short, clear sentences. If you need to list things, say them in flowing prose. Keep "
        "it tight unless asked to go deep." + voice_line
    )
    convo = ""
    for m in (history or [])[-8:]:
        role = "ALLEN" if m.get("role") == "assistant" else "Rahm"
        convo += f"{role}: {m.get('content', '')}\n"
    user = (convo + f"Rahm: {message}\nALLEN:").strip()
    return get_llm().complete(system=system, user=user, max_tokens=max_tokens)
