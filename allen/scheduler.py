"""Background scheduler — fires the daily WhatsApp morning brief."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _send_report() -> None:
    from . import briefing, report, whatsapp

    logger.info("[scheduler] firing daily briefing + report")
    try:
        whatsapp.send_message(briefing.build_daily_briefing())
    except Exception as exc:
        logger.error("[scheduler] daily briefing failed: %s", exc)
    try:
        whatsapp.send_message(report.build_daily_report())
    except Exception as exc:
        logger.error("[scheduler] daily report failed: %s", exc)


def _run_feed_watch() -> None:
    from . import feed_watch

    logger.info("[scheduler] firing feed watch")
    try:
        feed_watch.run_feed_watch()
    except Exception as exc:
        logger.error("[scheduler] feed watch failed: %s", exc)


def _run_agent_rollup() -> None:
    from . import rollup

    logger.info("[scheduler] firing agent rollup")
    try:
        rollup.refresh()
    except Exception as exc:
        logger.error("[scheduler] agent rollup failed: %s", exc)


def _run_reminders() -> None:
    from . import db, whatsapp

    try:
        due = db.list_due_reminders()
    except Exception as exc:
        logger.error("[scheduler] reminder poll failed: %s", exc)
        return
    for r in due:
        try:
            whatsapp.send_message(f"⏰ {r['message']}")
            db.mark_reminder_sent(r["id"])
            logger.info("[scheduler] sent reminder %s", r["id"])
        except Exception as exc:
            logger.error("[scheduler] failed to send reminder %s: %s", r["id"], exc)


def _run_token_health() -> None:
    from . import token_health

    logger.info("[scheduler] firing token-health check")
    try:
        # Alert (WhatsApp) on any revoked/missing token so a broken OAuth
        # credential is caught before it silently breaks the morning brief.
        token_health.run(alert=True)
    except Exception as exc:
        logger.error("[scheduler] token health failed: %s", exc)


def start() -> None:
    """Start the cron scheduler. Each job independently no-ops if its own
    prerequisites aren't configured (WhatsApp for the daily report, Thoth/
    ticker config for feed watch) — one being unready doesn't block the other."""
    global _scheduler

    jobs_added = False
    _scheduler = BackgroundScheduler()

    if settings.whatsapp_ready:
        try:
            hour, minute = (int(p) for p in settings.daily_report_time.split(":", 1))
            _scheduler.add_job(_send_report, "cron", hour=hour, minute=minute, id="daily_report")
            jobs_added = True
            logger.info(
                "[scheduler] daily report scheduled at %02d:%02d server local time", hour, minute
            )
        except (ValueError, AttributeError):
            logger.error(
                "[scheduler] invalid DAILY_REPORT_TIME '%s' — expected HH:MM, daily report not scheduled",
                settings.daily_report_time,
            )
    else:
        logger.info("[scheduler] WhatsApp not configured — daily report not scheduled")

    # Token-health check runs 15 min before the morning brief so a revoked OAuth
    # credential is surfaced (and alerted) ahead of the brief that depends on it.
    from . import google_auth

    if settings.whatsapp_ready and google_auth.oauth_ready():
        try:
            hour, minute = (int(p) for p in settings.daily_report_time.split(":", 1))
            check_minute = (minute - 15) % 60
            check_hour = (hour - 1) % 24 if minute - 15 < 0 else hour
            _scheduler.add_job(
                _run_token_health, "cron", hour=check_hour, minute=check_minute, id="token_health"
            )
            jobs_added = True
            logger.info(
                "[scheduler] token-health check scheduled at %02d:%02d server local time",
                check_hour, check_minute,
            )
        except (ValueError, AttributeError):
            logger.error("[scheduler] invalid DAILY_REPORT_TIME — token-health check not scheduled")

    if settings.feed_watch_ready:
        _scheduler.add_job(
            _run_feed_watch, "interval", minutes=settings.feed_watch_interval_minutes, id="feed_watch"
        )
        jobs_added = True
        logger.info(
            "[scheduler] feed watch scheduled every %d minute(s)", settings.feed_watch_interval_minutes
        )
    else:
        logger.info("[scheduler] feed watch not configured (needs FEED_WATCH_ENABLED, tickers, Thoth URL/token)")

    if settings.agent_rollup_ready:
        _scheduler.add_job(_run_agent_rollup, "interval", hours=6, id="agent_rollup")
        jobs_added = True
        logger.info("[scheduler] agent rollup scheduled every 6 hours")
    else:
        logger.info("[scheduler] agent rollup not configured (needs CAPPO_REPORT_URL, ANPU_REVIEWS_URL, or THOTH_STATUS_URL)")

    if settings.whatsapp_ready and settings.database_url:
        _scheduler.add_job(_run_reminders, "interval", minutes=5, id="reminders")
        jobs_added = True
        logger.info("[scheduler] reminder poll scheduled every 5 minutes")
    else:
        logger.info("[scheduler] reminders not configured (needs WhatsApp + DATABASE_URL)")

    if not jobs_added:
        _scheduler = None
        logger.info("[scheduler] no jobs configured — scheduler not started")
        return

    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[scheduler] stopped")
