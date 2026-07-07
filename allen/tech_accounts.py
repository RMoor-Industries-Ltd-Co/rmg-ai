"""Technology-account registry — which paid/metered services each PIAAR project relies
on, so the "$" console dashboard can show account-level status (not just per-call token
tallies): a metered account cross-references usage_log for real reporting/cost, a
flat-rate subscription shows a billing-cycle countdown from a renewal day YOU set (never
fabricated), and an account we haven't confirmed the billing model for yet is labeled
'unknown' rather than guessed.

Scope note: only accounts actually confirmed from each project's own config/docs are
listed here. Projects not yet audited (axis-tekhen, connection-circle, hvnhavenry-com)
are intentionally absent rather than guessed at — add their rows once verified."""

from . import db

# billing_model:
#   'metered' — usage_provider must match the `provider` column usage_log rows are
#               logged under (see usage.py's log_llm/log_stt/log_tts), so real usage
#               and cost roll up automatically.
#   'flat'    — subscription/seat billing with no per-call metering. Needs a renewal
#               day-of-month (1-28), set via set_cycle_day() — unset shows as such.
#   'unknown' — a real account this project uses, but its billing model isn't
#               confirmed yet. No status is claimed for these beyond the label.
TECH_ACCOUNTS = [
    # rmg-ai — confirmed via allen/config.py's *_ready properties
    {"key": "anthropic-rmg-ai", "label": "Anthropic (Claude API)", "project": "rmg-ai", "billing_model": "metered", "usage_provider": "anthropic"},
    {"key": "openai-rmg-ai", "label": "OpenAI (Whisper STT)", "project": "rmg-ai", "billing_model": "metered", "usage_provider": "openai"},
    {"key": "elevenlabs-rmg-ai", "label": "ElevenLabs (TTS)", "project": "rmg-ai", "billing_model": "metered", "usage_provider": "elevenlabs"},
    {"key": "clickup-rmg-ai", "label": "ClickUp", "project": "rmg-ai", "billing_model": "flat"},
    {"key": "notion-rmg-ai", "label": "Notion", "project": "rmg-ai", "billing_model": "flat"},
    {"key": "google-rmg-ai", "label": "Google (Drive/Calendar/Docs)", "project": "rmg-ai", "billing_model": "flat"},
    {"key": "twilio-rmg-ai", "label": "Twilio (WhatsApp bridge)", "project": "rmg-ai", "billing_model": "flat"},
    {"key": "github-app-rmg-ai", "label": "GitHub App (allen-piaar-control-bot)", "project": "rmg-ai", "billing_model": "free"},

    # rmg-creator-os / Master Atelier — named in rmg-piaar-system's production pipeline
    # doc; billing model not independently confirmed from that repo's own config yet.
    {"key": "elevenlabs-creator-os", "label": "ElevenLabs (voice profiles)", "project": "rmg-creator-os", "billing_model": "unknown"},
    {"key": "heygen-creator-os", "label": "HeyGen (A-Roll lip-sync)", "project": "rmg-creator-os", "billing_model": "unknown"},
    {"key": "higgsfield-creator-os", "label": "Higgsfield (B-Roll/scenes)", "project": "rmg-creator-os", "billing_model": "unknown"},
    {"key": "postiz-creator-os", "label": "Postiz (scheduling)", "project": "rmg-creator-os", "billing_model": "unknown"},

    # MyTubeScript — confirmed via its own CLAUDE.md
    {"key": "openai-mytubescript", "label": "OpenAI (Whisper fallback)", "project": "mytubescript", "billing_model": "metered", "usage_provider": "openai"},
    {"key": "google-mytubescript", "label": "Google Drive delivery", "project": "mytubescript", "billing_model": "flat"},

    # Cappo Meridian — confirmed via its own CLAUDE.md (separate AMG Anthropic key,
    # billed per-token but not yet reporting into this rmg-ai usage_log)
    {"key": "anthropic-cappo", "label": "Anthropic (shared AMG key)", "project": "cappo-meridian", "billing_model": "unknown"},
    {"key": "clickup-cappo", "label": "ClickUp", "project": "cappo-meridian", "billing_model": "flat"},
    {"key": "notion-cappo", "label": "Notion", "project": "cappo-meridian", "billing_model": "flat"},
    {"key": "google-cappo", "label": "Google Drive/Gmail", "project": "cappo-meridian", "billing_model": "flat"},
]


def _cycle_config_key(account_key: str) -> str:
    return f"tech_account_cycle_day:{account_key}"


def get_cycle_day(account_key: str) -> "int | None":
    val = db.get_config(_cycle_config_key(account_key))
    return int(val) if val else None


def set_cycle_day(account_key: str, day: int) -> None:
    if not 1 <= day <= 28:
        raise ValueError("cycle day must be between 1 and 28")
    db.set_config(_cycle_config_key(account_key), str(day))


def _error_config_key(project: str, usage_provider: str) -> str:
    return f"tech_account_last_error:{project}:{usage_provider}"


def record_error(project: str, usage_provider: str, message: str) -> None:
    """Called by a metered call site (speech.transcribe/synthesize, etc.) right before it
    raises, so a currently-blocked account (quota exhausted, revoked key, ...) shows up in
    the dashboard even though usage_log — which only records successful calls — still has
    stale 'reporting' history from before it broke."""
    import time

    try:
        db.set_config(
            _error_config_key(project, usage_provider),
            f"{time.time()}|{(message or '')[:300]}",
        )
    except Exception:
        pass  # error tracking must never break the caller's own error handling


def clear_error(project: str, usage_provider: str) -> None:
    """Called on the next successful call, so a resolved issue stops showing as broken."""
    try:
        db.set_config(_error_config_key(project, usage_provider), "")
    except Exception:
        pass


def _get_error(project: str, usage_provider: str) -> "dict | None":
    raw = db.get_config(_error_config_key(project, usage_provider))
    if not raw:
        return None
    at_str, _, message = raw.partition("|")
    try:
        at = float(at_str)
    except ValueError:
        return None
    return {"at": at, "message": message}


def _cycle_status(anchor_day: int) -> dict:
    """Days left / percent elapsed in the current renewal cycle, anchored to a
    day-of-month rather than always the calendar month's 1st."""
    from datetime import date

    today = date.today()

    def _safe(y: int, m: int) -> date:
        # clamp to the 28th so this never breaks on Feb/short months
        return date(y, m, min(anchor_day, 28))

    this_anchor = _safe(today.year, today.month)
    if today >= this_anchor:
        start = this_anchor
        end_month = today.month + 1 if today.month < 12 else 1
        end_year = today.year if today.month < 12 else today.year + 1
        end = _safe(end_year, end_month)
    else:
        start_month = today.month - 1 if today.month > 1 else 12
        start_year = today.year if today.month > 1 else today.year - 1
        start = _safe(start_year, start_month)
        end = this_anchor

    total = (end - start).days or 1
    days_left = max(0, (end - today).days)
    pct = min(100, max(0, round(((today - start).days / total) * 100)))
    return {"days_left": days_left, "pct": pct, "cycle_start": str(start), "cycle_end": str(end)}


def overview(usage_rows: list[dict]) -> list[dict]:
    """One entry per TECH_ACCOUNTS row: metered accounts cross-reference usage_rows
    (from usage.dashboard()'s period query) for real reporting/cost; flat accounts
    report their billing-cycle countdown (or 'not set' if no anchor day yet)."""
    by_project_provider: dict[tuple, float] = {}
    for r in usage_rows:
        by_project_provider[(r["project"], r["provider"])] = (
            by_project_provider.get((r["project"], r["provider"]), 0.0) + float(r["cost_usd"] or 0)
        )

    out = []
    for acc in TECH_ACCOUNTS:
        entry = {"key": acc["key"], "label": acc["label"], "project": acc["project"], "billing_model": acc["billing_model"]}
        if acc["billing_model"] == "metered":
            cost = by_project_provider.get((acc["project"], acc["usage_provider"]), 0.0)
            entry["reporting"] = cost > 0
            entry["period_cost_usd"] = round(cost, 4)
            err = _get_error(acc["project"], acc["usage_provider"])
            if err:
                entry["last_error"] = err
        elif acc["billing_model"] == "flat":
            anchor = get_cycle_day(acc["key"])
            if anchor:
                entry["cycle"] = _cycle_status(anchor)
                entry["cycle_anchor_day"] = anchor
            else:
                entry["cycle"] = None
        out.append(entry)
    return out
