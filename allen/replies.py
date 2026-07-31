"""Canonical reply catalog — ALLEN's standard user-facing messages in one place.

Every stock message ALLEN says when something goes wrong (a transient model overload,
a failed WhatsApp send, a dead-lettered reminder, an unreachable memory store) has a
stable key and a built-in default here. Rahm can override any of them at runtime via the
``canonical_replies`` table (edited through the ``/admin/replies`` endpoints), so the
wording is a source of truth he controls, not a string scattered across the code — while
the built-in defaults guarantee ALLEN is never mute even if the DB is unreachable.

Usage:  ``replies.get("llm_transient_failure")``  or  ``replies.for_exception(exc)``.
"""

import logging
from typing import Optional

from . import db

logger = logging.getLogger(__name__)

# Built-in defaults — the always-available fallback. Keep these calm, honest, and specific
# about what ALLEN will do next; they are what Rahm actually reads when something fails.
DEFAULTS: dict[str, str] = {
    "llm_transient_failure": (
        "I hit a brief snag reaching my reasoning engine — it looks like a temporary "
        "overload, not a real fault. I already retried a few times automatically. Give it "
        "a moment and send that again; if it keeps happening the model provider is likely "
        "having a wobble."
    ),
    "llm_failure_generic": (
        "Something went wrong on my end handling that, and it wasn't a transient blip I "
        "could retry through. I've logged it. Please try again, and if it persists let me "
        "know so it can be looked at."
    ),
    "whatsapp_error": "⚠️ ALLEN hit an error processing that message. I've logged it — try again in a moment.",
    "reminder_prefix": "⏰ {message}",
    "reminder_dead_letter": (
        "A reminder couldn't be delivered after several tries and has been set aside so it "
        "won't keep retrying: {message}"
    ),
    "db_unreachable": (
        "My memory store is briefly unreachable, so I'm working without full context right "
        "now. Try again shortly and I'll have everything back."
    ),
    "tool_error_generic": "That action didn't complete: {error}",
    "fault_logged": (
        "⚠️ I hit a fault on that and couldn't complete it, so I did NOT mark it done. I've written it to the "
        "error log for review — ask me to read the error log if you want the detail."
    ),
    "_unknown": "Something went wrong, and I've logged it.",
}


def _override(key: str) -> Optional[str]:
    """Rahm's DB override for a key, or None. Never raises — a DB blip just means defaults."""
    try:
        return db.get_reply_override(key)
    except Exception:
        return None


def get(key: str, **fmt) -> str:
    """Resolve a canonical reply: DB override → built-in default → generic fallback,
    then apply .format(**fmt). A bad template or missing field degrades to the raw text
    rather than raising, so an error message can never itself throw."""
    template = _override(key) or DEFAULTS.get(key) or DEFAULTS["_unknown"]
    if not fmt:
        return template
    try:
        return template.format(**fmt)
    except Exception:
        return template


# ---- exception classification ----

# Substrings that mark a retryable/transient upstream condition (overload, rate limit,
# 5xx, connection/timeout). Matched case-insensitively against the exception type name and
# message, so we don't need to hard-import the Anthropic SDK error classes here.
_TRANSIENT_MARKERS = (
    "overloaded", "rate limit", "ratelimit", "429", "529", "503", "502", "500",
    "timeout", "timed out", "temporarily", "connection", "unavailable",
    "serviceunavailable", "apiconnection", "apistatus", "internalserver",
)


def is_transient(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    if any(m in text for m in _TRANSIENT_MARKERS):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status >= 500 or status == 429


def for_exception(exc: BaseException) -> str:
    """The right canonical reply for a raised model/tool exception — a reassuring
    transient-overload notice when it looks retryable, else the generic failure message."""
    return get("llm_transient_failure") if is_transient(exc) else get("llm_failure_generic")


# ---- catalog view (for /admin/replies + future Sheet mirror) ----

def list_all() -> list[dict]:
    """Every canonical reply: its key, the effective template, the default, and whether
    Rahm has overridden it. Ordered for a stable, readable catalog view."""
    try:
        overrides = {r["key"]: r["template"] for r in db.list_reply_overrides()}
    except Exception:
        overrides = {}
    keys = sorted(k for k in set(DEFAULTS) | set(overrides) if k != "_unknown")
    out = []
    for k in keys:
        default = DEFAULTS.get(k, "")
        override = overrides.get(k)
        out.append(
            {
                "key": k,
                "effective": override or default,
                "default": default,
                "overridden": override is not None,
            }
        )
    return out
