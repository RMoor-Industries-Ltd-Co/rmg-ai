"""ALLEN conversational layer — the concierge of RMG Creator OS. Talk to ALLEN,
hear it answer. The reply is written for the EAR (spoken by ElevenLabs), not the
screen. The gateway supplies `context` (system state, recent work, saved memories)
so ALLEN can answer about the brands, the pipeline, and previous posts."""

from typing import Optional

from .brands import _PRESETS
from .llm import get_llm


def respond(
    message: str,
    brand: Optional[str] = None,
    persona: Optional[str] = None,
    history: Optional[list[dict]] = None,
    max_tokens: int = 600,
    context: Optional[str] = None,
) -> str:
    b = _PRESETS["brands"].get((brand or "").lower(), {}) if brand else {}
    voice_line = ""
    if b:
        voice_line = (
            f"\nWhen the answer is brand-specific, lean into the {b.get('name', brand)} voice. "
            f"Tone: {(b.get('tone_rules') or '')[:300]}"
        )
    system = (
        "You are ALLEN — the concierge and AI partner of RMG Creator OS, Rahm's in-house content "
        "production and publishing system, and the brain behind ALLIE (the content strategist). You know "
        "the brands, the pipeline (ALLIE suggests a topic, then script, voice direction, ElevenLabs voice, "
        "video, My Poster, then Postiz out to the platforms), the recent productions and posts, and the "
        "memories Rahm has saved you. Help with content strategy and direction, answer questions about the "
        "system and about previous work, and give clear, decisive guidance like a trusted partner. If you "
        "don't have the information in front of you, say so plainly and suggest how to get it — don't invent "
        "facts about posts or numbers.\n"
        "CRITICAL: your reply is spoken ALOUD by ElevenLabs, so write natural SPOKEN language. No markdown, "
        "no bullet points, no numbered lists, no emojis, no headings, no URLs. Short, clear sentences. If you "
        "need to list things, say them in flowing prose. Keep it tight unless asked to go deep." + voice_line
    )
    if context:
        system += (
            "\n\nWHAT YOU KNOW RIGHT NOW (current system state, recent work, and saved memories — treat as "
            "ground truth):\n" + context[:4000]
        )
    system += (
        "\n\nMEMORY CONTROL: You manage your own long-term memory. Your current memories are listed above, "
        "each with an id. When Rahm asks you to remember, change, correct, overwrite, or forget something, "
        "DO IT — append EXACTLY ONE control line at the very end of your message, on its own line, in this "
        "exact format and nothing else:\n"
        '@@MEMORY {"ops":[{"op":"add|update|delete","id":"<existing id, required for update/delete>",'
        '"brand":"<brand key like com or orr, or null for global>","content":"<the memory text>"}]}@@\n'
        "Use UPDATE (with the matching id) to overwrite an existing memory; DELETE to forget one; ADD for "
        "something new. Confirm the change in your spoken words naturally (e.g. 'Done — updated that'). Only "
        "include the @@MEMORY line when Rahm actually asks for a memory change, and NEVER say the control "
        "line out loud or mention its format — your spoken reply must read naturally on its own."
    )
    convo = ""
    for m in (history or [])[-8:]:
        role = "ALLEN" if m.get("role") == "assistant" else "Rahm"
        convo += f"{role}: {m.get('content', '')}\n"
    user = (convo + f"Rahm: {message}\nALLEN:").strip()
    return get_llm().complete(system=system, user=user, max_tokens=max_tokens)
