"""Market-feed scanner — scans social/momentum sources for "hot instrument" signals
and pushes them to Thoth (axis-tekhen's ingest endpoint). Runs as a standalone
scheduler job (see feed_watch.py); NOT part of ALLIE's agentic delegation chain
(allie.py) despite the historical "ALLIE" naming in config/docs — this is an
unrelated, unattended finance-signal pipeline with no LLM reasoning in the loop.

This is deliberately narrow: it detects a signal and hands it off. It does NOT
score trades, size positions, or talk to any broker — that decision-making lives
entirely on the axis-tekhen side (the gap scanner + Thoth's candidate board).

Two sources today:
  - yfinance (scan_yfinance_movers): no credentials needed, already usable.
  - YouTube Data API (scan_youtube_finance_mentions): requires
    settings.youtube_data_api_key; returns [] with a log warning if unset,
    rather than raising, since this runs unattended in a background job.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from .config import settings

logger = logging.getLogger(__name__)

_YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


def scan_yfinance_movers(
    tickers: List[str],
    news_lookback_hours: int = 6,
    min_news_count: int = 2,
    min_volume_ratio: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Flags a ticker as "hot" if it has an unusual burst of recent news, or
    today's volume is running well above its trailing average. Returns a list
    of Thoth-shaped signal dicts: {source, ticker, reason, confidence, detectedAt, evidence}.
    """
    import yfinance as yf  # imported lazily so this module has no hard dependency at collection time

    signals: List[Dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=news_lookback_hours)

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)

            news_items = t.news or []
            recent_news = []
            for item in news_items:
                ts = item.get("providerPublishTime")
                if ts and datetime.fromtimestamp(ts, tz=timezone.utc) >= cutoff:
                    recent_news.append(item)
            news_count = len(recent_news)

            hist = t.history(period="1mo", interval="1d")
            volume_ratio = 0.0
            if not hist.empty and "Volume" in hist.columns and len(hist) >= 2:
                today_volume = float(hist["Volume"].iloc[-1])
                avg_volume = float(hist["Volume"].iloc[:-1].mean())
                volume_ratio = (today_volume / avg_volume) if avg_volume > 0 else 0.0

            is_hot_news = news_count >= min_news_count
            is_hot_volume = volume_ratio >= min_volume_ratio
            if not (is_hot_news or is_hot_volume):
                continue

            reasons = []
            if is_hot_news:
                reasons.append(f"{news_count} news items in the last {news_lookback_hours}h")
            if is_hot_volume:
                reasons.append(f"volume {volume_ratio:.1f}x trailing 20-day average")

            confidence = min(1.0, 0.3 * news_count / max(min_news_count, 1) + 0.3 * min(volume_ratio, 5.0) / 5.0)

            signals.append(
                {
                    "source": "yfinance",
                    "ticker": ticker.upper(),
                    "reason": "; ".join(reasons),
                    "confidence": round(confidence, 3),
                    "detectedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "evidence": {"newsCount": news_count, "volumeRatio": round(volume_ratio, 3)},
                }
            )
        except Exception as exc:
            logger.warning("[feed_watch] yfinance scan failed for %s: %s", ticker, exc)

    return signals


def scan_youtube_finance_mentions(
    tickers: List[str],
    lookback_hours: int = 24,
    min_video_count: int = 2,
) -> List[Dict[str, Any]]:
    """
    Searches recent YouTube uploads mentioning "<ticker> stock" as a proxy for
    retail/finance-creator attention. Requires settings.youtube_data_api_key —
    returns [] (with a log warning) if it isn't configured, so the feed-watch
    job degrades gracefully rather than crashing when this source is unready.
    """
    if not settings.youtube_search_ready:
        logger.warning("[feed_watch] YouTube search skipped — youtube_data_api_key not configured")
        return []

    signals: List[Dict[str, Any]] = []
    published_after = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for ticker in tickers:
        try:
            resp = requests.get(
                _YOUTUBE_SEARCH_URL,
                params={
                    "part": "snippet",
                    "q": f"{ticker} stock",
                    "type": "video",
                    "order": "date",
                    "publishedAfter": published_after,
                    "maxResults": 25,
                    "key": settings.youtube_data_api_key,
                },
                timeout=15,
            )
            if not resp.ok:
                logger.warning("[feed_watch] YouTube search error for %s: %s %s", ticker, resp.status_code, resp.text[:200])
                continue

            items = resp.json().get("items", [])
            video_count = len(items)
            if video_count < min_video_count:
                continue

            confidence = min(1.0, video_count / 10.0)
            signals.append(
                {
                    "source": "youtube",
                    "ticker": ticker.upper(),
                    "reason": f"{video_count} finance videos mentioning \"{ticker} stock\" in the last {lookback_hours}h",
                    "confidence": round(confidence, 3),
                    "detectedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "evidence": {"videoCount": video_count},
                }
            )
        except Exception as exc:
            logger.warning("[feed_watch] YouTube scan failed for %s: %s", ticker, exc)

    return signals


def push_signals_to_thoth(signals: List[Dict[str, Any]]) -> bool:
    """POSTs a batch of signals to axis-tekhen's Thoth ingest endpoint. One signal per call
    (Thoth's /stocks/thoth/signals ingests a single signal per request)."""
    if not signals:
        return True
    if not (settings.thoth_ingest_url and settings.thoth_ingest_token):
        logger.warning("[feed_watch] Thoth ingest not configured — dropping %d signal(s)", len(signals))
        return False

    ok = True
    for signal in signals:
        try:
            resp = requests.post(
                settings.thoth_ingest_url,
                json=signal,
                headers={"X-Thoth-Token": settings.thoth_ingest_token},
                timeout=10,
            )
            if not resp.ok:
                logger.warning(
                    "[feed_watch] Thoth ingest rejected %s: %s %s",
                    signal.get("ticker"), resp.status_code, resp.text[:200],
                )
                ok = False
        except Exception as exc:
            logger.warning("[feed_watch] Thoth ingest failed for %s: %s", signal.get("ticker"), exc)
            ok = False
    return ok
