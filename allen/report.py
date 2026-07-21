"""Daily morning brief — compiled by ALLEN's agentic layer and sent via WhatsApp."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_PROMPT = """\
Compose today's morning brief for Rahm. Structure it EXACTLY as shown — no additions, \
no skipped sections.

*ALLEN Morning Brief — {date}*

Gather live data for each section from the CORRECT source (noted per section). Personal \
items come from your own calendar + the PERSONAL SYSTEMS ClickUp space directly. For every \
BUSINESS section (RMI, RMG, PIAAR, HVN, AMG) delegate to ALLIE for the live ClickUp/Notion \
data — she owns the business worlds. Report in THIS exact priority order:

*1. Personal* — your calendar (rahmind.consulting@rmoorind.com) events today, plus the \
PERSONAL SYSTEMS space: health, home, errands, personal commitments due or coming up
*2. RMI* — RMI - Company Headquarters ADMIN space: open tasks, anything due or overdue, \
active priorities
*3. RMG* — RMG - CREATOR SPACE (Master Atelier / Creator OS): content pipeline, production \
status, anything blocked
*4. PIAAR* — PIAAR lives INSIDE the RMG - CREATOR SPACE (not its own space): current PIAAR \
projects and priorities from there
*5. HVN* — HVN Haven is owned & operated by AMG: pull its status and open items from the \
AMG space (delegate to ALLIE → Cappo)
*6. PLP* — PLP is an occasional contractor (Angel's); it has NO dedicated ClickUp space. \
Surface PLP items ONLY if any appear in the PERSONAL SYSTEMS space today; otherwise report \
_Nothing flagged._ — do not fabricate a project
*7. AMG* — Apex Meridian Group is managed by QUARTERS: read the Q1–Q4 folders in the AMG \
space and report the current quarter's operational status and open items (delegate to \
ALLIE → Cappo)

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
