"""Usage & cost tracking — the data source for the "$" console dashboard. Every billable
call ALLEN makes to Anthropic/OpenAI/ElevenLabs funnels through log_llm/log_stt/log_tts
below (in-process). Other PIAAR services can report their own usage via POST /usage/log
so the dashboard can grow to cover the whole ecosystem, not just ALLEN.

Rates below are ESTIMATES from each provider's publicly listed pricing — they are for
relative footprint/trend awareness, not an invoice. Review periodically; a provider
pricing change won't automatically show up here."""

from . import db

# The PIAAR ecosystem's projects/repos — the dashboard's scaffold. A project with no
# usage yet still appears (at $0, "not yet reporting") so the shape is ready before the
# data is. Keys should match how each project identifies itself when it reports usage.
PIAAR_PROJECTS = [
    {"key": "rmg-ai", "label": "ALLEN · rmg-ai"},
    {"key": "rmg-creator-os", "label": "Master Atelier · rmg-creator-os"},
    {"key": "cappo-meridian", "label": "Cappo Meridian"},
    {"key": "axis-tekhen", "label": "Axis Tekhen"},
    {"key": "connection-circle", "label": "Connection Circle"},
    {"key": "hvnhavenry-com", "label": "HVN Havenry (Vale)"},
    {"key": "mytubescript", "label": "MyTubeScript"},
]

# $ per 1M tokens (input, output) — Anthropic, matched by substring against the model id.
_CLAUDE_RATES: dict[str, tuple[float, float]] = {
    "claude-opus": (15.00, 75.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (0.80, 4.00),
    "claude-fable": (3.00, 15.00),  # newer/unlisted tier — assumed Sonnet-equivalent until confirmed
}
_DEFAULT_CLAUDE_RATE = _CLAUDE_RATES["claude-sonnet"]

_WHISPER_RATE_PER_MINUTE = 0.006  # OpenAI whisper-1, $/minute

# $ per 1,000 characters — ElevenLabs, by model id. eleven_v3 is currently alpha/preview
# priced and may change; flash/turbo are the low-cost tiers this codebase doesn't use yet.
_ELEVENLABS_RATES: dict[str, float] = {
    "eleven_v3": 0.24,
    "eleven_multilingual_v2": 0.30,
    "eleven_flash_v2_5": 0.06,
    "eleven_turbo_v2_5": 0.10,
}
_DEFAULT_ELEVENLABS_RATE = _ELEVENLABS_RATES["eleven_multilingual_v2"]


def _claude_rate(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for prefix, rate in _CLAUDE_RATES.items():
        if prefix in m:
            return rate
    return _DEFAULT_CLAUDE_RATE


def log_llm(
    input_tokens: int,
    output_tokens: int,
    model: str,
    project: str = "rmg-ai",
    namespace: str = "",
    feature: str = "chat",
) -> None:
    in_rate, out_rate = _claude_rate(model)
    cost = (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
    db.insert_usage(
        project, namespace, feature, "anthropic", model,
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=round(cost, 6),
    )


def log_stt(
    duration_seconds: float,
    project: str = "rmg-ai",
    namespace: str = "",
    feature: str = "dictate",
) -> None:
    cost = (duration_seconds / 60.0) * _WHISPER_RATE_PER_MINUTE
    db.insert_usage(
        project, namespace, feature, "openai", "whisper-1",
        audio_seconds=round(duration_seconds, 2), cost_usd=round(cost, 6),
    )


def log_tts(
    characters: int,
    model: str,
    project: str = "rmg-ai",
    namespace: str = "",
    feature: str = "tts",
) -> None:
    rate = _ELEVENLABS_RATES.get(model or "", _DEFAULT_ELEVENLABS_RATE)
    cost = (characters / 1000.0) * rate
    db.insert_usage(
        project, namespace, feature, "elevenlabs", model,
        characters=characters, cost_usd=round(cost, 6),
    )


def dashboard(days: int = 30) -> dict:
    """Full scaffold for the '$' console panel: every PIAAR project (even $0 ones), each
    broken down by feature/provider/model, plus a daily trend series, top usage days,
    and a technology-account view (metered accounts cross-referenced against this same
    period's usage, flat-rate accounts shown by billing-cycle countdown instead)."""
    from . import tech_accounts

    days = max(1, min(int(days or 30), 365))
    rows = db.usage_summary(days=days)
    daily = db.usage_daily(days=days)
    accounts = tech_accounts.overview(rows)

    by_project: dict[str, list[dict]] = {}
    totals: dict[str, float] = {}
    for r in rows:
        by_project.setdefault(r["project"], []).append(r)
        totals[r["project"]] = totals.get(r["project"], 0.0) + float(r["cost_usd"] or 0)

    known_keys = {p["key"] for p in PIAAR_PROJECTS}
    projects = []
    for p in PIAAR_PROJECTS:
        projects.append({
            "key": p["key"],
            "label": p["label"],
            "total_cost_usd": round(totals.get(p["key"], 0.0), 4),
            "breakdown": by_project.get(p["key"], []),
            "reporting": p["key"] in by_project,
        })
    # A project reporting usage that isn't in the static registry yet (newly onboarded) — append too.
    for key, breakdown in by_project.items():
        if key not in known_keys:
            projects.append({
                "key": key, "label": key,
                "total_cost_usd": round(totals.get(key, 0.0), 4),
                "breakdown": breakdown, "reporting": True,
            })
    projects.sort(key=lambda p: p["total_cost_usd"], reverse=True)

    grand_total = round(sum(totals.values()), 4)
    top_days = sorted(daily, key=lambda d: float(d["cost_usd"] or 0), reverse=True)[:5]
    avg_daily = round(grand_total / days, 4) if days else 0.0

    return {
        "days": days,
        "grand_total_usd": grand_total,
        "avg_daily_usd": avg_daily,
        "projects": projects,
        "daily": daily,
        "top_days": top_days,
        "accounts": accounts,
        "rates_note": "Costs are ESTIMATES from static published rates, not live provider billing.",
    }
