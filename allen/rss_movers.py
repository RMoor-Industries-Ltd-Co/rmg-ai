"""RSS mover scout — reads pre-market/mover feeds and emits Thoth-shaped signals.

The third source behind feed_watch, alongside yfinance and YouTube. Day traders
work the opening rush off overnight and pre-market news flow, and that flow is
published as RSS by every financial wire — no API key, no rate-limit contract,
no vendor to sign up with.

**Each feed is its own signal source.** That is not cosmetic: axis-tekhen scores
feed sources independently on lift (did symbols this feed flagged outperform the
ones nobody flagged?), and collapsing them all to "rss" would make that
impossible to act on. You would learn that RSS as a category is mediocre, which
is useless, instead of that one wire earns its keep and another is noise.

Ticker extraction is deliberately conservative. Pulling symbols out of prose is a
named-entity problem, and a greedy matcher turns every "CEO SAID" and "IPO NEWS"
into a signal — false positives here do not merely add noise, they poison the
reliability score of the feed that produced them. So three high-precision
patterns only:

  * cashtags -- ``$AAPL``
  * exchange-qualified -- ``(NASDAQ: AAPL)``, ``NYSE:TSLA``
  * bare uppercase tokens, but ONLY when they match the configured watch
    universe, so an unknown three-letter word can never become a ticker

Confidence is derived, never invented: corroboration across distinct feeds plus
recency. A symbol named by three wires in the last hour is a stronger claim than
one mentioned once yesterday, and the number says so rather than being a
hard-coded 0.7.

Stdlib-only XML parsing, matching news.py — no feedparser dependency.
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_USER_AGENT = "ALLEN-RMG/1.0 (market-feed, contact: rahm@rmasters.group)"

# Mover/pre-market oriented wires. Keyed by the name that becomes the signal's
# `source`, so axis-tekhen scores each one separately and you can drop the ones
# that never earn their weight.
DEFAULT_FEEDS: Dict[str, str] = {
    "rss:yahoo-market": "https://finance.yahoo.com/news/rssindex",
    "rss:gnews-premarket": (
        "https://news.google.com/rss/search?q=premarket+movers&hl=en-US&gl=US&ceid=US:en"
    ),
    "rss:gnews-gappers": (
        "https://news.google.com/rss/search?q=stock+gaps+up+OR+gaps+down+premarket"
        "&hl=en-US&gl=US&ceid=US:en"
    ),
    "rss:gnews-earnings": (
        "https://news.google.com/rss/search?q=earnings+beat+OR+earnings+miss"
        "&hl=en-US&gl=US&ceid=US:en"
    ),
    "rss:nasdaq-original": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
}

# $AAPL / $BRK.B
_CASHTAG = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b")
# (NASDAQ: AAPL) / NYSE:TSLA / AMEX: XYZ
_EXCHANGE = re.compile(r"\b(?:NASDAQ|NYSE|AMEX|NYSEARCA|OTC)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b")
# Bare uppercase run, only trusted against the known universe.
_BARE = re.compile(r"\b([A-Z]{2,5})\b")

# Tokens that look like tickers and are not. Only consulted for the bare-token
# path; a cashtag is an explicit claim and is trusted as written.
_STOPWORDS = frozenset({
    "CEO", "CFO", "COO", "CTO", "IPO", "ETF", "SEC", "FDA", "FTC", "DOJ", "IRS",
    "GDP", "CPI", "PPI", "FOMC", "USA", "US", "UK", "EU", "AI", "EV", "API",
    "NEWS", "STOCK", "STOCKS", "MARKET", "BUY", "SELL", "HOLD", "UP", "DOWN",
    "Q1", "Q2", "Q3", "Q4", "YOY", "EPS", "PE", "ATH", "PM", "AM", "ET", "EST",
    "NYSE", "NASDAQ", "AMEX", "OTC", "WSJ", "CNBC", "AP", "PR", "LLC", "INC",
})


def _fetch(url: str, timeout: int = 15) -> Optional[str]:
    """Feed text, or None. A broken wire must never break the pass."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        logger.warning("[rss_movers] feed fetch failed for %s: %s", url, exc)
        return None


def _published(item: ET.Element) -> Optional[datetime]:
    for tag in ("pubDate", "published", "updated"):
        raw = item.findtext(tag)
        if not raw:
            continue
        try:
            stamp = parsedate_to_datetime(raw)
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            try:
                stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def extract_tickers(text: str, universe: Optional[Iterable[str]] = None) -> List[str]:
    """
    Tickers named in `text`, high-precision first.

    Cashtags and exchange-qualified symbols are explicit claims and are taken as
    written. Bare uppercase tokens are only accepted when they appear in
    `universe` — without that guard "FDA APPROVES" yields two tickers, and those
    false positives would be attributed to the feed that published the headline,
    corrupting exactly the score this feeds.
    """
    if not text:
        return []
    found: List[str] = []
    for pattern in (_CASHTAG, _EXCHANGE):
        found.extend(pattern.findall(text))

    known = {t.strip().upper() for t in (universe or []) if t and t.strip()}
    if known:
        for token in _BARE.findall(text):
            if token in known and token not in _STOPWORDS:
                found.append(token)

    seen, out = set(), []
    for symbol in found:
        symbol = symbol.upper()
        if symbol in _STOPWORDS or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _confidence(mentions: int, feeds: int, newest_age_hours: float) -> float:
    """
    Derived, not invented.

    Corroboration across distinct wires is the strongest component -- one outlet
    running a story is a story, three running it is a move. Recency decays over
    the overnight window a pre-market signal is useful in. Capped below 1.0
    because no RSS headline is ever certainty, and axis-tekhen's calibration
    check will tell you soon enough whether these numbers track reality.
    """
    corroboration = min(feeds / 3.0, 1.0)
    volume = min(mentions / 5.0, 1.0)
    freshness = max(0.0, 1.0 - (newest_age_hours / 18.0))
    score = 0.5 * corroboration + 0.2 * volume + 0.3 * freshness
    return round(min(0.95, max(0.05, score)), 3)


def scan_rss_movers(
    universe: Optional[Iterable[str]] = None,
    feeds: Optional[Dict[str, str]] = None,
    lookback_hours: int = 18,
    min_mentions: int = 1,
) -> List[Dict[str, Any]]:
    """
    One RSS pass. Returns Thoth-shaped signals, one per ticker per source.

    The default lookback spans an overnight so a story published after
    yesterday's close still counts toward this morning's open — which is the
    window the whole exercise exists to cover.
    """
    feeds = feeds or DEFAULT_FEEDS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # ticker -> source -> {mentions, newest, headlines}
    hits: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for source, url in feeds.items():
        raw = _fetch(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            logger.warning("[rss_movers] could not parse %s: %s", source, exc)
            continue

        for item in root.findall(".//item") + root.findall(
            ".//{http://www.w3.org/2005/Atom}entry"
        ):
            published = _published(item)
            if published and published < cutoff:
                continue
            title = (item.findtext("title") or "").strip()
            summary = (item.findtext("description") or "").strip()
            for ticker in extract_tickers(f"{title} {summary}", universe=universe):
                bucket = hits.setdefault(ticker, {}).setdefault(
                    source, {"mentions": 0, "newest": published, "headlines": []}
                )
                bucket["mentions"] += 1
                if published and (bucket["newest"] is None or published > bucket["newest"]):
                    bucket["newest"] = published
                if title and len(bucket["headlines"]) < 3:
                    bucket["headlines"].append(title)

    now = datetime.now(timezone.utc)
    signals: List[Dict[str, Any]] = []
    for ticker, by_source in hits.items():
        feed_count = len(by_source)
        for source, data in by_source.items():
            if data["mentions"] < min_mentions:
                continue
            newest = data["newest"] or now
            age_hours = max(0.0, (now - newest).total_seconds() / 3600.0)
            headline = data["headlines"][0] if data["headlines"] else "mentioned in market RSS"
            signals.append({
                "source": source,
                "ticker": ticker,
                "reason": (
                    f"{data['mentions']} mention(s) across {feed_count} feed(s) "
                    f"in the last {lookback_hours}h — {headline[:160]}"
                ),
                "confidence": _confidence(data["mentions"], feed_count, age_hours),
                "detectedAt": newest.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "evidence": {
                    "feed": source,
                    "mentions": data["mentions"],
                    "corroboratingFeeds": feed_count,
                    "ageHours": round(age_hours, 2),
                    "headlines": data["headlines"],
                },
            })

    signals.sort(key=lambda s: s["confidence"], reverse=True)
    logger.info(
        "[rss_movers] %d feed(s) → %d ticker(s) → %d signal(s)",
        len(feeds), len(hits), len(signals),
    )
    return signals
