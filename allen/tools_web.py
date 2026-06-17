"""Web fetch tool — lets ALLEN retrieve live web content for research."""

import re
import urllib.request
import urllib.error

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


def web_fetch(url: str) -> str:
    """Fetch a URL and return stripped plain text (up to 5 000 chars)."""
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
