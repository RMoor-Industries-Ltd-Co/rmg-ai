"""Web fetch tool — lets ALLEN retrieve live web content for research."""

import http.client
import ipaddress
import re
import socket
import ssl
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


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPSConnection that opens its TCP socket to a pre-resolved, pre-validated IP
    literal rather than re-resolving `self.host` at connect time -- `self.host` is kept
    as the original hostname purely for the TLS SNI/certificate check and the Host
    header, so this is not a relaxation of certificate validation. This is what actually
    closes the SSRF gap a hostname-only check leaves open: validating a *resolved name*
    and then handing the *name* to a second, independent resolution (what plain
    `urlopen(url)` does) is vulnerable to DNS rebinding -- the attacker's DNS can answer
    differently the second time. Pinning the connection to the IP we already validated
    removes that race entirely."""

    def __init__(self, host: str, pinned_ip: str, *args, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout, source_address=self.source_address
        )
        if getattr(self, "_tunnel_host", None):
            self._tunnel()
        context = self._context or ssl.create_default_context()
        self.sock = context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Plain-HTTP counterpart of `_PinnedHTTPSConnection` -- same IP-pinning, no TLS."""

    def __init__(self, host: str, pinned_ip: str, *args, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout, source_address=self.source_address
        )


def _resolve_safe_ip(hostname: str) -> str:
    """Resolves `hostname` and returns one global (public, routable) address, or raises
    ValueError. Rejects loopback/private/link-local/reserved results (127.0.0.1,
    169.254.169.254 cloud metadata, internal service IPs, etc.) -- used immediately
    before the pinned connection is opened, so the hostname this service ever actually
    connects to is always the one just validated here, not a second independent lookup."""
    for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_global:
            return sockaddr[0]
    raise ValueError(f"refused -- {hostname!r} does not resolve to a public address")


def web_fetch(url: str) -> str:
    """Fetch a URL and return stripped plain text (up to 5 000 chars).

    SSRF guard: the url this fetches can come from an external, caller-supplied value
    (e.g. accord_research.py's `sourceReferences`, submitted by an authenticated API
    caller rather than chosen by the trusted agent loop). Only http(s) is accepted, the
    hostname must resolve to a public address, the TCP connection is pinned to exactly
    that validated address (see `_PinnedHTTPSConnection`/`_PinnedHTTPConnection` --
    closes the DNS-rebinding gap a check-then-separately-connect approach leaves open),
    and redirects are never followed automatically (closes the SSRF-via-redirect gap --
    a redirect target gets reported, not silently fetched, so it never bypasses this
    same validation)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return f"Failed to fetch {url}: refused -- not a public http(s) address"

        ip = _resolve_safe_ip(parsed.hostname)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        conn_cls = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        conn = conn_cls(parsed.hostname, ip, port, timeout=15)
        try:
            conn.request(
                "GET", path,
                headers={"User-Agent": "ALLEN-RMG/1.0 (research bot)", "Host": parsed.hostname},
            )
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                # Never auto-follow -- a redirect target must pass this exact same
                # validation as its own fetch, not be trusted because the original
                # URL already was.
                location = resp.getheader("Location", "(no Location header)")
                return f"HTTP {resp.status} redirect from {url} to {location} (redirects are not followed)"
            if resp.status >= 400:
                return f"HTTP {resp.status} {resp.reason} from {url}"
            raw = resp.read(200_000)
            charset = "utf-8"
            ct = resp.getheader("Content-Type", "")
            if "charset=" in ct:
                charset = ct.split("charset=", 1)[1].split(";")[0].strip()
            html = raw.decode(charset, errors="replace")
        finally:
            conn.close()

        # Strip scripts, styles, tags
        html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<[^>]+>", " ", html)
        html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = re.sub(r"\s+", " ", html).strip()
        return text[:5_000] or "(page returned no text content)"

    except Exception as e:  # noqa: BLE001
        return f"Failed to fetch {url}: {e}"


def run_tool(name: str, tool_input: dict) -> str:
    if name == "web_fetch":
        return web_fetch(tool_input.get("url", ""))
    return f"(unknown web tool: {name})"
