"""Feed-watch job — periodic scan for "hot instrument" signals, pushed to
Thoth (axis-tekhen). Wired into the background scheduler (see scheduler.py);
mirrors the existing daily-report job's shape. Despite the "ALLIE" naming
carried over in config.py, this is a standalone, non-agentic scanner — it
does not call allie.py or involve any LLM reasoning."""

import logging

from . import db
from .config import settings

logger = logging.getLogger(__name__)


def run_feed_watch() -> None:
    """One feed-watch pass: scan configured tickers, push any hits to Thoth."""
    from . import tools_market_feed

    tickers = [t.strip().upper() for t in settings.feed_watch_tickers.split(",") if t.strip()]
    if not tickers:
        logger.info("[feed_watch] no tickers configured — skipping")
        return

    signals = tools_market_feed.scan_yfinance_movers(tickers)
    if settings.youtube_search_ready:
        signals += tools_market_feed.scan_youtube_finance_mentions(tickers)
    else:
        logger.info("[feed_watch] YouTube source not configured — yfinance only this pass")

    if not signals:
        logger.info("[feed_watch] scanned %d ticker(s), no hot signals this pass", len(tickers))
        return

    pushed_ok = tools_market_feed.push_signals_to_thoth(signals)
    logger.info(
        "[feed_watch] scanned %d ticker(s), found %d signal(s), pushed_ok=%s",
        len(tickers), len(signals), pushed_ok,
    )
    try:
        db.add_audit(
            "system", "allie", "feed_watch",
            f"tickers={tickers}",
            f"signals={[s['ticker'] for s in signals]} pushed_ok={pushed_ok}",
        )
    except Exception:
        logger.debug("[feed_watch] audit log skipped (db not configured)")
