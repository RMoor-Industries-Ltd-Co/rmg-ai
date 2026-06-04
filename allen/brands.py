"""Brand voice — ALLEN's grounding. Composes the layered prompt system
(System -> Brand -> Persona) from presets.json, generated from the RMG Notion
'Brand Prompts' database. ALLEN-the-Agent writes; the Persona presets (incl. the
ALLEN/ALLIE *characters*, e.g. QTNA) are speakers the Agent voices."""

import json
from pathlib import Path
from typing import Optional

_PRESETS = json.loads((Path(__file__).parent / "presets.json").read_text(encoding="utf-8"))

_RULE_LABELS = {
    "tone_profile": "Tone Profile",
    "tone_rules": "Tone Rules",
    "hook_rules": "Hook Rules",
    "cta_rules": "CTA Rules",
    "structure_rules": "Structure Rules",
    "clip_logic_rules": "Clip Logic Rules",
    "routing_rules": "Routing Rules",
}


def is_known_brand(brand: str) -> bool:
    return brand.lower() in _PRESETS["brands"]


def list_brands() -> list[dict[str, str]]:
    return [{"key": k, "name": v.get("name", k)} for k, v in _PRESETS["brands"].items()]


def _rules(label: str, d: dict, keys: list[str]) -> str:
    parts = []
    for k in keys:
        v = d.get(k)
        if v:
            parts.append(f"{label} · {_RULE_LABELS.get(k, k)}:\n{v}")
    return "\n\n".join(parts)


def system_prompt(brand: str, persona: Optional[str], output_kind: str) -> str:
    sysd = _PRESETS["system"]
    b = _PRESETS["brands"].get((brand or "").lower())
    p = _PRESETS["personas"].get((persona or "").lower()) if persona else None

    blocks = [
        "You are ALLEN — the in-house AI scriptwriter (Agent) for the RMG Creator OS. "
        "Write production-ready, spoken-word scripts in the exact brand + persona voice "
        "defined below. Apply the layers in order: System (universal discipline) → Brand "
        "(lane) → Persona (speaker). Begin with a single line 'TITLE: <short title>', then "
        "the script. Output only the content — no labels, analysis, or meta.",
        "## SYSTEM (universal)\n" + sysd.get("system_block", ""),
        _rules("System", sysd, ["tone_rules", "hook_rules", "cta_rules", "structure_rules"]),
    ]

    if b:
        blocks.append(f"## BRAND — {b.get('name', brand)}\n" + b.get("system_block", ""))
        blocks.append(_rules("Brand", b, list(_RULE_LABELS)))
    else:
        blocks.append(f"## BRAND — {brand}\n(No preset on file; write clean, on-brand, professional.)")

    if p:
        blocks.append(f"## PERSONA — {p.get('name', persona)}\n" + (p.get("persona_rules") or ""))
        blocks.append(_rules("Persona", p, ["tone_rules", "hook_rules", "cta_rules"]))
    elif persona:
        blocks.append(f"## PERSONA — {persona}\n(Speak as this persona.)")

    blocks.append(
        f"## OUTPUT — a {output_kind}. Structure HOOK → BODY → CTA. Spoken-word natural "
        "(it will be voiced and lip-synced). No stage directions, emojis, or hashtags in the spoken lines."
    )
    return "\n\n".join(x for x in blocks if x and x.strip())
