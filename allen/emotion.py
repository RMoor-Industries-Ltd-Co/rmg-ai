"""Emotion Director — replicates the ElevenLabs Emotion Creator + Director GPTs,
upgraded for eleven_v3. Annotates an approved script with v3 audio tags, CAPS
emphasis, ellipsis pauses, and recommends a stability mode. Per-brand palettes
come from the brand voice (see BRAND_PROMPTS optimization columns)."""

from typing import Optional

from .brands import _PRESETS
from .llm import get_llm

# Per-brand emotion profiles (from the BRAND_PROMPTS optimization columns).
EMOTION_PROFILES: dict[str, dict[str, str]] = {
    "com": {
        "tags": "[thoughtful] [measured] [sincere] [reflective]; sparing [emphatic]",
        "stability": "natural",
        "emphasis": "light CAPS on 1-2 pivotal words; let punctuation carry the weight",
        "pacing": "measured, deliberate; pause before the lesson lands",
    },
    "vlog": {
        "tags": "[clear] [focused] [assured]; brief pauses at key transitions",
        "stability": "natural",
        "emphasis": "light CAPS on one technical or payoff word",
        "pacing": "deliberate, even; crisp segment breaks",
    },
    "mstr-rahm": {
        "tags": "[intense] [emphatic] [bold]; fast beats; rare pause before the hit",
        "stability": "creative",
        "emphasis": "CAPS on the punch line; staccato",
        "pacing": "fast, hard cuts; punchy momentum",
    },
    "busy-mf": {
        "tags": "[excited] [energetic] [confident]; quick; [emphatic] on the offer",
        "stability": "creative",
        "emphasis": "CAPS on the hook and the offer",
        "pacing": "fast hooks, bold rhythm, snappy",
    },
    "orr": {
        "tags": "[warm] [inviting] [relaxed]; gentle pauses; [delighted]",
        "stability": "natural",
        "emphasis": "minimal CAPS; let sensory detail carry it",
        "pacing": "smooth, unhurried; lets scenes breathe",
    },
    "trc": {
        "tags": "[provocative] [measured] [pointed]; pauses for debate beats",
        "stability": "natural",
        "emphasis": "CAPS sparingly on the contested word",
        "pacing": "measured with sharp turns; panel rhythm",
    },
}

STABILITY_VALUE = {"creative": 0.0, "natural": 0.5, "robust": 1.0}


def direct(script: str, brand: str, persona: Optional[str], intensity: Optional[str]) -> dict:
    prof = EMOTION_PROFILES.get((brand or "").lower(), EMOTION_PROFILES["com"])
    b = _PRESETS["brands"].get((brand or "").lower(), {})
    brand_tone = b.get("tone_rules", "")

    system = (
        "You are the Emotion Director for ElevenLabs v3 voice synthesis. Annotate the script "
        "for emotional, dynamic delivery WITHOUT changing the words, their order, or their meaning. "
        "Apply only:\n"
        f"1. v3 AUDIO TAGS in [square brackets] at emotional beats. Brand palette: {prof['tags']}. "
        "Use them sparingly and tastefully — a few per script, never on every line.\n"
        f"2. EMPHASIS: {prof['emphasis']}.\n"
        "3. PAUSES: use ellipses (…) for dramatic pauses; tune commas and periods for rhythm.\n"
        f"4. PACING intent: {prof['pacing']}.\n"
        f"Match this brand's emotional register: {brand_tone[:600]}\n"
        + (f"Intensity: {intensity}.\n" if intensity else "")
        + "Return ONLY the annotated script text — no commentary, no labels."
    )
    tagged = get_llm().complete(system=system, user=f"Script:\n{script}", max_tokens=1500)
    mode = prof["stability"]
    return {
        "tagged_script": tagged,
        "stability_mode": mode,
        "stability": STABILITY_VALUE.get(mode, 0.5),
        "audio_tag_palette": prof["tags"],
    }
