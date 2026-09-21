"""server-ops (rmg-piaar-mcps) — read-only infrastructure inspection for registered hosts,
starting with piaar-preview (45.56.115.89). ALLEN is the only caller server-ops's own
config/server-ops/authz.json grants, and only the 13 read-only inspection tools — the 5
mutating tools (ensure_admin_user, install_authorized_key, ...) exist on that side but are
granted to nobody, so calling one here would just come back denied.

Reached over a Tailscale route, not a public endpoint (rmg-piaar-mcps's
docs/adr/0003-server-ops-mcp.md Decision 3) — piaar_serverops_endpoint is expected to be a
tailnet address, e.g. http://<piaar-preview tailnet IP>:8793/mcp. This module is a thin MCP
client scoped to exactly this one gateway's tool surface; it is not a general MCP client and
does not attempt session/streaming semantics beyond what a single stateless request needs (the
gateway builds a fresh transport per HTTP request — see rmg-piaar-mcps's
packages/server-ops-core/src/http.ts).

serverId defaults to "piaar-preview" — the only server currently registered — but every tool
still accepts it explicitly so a future second target (e.g. motohood) doesn't require a code
change here, only a new default or an explicit argument."""

import json
from typing import Optional

import requests

from .config import settings

DEFAULT_SERVER_ID = "piaar-preview"

_SERVER_ID_PROPERTY = {
    "serverId": {
        "type": "string",
        "description": f"Registered server-ops target id. Defaults to {DEFAULT_SERVER_ID!r} if omitted.",
    }
}


def _read_only_tool(
    name: str,
    description: str,
    extra_properties: Optional[dict] = None,
    extra_required: Optional[list] = None,
) -> dict:
    properties = {**_SERVER_ID_PROPERTY, **(extra_properties or {})}
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(extra_required or []),
        },
    }


TOOLS = [
    _read_only_tool("server_ops_whoami", "Which server-ops caller this connection authenticates as, which registered server targets exist, and which tools are granted on each. Call this first if unsure what's available."),
    _read_only_tool("server_status", "Hostname, kernel/OS version, and uptime for a registered server."),
    _read_only_tool("server_resources", "CPU count, memory, and disk usage for a registered server."),
    _read_only_tool("server_listening_ports", "Listening TCP ports and their bound interfaces on a registered server."),
    _read_only_tool("server_users", "Human-range local accounts (uid 1000-59999) with shell and home dir on a registered server."),
    _read_only_tool("server_ssh_status", "sshd service state and the security-relevant directives in effect on a registered server."),
    _read_only_tool("server_firewall_status", "ufw or iptables rule summary, whichever is present, on a registered server."),
    _read_only_tool("server_docker_status", "Docker engine version and daemon info summary on a registered server."),
    _read_only_tool("server_docker_containers", "All containers (running and stopped), image, status, ports, on a registered server."),
    _read_only_tool("server_docker_networks", "Docker networks and each one's IPAM config and container count, on a registered server."),
    _read_only_tool("server_filesystem_status", "Disk usage and top-level contents of managed deployment directories (/opt, /srv) on a registered server."),
    _read_only_tool("server_reverse_proxy_status", "Caddy or nginx version and active config, whichever is present, on a registered server."),
    _read_only_tool(
        "list_authorized_key_fingerprints",
        "SSH key fingerprints in a user's authorized_keys on a registered server — never the key material itself.",
        {"username": {"type": "string", "description": "POSIX username on the target server."}},
        ["username"],
    ),
    _read_only_tool(
        "verify_directory_access",
        "Stat and list a managed directory on a registered server (must be under /srv or /opt).",
        {"path": {"type": "string", "description": "Absolute path under /srv or /opt on the target server."}},
        ["path"],
    ),
]

_TOOL_NAMES = {tool["name"] for tool in TOOLS}


def ready() -> bool:
    return settings.server_ops_ready


def _parse_mcp_response(resp: requests.Response) -> dict:
    """The gateway's StreamableHTTPServerTransport may answer with a single JSON body or an
    SSE stream of ``data: <json>`` lines (a fresh transport per request, no session — see this
    module's docstring). Handle both rather than assuming one."""
    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type:
        return resp.json()
    # SSE: take the last well-formed `data: {...}` line, which is the final message for a
    # single-request/single-response call.
    last: Optional[dict] = None
    for line in resp.text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload:
            continue
        try:
            last = json.loads(payload)
        except ValueError:
            continue
    if last is None:
        raise ValueError(f"could not parse server-ops response (content-type={content_type!r})")
    return last


def _call(tool_name: str, arguments: dict) -> dict:
    """POST one MCP tools/call request to server-ops. Raises on transport failure; returns the
    parsed JSON-RPC response (caller checks for an 'error' key or result.isError) otherwise.

    Routed through settings.piaar_serverops_proxy (the tailscale-serverops sidecar's HTTP
    forward proxy, when configured) via requests' per-call `proxies=` argument — deliberately
    NOT a container-wide HTTP_PROXY/HTTPS_PROXY env var, which would silently route every other
    tool's traffic (Anthropic, Gmail, Drive, ClickUp, ...) through the tailnet too. Empty proxy
    setting means a direct connection, matching requests' own default."""
    proxy = settings.piaar_serverops_proxy
    resp = requests.post(
        settings.piaar_serverops_endpoint,
        headers={
            "x-piaar-key": settings.piaar_key_serverops_allen,
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        proxies={"http": proxy, "https": proxy} if proxy else None,
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_mcp_response(resp)


def handle(name: str, args: dict) -> str:
    if not ready():
        return "server-ops isn't connected yet."
    if name not in _TOOL_NAMES:
        return f"server-ops call failed: unknown tool {name!r}"

    call_args = dict(args or {})
    if name != "server_ops_whoami":
        call_args.setdefault("serverId", DEFAULT_SERVER_ID)

    try:
        message = _call(name, call_args)
    except Exception as e:
        return f"server-ops call failed: {e}"

    if isinstance(message, dict) and message.get("error"):
        err = message["error"]
        return f"server-ops rejected the call: {err.get('message', err)}"

    result = message.get("result", {}) if isinstance(message, dict) else {}
    content = result.get("content", []) if isinstance(result, dict) else []
    text = "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    if not text:
        return "server-ops call failed: empty response"
    if result.get("isError"):
        return f"server-ops tool error: {text}"
    return text
