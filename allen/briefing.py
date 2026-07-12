"""Rich morning briefing — weather, calendar, ClickUp deadline audit, ranked priorities,
news, and a motivational close, sent via WhatsApp alongside (not instead of) the existing
business-lane daily report in report.py. Weather and news are fetched deterministically in
Python (weather.py / news.py) and handed to the model as given facts — ALLEN's own tools
can't reliably produce either (no weather tool; web_fetch strips links news needs)."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_PROMPT = """\
Compose Rahm's rich morning briefing for {date}. Structure it EXACTLY as shown, with \
these exact section headers and emoji, in this order. No additions, no skipped sections \
— if a section has nothing to report, say so plainly rather than omitting the header.

## ☀️ Good morning
2-3 sentences: the day's overall shape (light/heavy, what's ahead) based on the actual \
calendar and task load you find below. Grounded and specific, not generic.

## 🌤️ Weather
Use ONLY this pre-fetched forecast — do not invent or alter any numbers:
{weather}

## 📅 Today's calendar (America/New_York)
Pull TODAY's real events from the calendar tool: time range, title, and location/attendees \
if present. List them in chronological order. If two events are close together, calculate \
the gap and flag it with a ⚠️ **Tight gap:** callout if realistic travel time (estimate — \
say so) could eat into it. If there are no events, say so.

## ✅ ClickUp deadline check
Pull real open tasks. Report:
- Whether every open task has a due date (or which ones don't).
- **Due in the next 2 days** — task name, exact due date, priority, assignee.
- **Overdue** — task name, priority, assignee, how many days overdue, and a recommended \
new due date with one-line reasoning.
End this section with: "I haven't changed anything in ClickUp — these are yours to confirm."
If ClickUp isn't reachable, say so plainly instead of inventing tasks.

## 🎯 Top 5 for today (ranked)
Exactly 5 items (fewer only if there's genuinely not enough real material), ranked by \
urgency and leverage, each with a one-line reason drawn from the calendar/ClickUp data above.

## 📰 News
Use ONLY these pre-fetched headlines — do not invent, add, or alter any. Present as a \
short bulleted list with the source name and a working markdown link:
{news}

## 🔒 Focus + motivation
One sentence naming the single highest-leverage thing to do today, then a short, warm, \
direct closing paragraph in your own voice — genuine, not generic motivational filler. \
Sign off "— ALLEN".

Close with a "Sources:" line listing every link used above (news links + the weather \
forecast link), markdown-formatted.

Formatting: markdown headers as shown, concise bullets, no invented data anywhere. \
Today is {date}."""


def build_daily_briefing() -> str:
    """Ask ALLEN's agentic layer to compile and return the rich morning briefing text."""
    from . import agent  # late import — avoids circular at module load time
    from . import news, weather

    today = datetime.now().strftime("%A, %B %-d, %Y")
    forecast = weather.todays_forecast()
    headlines = news.daily_digest()
    prompt = _PROMPT.format(date=today, weather=forecast, news=headlines)

    logger.info("[briefing] generating rich morning briefing for %s", today)
    try:
        return agent.respond_agentic(
            message=prompt,
            history=[],
            context="Generating the rich personal morning briefing. Be concrete and data-driven — "
            "pull real calendar and ClickUp data via your tools; never invent events, tasks, or dates.",
            namespace="atelier",
            max_tokens=3000,
        )
    except Exception as exc:
        logger.error("[briefing] generation failed: %s", exc)
        return f"*ALLEN Morning Briefing — {today}*\n\n⚠️ Briefing generation encountered an error. Check system logs."
