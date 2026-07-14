"""ALLEN's executive rollup — a scheduled job (allen/scheduler.py) that pulls each PIAAR
domain agent's already-cached report (Cappo, Anpu, Thoth) and synthesizes a concise executive
summary, storing both the raw per-source pulls and the synthesis in agent_reports (allen/db.py)
so it's instant to read when Rahm asks ALLEN "what's going on" — matching the "ready to go"
reporting requirement, never live-computed at request time. Each domain agent is autonomous
and independent; this job only PULLS what they've already produced, it never triggers them to
do work (matches rmg-piaar-system's reporting law: centralized through ALLIE, not peer-to-peer)."""

import logging

from . import db, tools_anpu, tools_cappo, tools_thoth
from .config import settings

logger = logging.getLogger(__name__)

_SOURCES = [
    ("cappo", lambda: tools_cappo.get_report(), lambda: settings.cappo_report_ready),
    ("anpu", lambda: tools_anpu.handle("anpu_get_reviews", {}), tools_anpu.ready),
    ("thoth", lambda: tools_thoth.handle("thoth_get_status", {}), tools_thoth.ready),
]

_SYNTHESIS_PROMPT = """\
Rahm's PIAAR domain agents just reported their latest status. Write a tight executive rollup \
for ALLEN to hand Rahm on request — 3-5 sentences max, plain language, only real findings \
below. If a domain has nothing notable, say so briefly rather than padding. Never invent \
anything not present in the reports.

{reports}"""


def refresh() -> None:
    """Pull each configured domain's cached report, store it, and synthesize a rollup. Every
    step is independently try/excepted — one domain failing to pull never blocks the others
    or the synthesis of what did come through."""
    pulled = {}
    for source, fetch, is_ready in _SOURCES:
        if not is_ready():
            continue
        try:
            text = fetch()
            db.set_agent_report(source, text, ok=True)
            pulled[source] = text
        except Exception as exc:
            logger.error("[rollup] pulling %s failed: %s", source, exc)
            db.set_agent_report(source, f"(pull failed: {exc})", ok=False)

    if not pulled:
        logger.info("[rollup] no domain sources configured — nothing to synthesize")
        return

    reports_block = "\n\n".join(f"{k.upper()}:\n{v}" for k, v in pulled.items())
    try:
        from .llm import get_llm

        summary = get_llm().complete(
            system="You write concise, factual executive summaries. Never invent data.",
            user=_SYNTHESIS_PROMPT.format(reports=reports_block),
            max_tokens=400,
            feature="agent_rollup",
        )
        db.set_agent_report("allen_rollup", summary, ok=True)
        logger.info("[rollup] synthesized executive rollup from %d source(s)", len(pulled))
    except Exception as exc:
        logger.error("[rollup] synthesis failed: %s", exc)
