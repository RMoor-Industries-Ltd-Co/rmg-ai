"""Brand performance contracts — the detailed "law" governing how the Emotion Director
(allen/emotion.py) annotates a brand's approved scripts with ElevenLabs v3 bracket tags,
pacing markers, and emphasis. A brand WITHOUT an entry here falls back to emotion.py's
older, lighter-weight EMOTION_PROFILES — this only needs to hold brands that have an
actual written contract. Canonical spec doc: rmg-piaar-system/contracts/
22-brand-voice-performance-contracts.md. Start with COM only, per the brand owner."""

BRAND_CONTRACTS: dict[str, dict] = {
    "com": {
        "brand_key": "COM",
        "display_name": "COM — Conversations of Mastery",
        "host": "Coach Rahm",
        "voice_identity": (
            "Coach Rahm is calm, grounded, direct, reflective, masculine, practical, and "
            "emotionally intelligent. He sounds like a trusted coach having a serious "
            "conversation with men who need clarity, discipline, accountability, and "
            "movement. He should challenge without yelling, teach without sounding "
            "academic, and inspire without sounding fake-motivational."
        ),
        "brand_theme": (
            "Conversations of Mastery is about men's development, discipline, "
            "responsibility, emotional clarity, leadership, relationships, purpose, "
            "business, and legacy. The voice should feel like a coaching conversation "
            "with sermon-level weight, but still human, simple, and relatable."
        ),
        "default_tags": [
            "[calm]", "[confident]", "[focused]", "[measured]", "[reflective]", "[serious]",
            "[firm]", "[teacher]", "[challenge]", "[encouraging]", "[softly]", "[emphasize]",
            "[pause]", "[short pause]", "[long pause]", "[beat]", "[leans in]", "[drawn out]",
        ],
        "allowed_tags": [
            "[calm]", "[confident]", "[focused]", "[measured]", "[reflective]", "[serious]",
            "[firm]", "[teacher]", "[challenge]", "[encouraging]", "[softly]", "[warm]",
            "[thoughtful]", "[with conviction]", "[with authority]", "[with restraint]",
            "[emphasize]", "[emphatic]", "[key point]", "[important]", "[leans in]", "[quiet]",
            "[soft smile]", "[pause]", "[short pause]", "[long pause]", "[beat]", "[drawn out]",
            "[takes a breath]", "[exhales]",
        ],
        "forbidden": [
            "Do not make Coach Rahm sound goofy.",
            "Do not overuse [excited] for COM.",
            "Do not make the delivery frantic.",
            "Do not use too many tags in one sentence.",
            "Do not rewrite the user's words unless explicitly requested.",
            "Do not turn the script into Master Rahm, Rah Rah, or VLOG.",
            "Do not add stage directions that imply visuals, gestures, or actions unless "
            "they affect voice delivery naturally.",
            "Avoid bracket tag clutter.",
        ],
        "pacing_rules": [
            "Use ellipses for natural tension and thought breaks.",
            "Use [pause] after major insights.",
            "Use [short pause] between setup and punchline.",
            "Use [beat] for rhythmic contrast in short repeated lines.",
            "Use [drawn out] only for words or phrases that should stretch emotionally.",
            "Use [leans in] before intimate challenges or serious questions.",
            "Use [firm] or [challenge] before direct accountability lines.",
            "Use [softly] for personal, vulnerable, or reflective lines.",
            "Use [emphasize] before central thesis statements.",
            "Do not stack more than 2 tags at the start of a sentence unless necessary.",
        ],
        "recommended_stability": "natural",
        "intensity_modes": {
            "default": {
                "label": "Default",
                "purpose": "Balanced Coach Rahm delivery.",
                "tag_density": "moderate",
                "use": ["[pause]", "[short pause]", "[firm]", "[reflective]", "[teacher]", "[emphasize]", "[challenge]"],
                "notes": (
                    "Apply tags at the beginning of important sentences and before major "
                    "transitions. Do not tag every line."
                ),
            },
            "soft": {
                "label": "Soft",
                "purpose": "Reflective, warm, more personal.",
                "tag_density": "light to moderate",
                "use": ["[calm]", "[softly]", "[reflective]", "[thoughtful]", "[warm]", "[pause]", "[short pause]"],
                "reduce": ["[firm]", "[challenge]", "[emphatic]"],
                "notes": "Best for vulnerable, relationship, healing, legacy, or reflective scripts.",
            },
            "strong": {
                "label": "Strong",
                "purpose": "Direct, commanding, high-impact coaching.",
                "tag_density": "moderate to high",
                "use": [
                    "[firm]", "[challenge]", "[with conviction]", "[emphasize]", "[serious]",
                    "[leans in]", "[beat]", "[pause]", "[drawn out]",
                ],
                "notes": (
                    "Increase contrast between short punches and reflective pauses. Best for "
                    "accountability, discipline, hard truth, masculine development, and "
                    "self-correction scripts. Strong should still sound controlled, not angry."
                ),
            },
        },
        # Few-shot example (Strong mode) from the brand owner — anchors tagging density/style.
        "example": {
            "intensity": "strong",
            "text": (
                "[confident] AI is literally rewriting its own code... [short pause] to get better.\n\n"
                "[firm] And YOU... [emphasize] can't EVEN... [short pause] rewrite your morning routine.\n\n"
                "[pause][serious] That's not a technology story.\n"
                "[reflective] That's a mirror...\n"
                "[challenge] and most people won't look into it.\n\n"
                "[teacher][measured] There's a concept in AI development called recursive self-improvement.\n\n"
                "[explaining] The machine identifies its own weaknesses...\n"
                "[pause]\n"
                "...adjusts its own architecture...\n"
                "[pause]\n"
                "...and comes back [emphasize] sharper than it was.\n\n"
                "[firm] That's not a capability problem.\n"
                "[pause]\n"
                "[drawn out][emphasize] That's an honesty problem.\n\n"
                "[leans in][quiet] So here's the only thing worth asking yourself right now.\n\n"
                "[pause][challenge] What part of your own code needs to be rewritten... and "
                "what's the real reason you haven't touched it?\n\n"
                "[focused] If that question bothers you... [short pause] good.\n"
                "[drawn out] That's where the work is."
            ),
        },
    },
}


def get_contract(brand: str) -> "dict | None":
    return BRAND_CONTRACTS.get((brand or "").lower())
