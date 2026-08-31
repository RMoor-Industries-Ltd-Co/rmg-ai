"""Unit tests for the RSS mover scout.

The property that matters most is precision, not recall. A false ticker does
not merely add noise: axis-tekhen attributes every signal to the feed that
produced it and scores that feed on whether its picks outperformed. So a greedy
matcher turning "FDA APPROVES" into two tickers would corrupt the reliability
score of an otherwise good wire — the signal quality metric and the extractor
are coupled, and the extractor has to be the conservative one.

No network: feeds are parsed from fixture XML.
"""
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch

from allen import rss_movers


def feed_xml(items):
    """Minimal RSS document. `items` is [(title, description, published_dt)]."""
    parts = ["<rss><channel>"]
    for title, description, published in items:
        parts.append("<item>")
        parts.append(f"<title>{title}</title>")
        parts.append(f"<description>{description}</description>")
        if published:
            parts.append(f"<pubDate>{format_datetime(published)}</pubDate>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return "".join(parts)


class TickerExtractionTests(unittest.TestCase):
    def test_cashtag_is_extracted(self):
        self.assertEqual(rss_movers.extract_tickers("$AAPL jumps on earnings"), ["AAPL"])

    def test_exchange_qualified_is_extracted(self):
        self.assertIn("TSLA", rss_movers.extract_tickers("Tesla (NASDAQ: TSLA) rallies"))
        self.assertIn("GE", rss_movers.extract_tickers("GE update NYSE:GE today"))

    def test_bare_token_needs_the_known_universe(self):
        text = "AAPL climbs in premarket trading"
        # Without a universe there is nothing to validate against, so a bare
        # uppercase run is not trusted.
        self.assertEqual(rss_movers.extract_tickers(text), [])
        self.assertEqual(rss_movers.extract_tickers(text, universe=["AAPL"]), ["AAPL"])

    def test_common_acronyms_never_become_tickers(self):
        # The exact failure mode that would corrupt a feed's reliability score.
        text = "SEC and FDA respond as CEO discusses IPO and ETF flows"
        self.assertEqual(rss_movers.extract_tickers(text, universe=["SEC", "FDA", "CEO"]), [])

    def test_unknown_uppercase_word_is_not_a_ticker(self):
        self.assertEqual(
            rss_movers.extract_tickers("BREAKING MARKET UPDATE", universe=["AAPL"]), []
        )

    def test_duplicates_collapse(self):
        self.assertEqual(
            rss_movers.extract_tickers("$AAPL rises; Apple (NASDAQ: AAPL) leads"), ["AAPL"]
        )

    def test_dotted_class_shares_survive(self):
        self.assertIn("BRK.B", rss_movers.extract_tickers("$BRK.B in focus"))

    def test_empty_text_is_safe(self):
        self.assertEqual(rss_movers.extract_tickers(""), [])
        self.assertEqual(rss_movers.extract_tickers(None), [])


class ConfidenceTests(unittest.TestCase):
    def test_corroboration_across_feeds_raises_confidence(self):
        one = rss_movers._confidence(mentions=2, feeds=1, newest_age_hours=1)
        three = rss_movers._confidence(mentions=2, feeds=3, newest_age_hours=1)
        # Three wires running a story is a stronger claim than one.
        self.assertGreater(three, one)

    def test_staleness_lowers_confidence(self):
        fresh = rss_movers._confidence(mentions=2, feeds=2, newest_age_hours=0.5)
        stale = rss_movers._confidence(mentions=2, feeds=2, newest_age_hours=16)
        self.assertGreater(fresh, stale)

    def test_confidence_stays_in_range(self):
        for mentions, feeds, age in ((0, 0, 100), (99, 99, 0), (1, 1, 5)):
            value = rss_movers._confidence(mentions, feeds, age)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_never_claims_certainty(self):
        # No headline is ever proof; the cap says so.
        self.assertLess(rss_movers._confidence(999, 999, 0), 1.0)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def _scan(self, feeds_content, **kwargs):
        def fake_fetch(url, timeout=15):
            return feeds_content.get(url)

        with patch.object(rss_movers, "_fetch", side_effect=fake_fetch):
            return rss_movers.scan_rss_movers(
                feeds={k: k for k in feeds_content}, **kwargs
            )

    def test_each_feed_reports_under_its_own_source(self):
        # The point of the whole design: axis-tekhen scores feeds separately,
        # so they must arrive distinguishable.
        content = {
            "rss:alpha": feed_xml([("$AAPL surges", "", self.now)]),
            "rss:beta": feed_xml([("$AAPL climbs", "", self.now)]),
        }
        signals = self._scan(content, universe=["AAPL"])
        self.assertEqual({s["source"] for s in signals}, {"rss:alpha", "rss:beta"})

    def test_signal_carries_the_thoth_contract_fields(self):
        content = {"rss:alpha": feed_xml([("$TSLA gaps up", "premarket", self.now)])}
        signal = self._scan(content)[0]
        for field in ("source", "ticker", "reason", "confidence", "detectedAt"):
            self.assertIn(field, signal)
        self.assertEqual(signal["ticker"], "TSLA")

    def test_items_outside_the_lookback_are_ignored(self):
        old = self.now - timedelta(hours=48)
        content = {"rss:alpha": feed_xml([("$AAPL moved", "", old)])}
        self.assertEqual(self._scan(content, lookback_hours=18), [])

    def test_overnight_news_still_counts_for_the_open(self):
        # A story published after yesterday's close is exactly what the morning
        # rush trades off — the default window has to span it.
        overnight = self.now - timedelta(hours=12)
        content = {"rss:alpha": feed_xml([("$AAPL after-hours beat", "", overnight)])}
        self.assertEqual(len(self._scan(content, lookback_hours=18)), 1)

    def test_corroborated_ticker_scores_above_a_single_mention(self):
        both = {
            "rss:alpha": feed_xml([("$AAPL surges", "", self.now)]),
            "rss:beta": feed_xml([("$AAPL climbs", "", self.now)]),
        }
        alone = {"rss:alpha": feed_xml([("$MSFT drifts", "", self.now)])}
        corroborated = self._scan(both)[0]["confidence"]
        single = self._scan(alone)[0]["confidence"]
        self.assertGreater(corroborated, single)

    def test_a_broken_feed_does_not_lose_the_working_ones(self):
        content = {
            "rss:broken": "<<<not xml at all",
            "rss:good": feed_xml([("$NVDA jumps", "", self.now)]),
        }
        signals = self._scan(content)
        self.assertEqual([s["ticker"] for s in signals], ["NVDA"])

    def test_unreachable_feed_is_skipped_quietly(self):
        with patch.object(rss_movers, "_fetch", return_value=None):
            self.assertEqual(rss_movers.scan_rss_movers(feeds={"rss:down": "u"}), [])

    def test_no_tickers_yields_no_signals(self):
        content = {"rss:alpha": feed_xml([("Markets open mixed", "no symbols", self.now)])}
        self.assertEqual(self._scan(content), [])

    def test_results_are_ordered_by_confidence(self):
        content = {
            "rss:alpha": feed_xml([("$AAPL surges", "", self.now), ("$ZZZ drifts", "", self.now)]),
            "rss:beta": feed_xml([("$AAPL again", "", self.now)]),
        }
        signals = self._scan(content)
        self.assertEqual(
            [s["confidence"] for s in signals],
            sorted((s["confidence"] for s in signals), reverse=True),
        )


if __name__ == "__main__":
    unittest.main()
