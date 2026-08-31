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

    # RSS mover wires. No credentials, so this source is always available --
    # and it is the one that actually covers the overnight/pre-market flow a
    # day trader works the open off. Each feed reports under its own source
    # name so axis-tekhen can score them separately; collapsing them to "rss"
    # would only ever tell us whether RSS-as-a-category is any good, which is
    # not an actionable answer.
    if settings.rss_movers_enabled:
        try:
            from . import rss_movers

            signals += rss_movers.scan_rss_movers(universe=tickers)
        except Exception as exc:
            # A broken wire must not cost us the sources that did work.
            logger.warning("[feed_watch] RSS source failed this pass: %s", exc)

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
