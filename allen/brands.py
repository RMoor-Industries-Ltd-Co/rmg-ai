"""Brand voice profiles — the per-brand 'voice' ALLEN writes in.
Mirrors the canonical brand model (RMG Creator OS contract 12). Encoded as prompt
fragments now; can grow into retrieval/fine-tuning later."""

from typing import Optional

BRAND_VOICES: dict[str, dict[str, str]] = {
    "com": {
        "name": "Conversations of Mastery (COM)",
        "voice": "Reflective, masterful, and depth-oriented. Teaches one principle clearly per piece. "
        "Confident and grounded; favors story-led framing and reframes; speaks to people who want mastery, not hacks.",
    },
    "vlog": {
        "name": "Virtual Legacy of Greatness (VLOG)",
        "voice": "Clean, educational, technically clear. Restrained and credible; legacy- and craft-minded. "
        "Explains the 'how' with precision and a forward-looking, build-something tone.",
    },
    "busy-mf": {
        "name": "Business Monday thru Friday (BU$Y_MF)",
        "voice": "High-energy, punchy, practical commerce voice for TikTok. Fast hooks, bold rhythm, "
        "drives action toward the stores (ORR, Master Rahm, VLOG). Confident hustle, never cheesy.",
    },
    "orr": {
        "name": "Our Royal Reservations (ORR / R+R)",
        "voice": "Smooth, aspirational travel & lifestyle. Warm, hospitable, sensory; invites the audience "
        "into elevated experiences. Refined but accessible.",
    },
    "mstr-rahm": {
        "name": "Master Rahm",
        "voice": "Conscious, philosophical, and assertive. The flagship master persona — speaks with earned "
        "authority and depth; bold emphasis and rhythmic pacing.",
    },
    "trc": {
        "name": "The Rahm Council (TRC)",
        "voice": "Cultural commentary with gravitas. Convening, perspective-rich, and discerning; frames "
        "debate and principle. Measured, intelligent, a touch provocative.",
    },
    "tgl": {
        "name": "The Afterlife (Godfather) Lounge (TGL / TAL)",
        "voice": "Late-night lounge cool — smooth, cinematic, a little mythic. Confident, unhurried, "
        "atmospheric storytelling with a Godfather-esque edge.",
    },
}


def is_known_brand(brand: str) -> bool:
    return brand.lower() in BRAND_VOICES


def list_brands() -> list[dict[str, str]]:
    return [{"key": k, "name": v["name"], "voice": v["voice"]} for k, v in BRAND_VOICES.items()]


def system_prompt(brand: str, persona: Optional[str], output_kind: str) -> str:
    b = BRAND_VOICES.get(brand.lower())
    if not b:
        brand_block = f"Brand: {brand} (no profile on file — write in a clean, professional brand voice)."
    else:
        brand_block = f"Brand: {b['name']}\nBrand voice: {b['voice']}"

    persona_block = f"\nSpeaking persona: {persona}." if persona else ""

    return (
        "You are ALLEN, the in-house scriptwriter for the RMG Creator OS. You write "
        "short-form, social-ready scripts in a specific brand voice for a talking-head "
        "avatar to perform.\n\n"
        f"{brand_block}{persona_block}\n\n"
        f"Deliverable: a {output_kind} script.\n"
        "Structure every script as HOOK → BODY → CTA. Keep it tight and spoken-word "
        "natural (it will be voiced and lip-synced). Avoid stage directions, emojis, and "
        "hashtags in the spoken lines. Start with a single line: 'TITLE: <a short title>'. "
        "Then the script. Honor the brand voice precisely."
    )
