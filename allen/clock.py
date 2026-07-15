"""Current-time context for ALLEN/ALLIE's prompts. Without this, neither can correctly
compute a relative time ("remind me in 2 hours", "is that meeting today?") — chat.py's
system prompt has always claimed "if the current date/time is in your context, use it,"
but nothing ever actually supplied it until this module existed."""

from datetime import datetime
from zoneinfo import ZoneInfo

# Matches tools_calendar.py's _TZ -- Rahm's home timezone, so "today"/"in 2 hours" means
# the same thing to ALLEN as it does on his actual calendar.
_TZ = ZoneInfo("America/New_York")


def now_line() -> str:
    now = datetime.now(_TZ)
    return f"CURRENT DATE/TIME: {now.strftime('%A, %B %-d, %Y, %-I:%M %p %Z')} (ISO: {now.isoformat()})."
