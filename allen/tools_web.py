"""Web fetch tool — lets ALLEN retrieve live web content for research."""

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

TOOLS = [
    {
        "name": "web_fetch",
        "description": (
            "Fetch a public web page and return its visible text content (up to ~5 000 characters). "
            "Use for live research: company websites, news articles, pricing pages, LinkedIn profiles, "
            "Wikipedia articles, etc. Do not use for login-protected pages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to fetch (https://...)"}
            },
            "required": ["url"],
        },
    }
]


def _is_safe_public_url(url: str) -> bool:
    """SSRF guard: the url this fetches can come from an external, caller-supplied value
    (e.g. accord_research.py's sourceReferences, submitted by an authenticated API
    caller rather than chosen by the trusted agent loop). Reject anything but http(s),
    and reject a hostname that resolves to a loopback/private/link-local/reserved
    address (127.0.0.1, 169.254.169.254 cloud metadata, internal service IPs, etc.) —
    checked here, immediately before the request is made, so every caller of this
    function is covered rather than relying on each caller to pre-filter."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        for family, _, _, _, sockaddr in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                return False
        return True
    except Exception:  # noqa: BLE001 -- any parse/resolution failure is treated as unsafe
        return False


def web_fetch(url: str) -> str:
    """Fetch a URL and return stripped plain text (up to 5 000 chars)."""
    if not _is_safe_public_url(url):
        return f"Failed to fetch {url}: refused -- not a public http(s) address"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ALLEN-RMG/1.0 (research bot)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(200_000)
            charset = "utf-8"
            ct = resp.headers.get_content_charset()
            if ct:
                charset = ct
            html = raw.decode(charset, errors="replace")

        # Strip scripts, styles, tags
        html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<[^>]+>", " ", html)
        html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = re.sub(r"\s+", " ", html).strip()
        return text[:5_000] or "(page returned no text content)"

    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} {e.reason} from {url}"
    except Exception as e:  # noqa: BLE001
        return f"Failed to fetch {url}: {e}"


def run_tool(name: str, tool_input: dict) -> str:
    if name == "web_fetch":
        return web_fetch(tool_input.get("url", ""))
    return f"(unknown web tool: {name})"
