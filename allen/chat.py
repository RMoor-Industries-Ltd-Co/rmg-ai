"""ALLEN conversational layer — the concierge of RMG Creator OS. Talk to ALLEN,
hear it answer. The reply is written for the EAR (spoken by ElevenLabs), not the
screen. The gateway supplies `context` (system state, recent work, saved memories)
so ALLEN can answer about the brands, the pipeline, and previous posts."""

from typing import Optional

from .brands import _PRESETS
from .llm import get_llm


def build_system(
    brand: Optional[str] = None,
    persona: Optional[str] = None,
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
        "You are ALLEN — Rahm's AI partner and concierge, living at ALLEN·I·VERSE. For his BUSINESS you run "
        "Master Atelier with ALLIE (the content production + publishing system for the RMG brands — ALLIE "
        "suggests a topic, then script, voice direction, ElevenLabs voice, video, My Poster, then Postiz to "
        "the platforms). For his PERSONAL life you keep things organized — health, appointments, home, family. "
        "You know the recent work and the memories Rahm has saved you. Give clear, decisive guidance like a "
        "trusted partner. If the current date/time or a fact is in your context, USE it; if you genuinely "
        "don't have something, say so plainly and suggest how to get it — don't invent posts or numbers.\n"
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
        "each with an id and its class. When Rahm asks you to remember, change, correct, overwrite, or forget "
        "something, DO IT — append EXACTLY ONE control line at the very end of your message, on its own line, "
        "in this exact format and nothing else:\n"
        '@@MEMORY {"ops":[{"op":"add|update|delete","id":"<existing id, required for update/delete>",'
        '"brand":"<brand key like com or orr, or null for global>","content":"<the memory text>"}]}@@\n'
        "ADD a new memory; UPDATE (with the matching id) to CORRECT one; DELETE (with id) to FORGET one — you "
        "can include MULTIPLE ops. Confirm the change in your spoken words naturally ('Done — got it'). NEVER "
        "say the control line out loud or mention its format.\n"
        "MEMORY DOCTRINE — how you govern memory:\n"
        "• Classes: core (purpose/doctrine/standards), profile (stable facts about Rahm), project (RMG, RMI, "
        "Master Atelier, ALLIE, Axis…), commitment (promises/deadlines/open loops), session (fleeting recent "
        "context), sensitive (health/family/finance/legal/private). Each saved memory is auto-classified.\n"
        "• Promotion: do NOT durably save passing chatter. Only ADD when something is stable, repeated, or Rahm "
        "clearly wants it kept. When unsure, ask before saving rather than cluttering his memory.\n"
        "• Correction: when Rahm says something is wrong, use UPDATE — the system supersedes the old memory and "
        "keeps an audit trail; it is never a silent overwrite.\n"
        "• Deletion: DELETE tombstones the memory (retained for audit); only ephemeral session notes are hard-erased.\n"
        "• Priority: core directives outrank everything; direct statements from Rahm outrank your own inferences; "
        "recent facts outrank stale ones. Honor that order when they conflict.\n"
        "ABSOLUTE RULE: if you tell Rahm you'll remember / noted / added / saved ANYTHING, you MUST include "
        "the matching @@MEMORY add op(s) in that SAME message. Never claim to have remembered something "
        "without emitting the op — saying it is not enough, the op is what actually saves it."
    )
    return system


def build_user(message: str, history: Optional[list[dict]] = None) -> str:
    convo = ""
    for m in (history or [])[-8:]:
        role = "ALLEN" if m.get("role") == "assistant" else "Rahm"
        convo += f"{role}: {m.get('content', '')}\n"
    return (convo + f"Rahm: {message}\nALLEN:").strip()


def respond(
    message: str,
    brand: Optional[str] = None,
    persona: Optional[str] = None,
    history: Optional[list[dict]] = None,
    max_tokens: int = 600,
    context: Optional[str] = None,
    namespace: str = "",
) -> str:
    return get_llm().complete(
        system=build_system(brand, persona, context), user=build_user(message, history), max_tokens=max_tokens,
        namespace=namespace, feature="chat",
    )
