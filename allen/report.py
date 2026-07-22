"""Daily business-lane brief — compiled by ALLEN's agentic layer.

DEPRECATED as a standalone scheduled job: its per-lane business content is now folded into
`briefing.py`'s single morning-brief generation (one agentic loop instead of two that
re-queried overlapping ClickUp/calendar data). `scheduler.py` no longer calls this. Kept
importable for ad-hoc/manual use; remove once nothing references `build_daily_report`."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_PROMPT = """\
Compose today's morning brief for Rahm. Structure it EXACTLY as shown — no additions, \
no skipped sections.

*ALLEN Morning Brief — {date}*

Pull live data from ClickUp, Notion, and your calendar for each section. \
Report in THIS exact priority order:

*1. Personal* — Rahm's personal calendar events today, health, home, errands, \
personal commitments due or coming up
*2. RMI* — RMoor Industries Ltd Co: open tasks, anything due or overdue, active priorities
*3. RMG* — RMG / Master Atelier / Creator OS: content pipeline, production status, \
anything blocked
*4. PIAAR* — PIAAR: current projects and priorities
*5. HVN* — HVN Haven: status and open items
*6. PLP* — PLP: current projects and priorities
*7. AMG* — Apex Meridian Group: operational status, open items

Formatting rules (strictly enforced):
- Under each header: 1–3 tight bullet points starting with -
- If a section has nothing to report: write exactly _Nothing flagged._
- Use *bold* for section headers, _italic_ only for status notes
- Keep the full message under 3800 characters
- Close with: _Reply to me with any questions or tasks._

Today is {date}."""


def build_daily_report() -> str:
    """Ask ALLEN's agentic layer to compile and return the morning brief text."""
    from . import agent  # late import — avoids circular at module load time

    today = datetime.now().strftime("%A, %B %-d, %Y")
    prompt = _PROMPT.format(date=today)

    logger.info("[report] generating daily brief for %s", today)
    try:
        return agent.respond_agentic(
            message=prompt,
            history=[],
            context="Generating the structured daily morning brief. Be concise and data-driven.",
            namespace="atelier",
            max_tokens=2000,
        )
    except Exception as exc:
        logger.error("[report] generation failed: %s", exc)
        return (
            f"*ALLEN Morning Brief — {today}*\n\n"
            "⚠️ Brief generation encountered an error. Check system logs."
        )
