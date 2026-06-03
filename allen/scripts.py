"""Brand-voice script generation."""

from .brands import system_prompt
from .llm import get_llm
from .models import DraftRequest


def _split_title(raw: str) -> tuple[str, str]:
    """Pull the leading 'TITLE: ...' line off the generated text."""
    lines = raw.splitlines()
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("TITLE:"):
            title = stripped.split(":", 1)[1].strip()
            body_start = i + 1
        break
    script = "\n".join(lines[body_start:]).strip()
    if not title:
        title = (script[:48] + "…") if len(script) > 48 else (script or "Untitled")
    return title, script


def generate_script(req: DraftRequest) -> tuple[str, str, str]:
    """Return (title, script, model_id)."""
    llm = get_llm()
    system = system_prompt(req.brand, req.persona, req.output_kind)

    user = f"Topic / brief:\n{req.topic}\n"
    if req.allie_context:
        user += (
            "\nGrounding context (from ALLIE — use for accuracy, do not quote verbatim):\n"
            f"{req.allie_context}\n"
        )
    user += "\nWrite the script now."

    raw = llm.complete(system=system, user=user, max_tokens=1500)
    title, script = _split_title(raw)
    from .config import settings

    return title, script, settings.anthropic_model
