"""Emotion Director — annotates an approved script for ElevenLabs voice synthesis.
Two rulesets, chosen by `version`:
- v3: square-bracket audio tags [like this] (not spoken aloud) PLUS ALL CAPS on emphasized
  words — both mechanisms together in one document. SSML breaks aren't supported; use
  [pause]/[short pause]/[long pause] tags. Ellipses = soft hesitation; em dashes = hard breaks.
- v2: the v2 model does not parse bracket tags (it speaks them aloud literally), so v2
  annotation relies on ALL CAPS + punctuation (ellipses/em dashes) only; emotional delivery
  is carried by the stability/style sliders, not inline tags."""

import re
from typing import Optional

from .brand_contracts import get_contract
from .brands import _PRESETS
from .llm import get_llm

# Per-brand emotion profiles aligned with the v3 tag vocabulary (also used to derive
# stability/pacing guidance for v2, which has no bracket tags of its own).
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
    """Serializable emotion profiles + tag rules for the Voice Direction UI. `emphasis` is
    the field name the dashboard's EmotionProfile type actually reads — profiles() used to
    ship a `delivery` key instead, so the "Tag rules" panel silently rendered undefined."""
    out = []
    for key, prof in EMOTION_PROFILES.items():
        contract = get_contract(key)
        if contract:
            out.append(
                {
                    "brand": key,
                    "label": contract["display_name"],
                    "tags": ", ".join(contract["allowed_tags"]),
                    "emphasis": contract["voice_identity"],
                    "pacing": "; ".join(contract["pacing_rules"]),
                    "stability_mode": contract["recommended_stability"],
                    "stability": STABILITY_VALUE.get(contract["recommended_stability"], 0.5),
                }
            )
            continue
        out.append(
            {
                "brand": key,
                "label": BRAND_LABELS.get(key, key),
                "tags": prof["tags"],
                "emphasis": prof["delivery"],
                "pacing": prof["pacing"],
                "stability_mode": prof["stability"],
                "stability": STABILITY_VALUE.get(prof["stability"], 0.5),
            }
        )
    return {"profiles": out, "stability_values": STABILITY_VALUE}


def _v3_system(prof: dict, brand_tone: str, intensity: Optional[str]) -> str:
    return (
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
        "6. EMPHASIS: use ALL CAPS on emphasized words/phrases TOGETHER WITH the bracket tags above — "
        "both mechanisms apply in this document. Caps mark which word carries the emphasis; tags direct "
        "the surrounding emotional delivery. Use caps sparingly, on the single most important word per beat.\n"
        f"7. Match this brand's emotional register: {brand_tone[:600]}\n"
        + (f"8. Intensity: {intensity}.\n" if intensity else "")
        + "Return ONLY the annotated script text — no commentary, no labels, no explanation."
    )


def _v2_system(prof: dict, brand_tone: str, intensity: Optional[str]) -> str:
    return (
        "You are the Emotion Director for ElevenLabs v2 voice synthesis.\n\n"
        "RULES (follow exactly):\n"
        "1. Annotate the script for emotional, dynamic delivery WITHOUT changing any words, their order, or meaning.\n"
        "2. The v2 model does NOT parse bracket audio tags — it speaks them aloud literally. "
        "DO NOT use [square bracket] tags anywhere in this document.\n"
        "3. EMPHASIS: use ALL CAPS on the single most important word/phrase per beat — this is the primary "
        "emphasis mechanism for v2. Use sparingly, only at real emotional peaks.\n"
        "4. PAUSES/PACING: use punctuation only. Ellipses (…) for soft hesitation; em dashes (—) for hard, "
        "sharp breaks; paragraph breaks for breathing room. No tags, no SSML.\n"
        f"5. DELIVERY style (carried by narrative tone and word choice, not tags): {prof['delivery']}\n"
        f"6. PACING: {prof['pacing']}\n"
        f"7. Match this brand's emotional register: {brand_tone[:600]}\n"
        + (f"8. Intensity: {intensity}.\n" if intensity else "")
        + "Return ONLY the annotated script text — no commentary, no labels, no explanation."
    )


def _intensity_key(intensity: Optional[str]) -> str:
    key = (intensity or "default").lower()
    return key if key in ("default", "soft", "strong") else "default"


def _v3_contract_system(contract: dict, intensity_key: str) -> str:
    mode = contract["intensity_modes"][intensity_key]
    forbidden = "\n".join(f"- {f}" for f in contract["forbidden"])
    pacing = "\n".join(f"- {p}" for p in contract["pacing_rules"])
    use_tags = ", ".join(mode["use"])
    reduce_tags = ", ".join(mode.get("reduce", [])) or "(none specified)"
    example = contract.get("example")
    example_block = (
        f"\n\nEXAMPLE (Strong mode, for tagging density/style reference only — do not copy its words):\n"
        f"{example['text']}\n" if example else ""
    )
    return (
        f"You are the Emotion Director for {contract['display_name']}, voiced by {contract['host']}, "
        "annotating an approved script with ElevenLabs v3 bracket audio tags for the "
        "\"Re-apply direction\" step.\n\n"
        "Follow this brand's performance contract exactly:\n\n"
        f"VOICE IDENTITY: {contract['voice_identity']}\n\n"
        f"BRAND THEME: {contract['brand_theme']}\n\n"
        f"ALLOWED TAGS ONLY (do not invent or use tags outside this list): {', '.join(contract['allowed_tags'])}\n\n"
        f"FORBIDDEN — never do any of this:\n{forbidden}\n\n"
        f"PACING RULES:\n{pacing}\n\n"
        f"INTENSITY: {mode['label']} — {mode['purpose']} Tag density: {mode['tag_density']}. "
        f"Favor these tags: {use_tags}. Reduce or avoid: {reduce_tags}. {mode['notes']}\n"
        + example_block
        + "\nRE-APPLY DIRECTION BEHAVIOR:\n"
        "1. Annotate the script with ElevenLabs v3 bracket tags from the allowed list above.\n"
        "2. Preserve the original wording exactly — do not rewrite, add, or remove words.\n"
        "3. Preserve paragraph order.\n"
        "4. Add tags only where they improve performance — not on every line.\n"
        "5. Use ellipses (…) where pacing needs a natural vocal break.\n"
        "6. Do not stack more than 2 tags at the start of a sentence unless necessary.\n"
        "Return ONLY the annotated script text — no commentary, no labels, no explanation."
    )


def _v2_contract_system(contract: dict, intensity_key: str) -> str:
    mode = contract["intensity_modes"][intensity_key]
    # v2 must never see literal bracket syntax in its own instructions — the model has no
    # concept of a "tag" to avoid, only literal text it would otherwise speak aloud. Drop
    # bullets that are purely about tag mechanics, and strip stray [bracket] mentions
    # (e.g. "don't overuse [excited]") from the rest so none leak into the prompt.
    debracket = lambda s: re.sub(r"\[([^\]]+)\]", r"\1", s)
    forbidden = "\n".join(
        f"- {debracket(f)}"
        for f in contract["forbidden"]
        if "tag" not in f.lower() and "bracket" not in f.lower()
    )
    caps_density = {"soft": "light — only at genuine emotional peaks", "default": "moderate", "strong": "moderate to high, but still controlled, not shouted"}[intensity_key]
    return (
        f"You are the Emotion Director for {contract['display_name']}, voiced by {contract['host']}, "
        "annotating an approved script for ElevenLabs v2 synthesis (no bracket tags — v2 speaks "
        "them aloud literally, so NONE may appear anywhere in the output).\n\n"
        f"VOICE IDENTITY: {contract['voice_identity']}\n\n"
        f"BRAND THEME: {contract['brand_theme']}\n\n"
        f"FORBIDDEN:\n{forbidden}\n\n"
        f"EMPHASIS: ALL CAPS on the single most important word/phrase per beat — the primary "
        f"emphasis mechanism for v2. Density for {mode['label']} intensity: {caps_density}.\n"
        "PACING: punctuation only — ellipses (…) for soft hesitation, em dashes (—) for hard "
        f"breaks, paragraph breaks for breathing room. {mode['notes']}\n\n"
        "RE-APPLY DIRECTION BEHAVIOR:\n"
        "1. Preserve the original wording exactly — do not rewrite, add, or remove words.\n"
        "2. Preserve paragraph order.\n"
        "3. Add ALL CAPS emphasis and punctuation-based pacing only where they improve performance.\n"
        "Return ONLY the annotated script text — no commentary, no labels, no explanation."
    )


def direct(
    script: str,
    brand: str,
    persona: Optional[str],
    intensity: Optional[str],
    stability_mode: Optional[str] = None,
    brand_examples: Optional[list[str]] = None,
    version: str = "v3",
) -> dict:
    version = (version or "v3").lower()
    if version not in ("v2", "v3"):
        version = "v3"

    contract = get_contract(brand)
    if contract:
        intensity_key = _intensity_key(intensity)
        system = (
            _v2_contract_system(contract, intensity_key)
            if version == "v2"
            else _v3_contract_system(contract, intensity_key)
        )
        default_stability = contract["recommended_stability"]
        tag_palette = ", ".join(contract["allowed_tags"])
    else:
        prof = EMOTION_PROFILES.get((brand or "").lower(), EMOTION_PROFILES["com"])
        b = _PRESETS["brands"].get((brand or "").lower(), {})
        brand_tone = b.get("tone_rules", "")
        system = _v2_system(prof, brand_tone, intensity) if version == "v2" else _v3_system(prof, brand_tone, intensity)
        default_stability = prof["stability"]
        tag_palette = prof["tags"]

    user = f"Script:\n{script}"

    if brand_examples:
        user += "\n\n## TAGGED SCRIPT MEMORY — previously directed scripts for this brand. Match this tagging density, style, and emotional register:\n"
        for i, ex in enumerate(brand_examples[:3], 1):
            user += f"\n--- Example {i} ---\n{ex.strip()}\n"
        user += "\n---"

    tagged = get_llm().complete(system=system, user=user, max_tokens=1500)
    mode = (stability_mode or default_stability).lower()
    if mode not in STABILITY_VALUE:
        mode = default_stability
    return {
        "tagged_script": tagged,
        "stability_mode": mode,
        "stability": STABILITY_VALUE.get(mode, 0.5),
        "audio_tag_palette": tag_palette,
        "version": version,
    }
