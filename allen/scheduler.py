"""Background scheduler — fires the daily WhatsApp morning brief."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _send_report() -> None:
    from . import report, whatsapp

    logger.info("[scheduler] firing daily report")
    try:
        body = report.build_daily_report()
        whatsapp.send_message(body)
    except Exception as exc:
        logger.error("[scheduler] daily report failed: %s", exc)


def start() -> None:
    """Start the cron scheduler. No-ops if WhatsApp is not configured."""
    global _scheduler

    if not settings.whatsapp_ready:
        logger.info("[scheduler] WhatsApp not configured — scheduler not started")
        return

    try:
        hour, minute = (int(p) for p in settings.daily_report_time.split(":", 1))
    except (ValueError, AttributeError):
        logger.error(
            "[scheduler] invalid DAILY_REPORT_TIME '%s' — expected HH:MM, scheduler not started",
            settings.daily_report_time,
        )
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_send_report, "cron", hour=hour, minute=minute, id="daily_report")
    _scheduler.start()
    logger.info(
        "[scheduler] daily report scheduled at %02d:%02d server local time",
        hour,
        minute,
    )


def stop() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[scheduler] stopped")
