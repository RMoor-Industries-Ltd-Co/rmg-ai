"""Emotion Director — annotates an approved script with ElevenLabs v3 audio tags
for dynamic, realistic delivery. Based on verified ElevenLabs v3 documentation:
- Square-bracket tags [like this] are the primary mechanism; they are NOT spoken aloud
- ALL CAPS does NOT reliably produce emphasis in v3 — use [emphatic]/[drawn out] instead
- SSML break tags are not supported in v3; use [pause]/[short pause]/[long pause] tags
- Ellipses work as soft hesitation pauses; em dashes for hard breaks"""

from typing import Optional

from .brands import _PRESETS
from .llm import get_llm

# Per-brand emotion profiles aligned with verified ElevenLabs v3 tag vocabulary.
# Emphasis is tag-based only — ALL CAPS removed (ineffective in v3, per official docs).
EMOTION_PROFILES: dict[str, dict[str, str]] = {
    "com": {
        "tags": "[thoughtful] [sincere] [reflective] [measured]; [emphatic] at the lesson; [pause] before wisdom lands",
        "stability": "natural",
        "delivery": "measured, deliberate; [pause] before the key insight; [drawn out] on pivotal words",
        "pacing": "unhurried; let the idea settle; paragraph breaks are breathing room",
    },
    "vlog": {
        "tags": "[clear] [focused] [assured]; [drawn out] on the payoff word; [short pause] at transitions",
        "stability": "natural",
        "delivery": "[drawn out] on one key technical or payoff word per segment; crisp segment breaks",
        "pacing": "deliberate and even; clean cuts between ideas; no rush",
    },
    "mstr-rahm": {
        "tags": "[intense] [emphatic] [bold]; [pause] before the hit; [dramatic tone] on the punchline",
        "stability": "creative",
        "delivery": "[emphatic] on the punchline; [rushed] through the build; [pause] — then land it hard",
        "pacing": "fast momentum, hard cuts; punchy staccato; silence is a weapon",
    },
    "busy-mf": {
        "tags": "[excited] [energetic] [confident]; [emphatic] on the hook; [emphatic] on the offer",
        "stability": "creative",
        "delivery": "[excited] at the open; [emphatic] on the hook word and the offer; [rushed] through the detail",
        "pacing": "fast hooks, snappy rhythm; quick transitions; bold and direct",
    },
    "orr": {
        "tags": "[warm] [inviting] [relaxed]; [delighted] on sensory details; [pause] to let scenes breathe",
        "stability": "natural",
        "delivery": "[warm] throughout; [delighted] on the experience words; let scenes breathe naturally",
        "pacing": "smooth, unhurried; long pauses welcome; sensory language carries the weight",
    },
    "trc": {
        "tags": "[provocative] [measured] [pointed]; [pause] at debate turns; [sarcastic] when challenging assumptions",
        "stability": "natural",
        "delivery": "[pointed] on the contested word; [pause] before the counter-argument; sharp panel rhythm",
        "pacing": "measured with sharp turns; a beat of silence before each reframe",
    },
}

STABILITY_VALUE = {"creative": 0.0, "natural": 0.5, "robust": 1.0}

# Human-facing brand labels for the Voice Direction UI.
BRAND_LABELS = {
    "com": "COM — Conversations of Mastery",
    "vlog": "VLOG — Virtual Legacy of Greatness",
    "mstr-rahm": "MSTR_RAHM — Master Rahm",
    "busy-mf": "BU$Y_MF — Business Monday–Friday",
    "orr": "ORR / R+R — Our Royal Reservations",
    "trc": "TRC — The Rahm Council",
}


def profiles() -> dict:
    """Serializable emotion profiles + tag rules for the Voice Direction UI."""
    out = []
    for key, prof in EMOTION_PROFILES.items():
        out.append(
            {
                "brand": key,
                "label": BRAND_LABELS.get(key, key),
                "tags": prof["tags"],
                "delivery": prof["delivery"],
                "pacing": prof["pacing"],
                "stability_mode": prof["stability"],
                "stability": STABILITY_VALUE.get(prof["stability"], 0.5),
            }
        )
    return {"profiles": out, "stability_values": STABILITY_VALUE}


def direct(
    script: str,
    brand: str,
    persona: Optional[str],
    intensity: Optional[str],
    stability_mode: Optional[str] = None,
    brand_examples: Optional[list[str]] = None,
) -> dict:
    prof = EMOTION_PROFILES.get((brand or "").lower(), EMOTION_PROFILES["com"])
    b = _PRESETS["brands"].get((brand or "").lower(), {})
    brand_tone = b.get("tone_rules", "")

    system = (
        "You are the Emotion Director for ElevenLabs v3 voice synthesis.\n\n"
        "RULES (follow exactly):\n"
        "1. Annotate the script for emotional, dynamic delivery WITHOUT changing any words, their order, or meaning.\n"
        "2. Use v3 AUDIO TAGS in [square brackets] at emotional beats — these are never spoken aloud, they direct the voice.\n"
        f"   Brand tag palette: {prof['tags']}\n"
        "   Full v3 tag vocabulary: emotions [sad] [angry] [happily] [sorrowful] [excited] [tired] [awe] [curious] "
        "[crying] [mischievously] [nervous] [sarcastic] [emphatic] [resigned tone]; "
        "delivery [whispers] [shouts] [dramatic tone] [rushed] [drawn out] [hesitates] [stammers]; "
        "pauses [pause] [short pause] [long pause]; "
        "reactions [laughs] [sighs] [clears throat] [breathes].\n"
        "   Use tags sparingly and tastefully — a few key moments per script, NOT on every line.\n"
        "   Tags can be chained: [sorrowful] I couldn't sleep... [quietly] And that's when I saw it.\n"
        "3. PAUSES: Use [pause] / [short pause] / [long pause] tags at dramatic beats. "
        "Use ellipses (…) only for soft hesitation moments. Em dashes (—) for hard, sharp breaks.\n"
        f"4. DELIVERY style: {prof['delivery']}\n"
        f"5. PACING: {prof['pacing']}\n"
        "6. DO NOT use ALL CAPS for emphasis — it does not reliably work in ElevenLabs v3.\n"
        f"7. Match this brand's emotional register: {brand_tone[:600]}\n"
        + (f"8. Intensity: {intensity}.\n" if intensity else "")
        + "Return ONLY the annotated script text — no commentary, no labels, no explanation."
    )

    user = f"Script:\n{script}"

    if brand_examples:
        user += "\n\n## TAGGED SCRIPT MEMORY — previously directed scripts for this brand. Match this tagging density, style, and emotional register:\n"
        for i, ex in enumerate(brand_examples[:3], 1):
            user += f"\n--- Example {i} ---\n{ex.strip()}\n"
        user += "\n---"

    tagged = get_llm().complete(system=system, user=user, max_tokens=1500)
    mode = (stability_mode or prof["stability"]).lower()
    if mode not in STABILITY_VALUE:
        mode = prof["stability"]
    return {
        "tagged_script": tagged,
        "stability_mode": mode,
        "stability": STABILITY_VALUE.get(mode, 0.5),
        "audio_tag_palette": prof["tags"],
    }
