"""News headlines for the morning briefing — read directly from RSS feeds. tools_web's
web_fetch strips ALL html tags (including <a href>), so it can never recover a real
article link; RSS gives structured title/link/source without needing a search API or key."""

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = {
    "general": "https://feeds.npr.org/1001/rss.xml",
    "ai": "https://news.google.com/rss/search?q=artificial%20intelligence&hl=en-US&gl=US&ceid=US:en",
    "finance": "https://news.google.com/rss/search?q=stock%20market&hl=en-US&gl=US&ceid=US:en",
}

LABELS = {"general": "General", "ai": "AI / Tech", "finance": "Finance / Markets"}


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ALLEN-RMG/1.0 (news, contact: rahm@rmasters.group)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def headlines(category: str, limit: int = 2) -> list[dict]:
    """[{title, link, source}] for the top `limit` items in a feed. Empty list on any
    failure — a broken feed should never break the whole briefing."""
    url = FEEDS.get(category)
    if not url:
        return []
    try:
        root = ET.fromstring(_fetch(url))
        out = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            source_el = item.find("source")
            source = (source_el.text or "").strip() if source_el is not None else ""
            if title and link:
                out.append({"title": title, "link": link, "source": source or LABELS.get(category, category)})
        return out
    except (urllib.error.URLError, ET.ParseError):
        return []


def daily_digest(limit_per_category: int = 2) -> str:
    """Formatted text block with real headlines + real links, grouped by category —
    handed to the briefing prompt as given facts so the model never has to invent a URL."""
    lines = []
    for cat, label in LABELS.items():
        items = headlines(cat, limit=limit_per_category)
        if not items:
            continue
        lines.append(f"{label}:")
        for h in items:
            lines.append(f"- {h['title']} ({h['source']}) — {h['link']}")
    return "\n".join(lines) if lines else "(no headlines available today)"
