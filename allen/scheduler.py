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
