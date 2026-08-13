"""The PIAAR MCP server — ALLEN's tool belt, and through it the whole PIAAR agent network,
exposed over the Model Context Protocol.

WHY IT LIVES HERE. Every `tools_*.py` module already emits `{"name", "description",
"input_schema"}` — MCP's `tools/list` shape with one key renamed. And `config.py` already
holds every sibling agent's URL and key (Cappo, Constance, Vale, Anpu, Thoth) with working
clients beside them. So a server hosted inside ALLEN exposes the entire fleet without the
sibling repos changing a line, and without a second implementation of any integration.

SCOPE IS THE PRIVILEGE BOUNDARY. An MCP client gets `registry`'s **"allie"** profile by
default — the gatekeeper rule, business systems only. Rahm's PERSONAL systems (his
calendar, his Gmail, his personal ClickUp spaces) are not on this surface at all unless
`MCP_SCOPE` is deliberately widened to "allen". Least privilege is the default because an
MCP key is handed to client software, not typed by Rahm.

WITHHELD IN v1 (see `_WITHHELD_PREFIXES`): Gmail, GitHub writes, virtual-form submissions,
and the alert/reminder tools. These either reach Rahm directly (a WhatsApp push), write to
repositories, or act on personal data — each should be re-added deliberately, one at a
time, not swept in because it happened to be in the registry.

Auth reuses the existing `x-allen-key` → project/namespace mapping so an MCP key is a
first-class ALLEN project key, compared in constant time. A compromised key grants exactly
what the configured scope grants — document that when issuing one.
"""

import hmac
import logging
from typing import Any, Optional

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware
from fastmcp.tools.tool import Tool, ToolResult

from . import registry
from .config import settings

logger = logging.getLogger(__name__)

SERVER_NAME = "piaar"

#: Tools kept off the MCP surface in v1 regardless of scope. Prefix-matched.
_WITHHELD_PREFIXES = ("gmail_", "submit_form_")

#: Exact tool names kept off the MCP surface in v1.
_WITHHELD_NAMES = {
    # Reach Rahm's phone directly — an MCP client should not be able to interrupt him.
    "send_alert", "schedule_reminder", "list_reminders", "cancel_reminder",
    # Console-conversation bookkeeping; meaningless outside ALLEN's own chat surface.
    "set_conversation_folder",
    # Virtual-form management is ALLEN's own authoring surface.
    "define_virtual_form", "list_virtual_forms",
}


def _mcp_scope() -> str:
    """The registry scope an MCP client runs as. Defaults to ALLIE's business profile."""
    scope = (getattr(settings, "mcp_scope", "") or "allie").strip().lower()
    if scope not in registry.SCOPES:
        logger.warning("[mcp] invalid MCP_SCOPE %r — falling back to 'allie'", scope)
        return "allie"
    return scope


def _is_withheld(name: str) -> bool:
    return name in _WITHHELD_NAMES or name.startswith(_WITHHELD_PREFIXES)


def visible_tools(namespace: str, scope: Optional[str] = None) -> list:
    """The registry tools this server exposes, withholding list applied.

    Sorted by name so a given scope + namespace always renders a byte-identical tool
    payload. That stability matters: `llm._cached_tools` caches the whole tool block as one
    prompt prefix, and a list that reshuffles between calls would miss that cache on every
    turn.
    """
    tools = registry.build_tools(scope or _mcp_scope(), namespace)
    return sorted(
        (t for t in tools if not _is_withheld(t["name"])),
        key=lambda t: t["name"],
    )


class _RegistryTool(Tool):
    """One registry tool published over MCP.

    Subclassing `Tool` rather than using `from_function` because our schemas are data, not
    Python signatures — they are generated at runtime (virtual forms) and already validated
    by the model. `parameters` takes the module's `input_schema` verbatim.
    """

    piaar_scope: str
    piaar_namespace: str
    piaar_actor: str = "mcp"

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        import anyio

        # registry.dispatch is synchronous and does blocking network I/O (ClickUp, Drive,
        # the sibling agents). Off-thread it so one slow tool call can't stall the event
        # loop and starve every other MCP session on this process.
        text = await anyio.to_thread.run_sync(
            lambda: registry.dispatch(
                self.name,
                arguments or {},
                scope=self.piaar_scope,
                namespace=self.piaar_namespace,
                actor=self.piaar_actor,
            )
        )
        # Faults come back as ordinary result strings (that is the tools_* convention), and
        # registry.dispatch has already written them to the error log. Flag them to the MCP
        # client too, so a caller sees a failed call as failed rather than as content.
        return ToolResult(content=text, is_error=registry.looks_like_fault(text))


def _authorized(key: Optional[str]) -> Optional[dict]:
    """Resolve an MCP key to a project + namespace, or None.

    Mirrors `main.current_project`, but never falls back to an open surface: if no key is
    configured at all, the MCP endpoint stays closed rather than becoming an unauthenticated
    door into ClickUp and Drive. Fails closed by construction — the same posture as
    axis-tekhen's `/auth/verify`.
    """
    if not key:
        return None
    from . import db

    if db.db_ready():
        proj = db.project_by_key(key)
        if proj:
            return proj
    expected = settings.allen_api_key
    # Constant-time: a plain != leaks timing proportional to the matching prefix length,
    # which is enough to recover a key character by character. Matches Cappo's
    # timingSafeEqual and axis-tekhen's hmac.compare_digest.
    if expected and hmac.compare_digest(key, expected):
        return {"id": "proj-atelier", "name": "Master Atelier", "namespace": "atelier"}
    return None


def _caller() -> dict:
    """The authenticated project for the in-flight MCP request."""
    headers = get_http_headers()
    key = headers.get("x-allen-key") or ""
    if not key:
        auth = headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
    proj = _authorized(key)
    if not proj:
        raise PermissionError("invalid or missing x-allen-key")
    return proj


def build() -> FastMCP:
    """Construct the MCP server.

    Tools are registered per-request rather than once at import: the registry's list depends
    on the caller's namespace (virtual forms are DB rows) and on which integrations are
    currently configured, so a snapshot taken at boot would go stale the moment a credential
    is added.
    """
    mcp = FastMCP(SERVER_NAME)

    @mcp.tool(
        name="piaar_whoami",
        description=(
            "Report which PIAAR project/namespace this MCP connection is authenticated as, "
            "which privilege scope it runs at, and how many tools that grants. Call this "
            "first when a tool you expected is missing — it tells you whether the tool is "
            "withheld, or the integration behind it simply isn't configured."
        ),
    )
    async def piaar_whoami() -> str:
        proj = _caller()
        scope = _mcp_scope()
        names = [t["name"] for t in visible_tools(proj["namespace"], scope)]
        return (
            f"project: {proj['name']} (namespace {proj['namespace']})\n"
            f"scope: {scope}\n"
            f"tools: {len(names)}\n" + "\n".join(f"  - {n}" for n in names)
        )

    @mcp.custom_route("/healthz", methods=["GET"])
    async def _healthz(request):  # noqa: ANN001 - starlette Request
        from starlette.responses import JSONResponse

        return JSONResponse({"ok": True, "server": SERVER_NAME, "scope": _mcp_scope()})

    mcp.add_middleware(RegistryMiddleware())
    return mcp


def _registry_tools() -> list:
    """The registry's tools for the in-flight caller, as MCP Tool objects."""
    proj = _caller()
    scope = _mcp_scope()
    return [
        _RegistryTool(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t.get("input_schema") or {"type": "object", "properties": {}},
            piaar_scope=scope,
            piaar_namespace=proj["namespace"],
        )
        for t in visible_tools(proj["namespace"], scope)
    ]


class RegistryMiddleware(Middleware):
    """Publishes the registry through MCP's supported extension points.

    Tools are resolved per request rather than registered once at import, because the
    registry's list depends on the caller's namespace (virtual forms are DB rows) and on
    which integrations are currently configured — a snapshot taken at boot would go stale
    the moment a credential is added in Doppler.
    """

    async def on_list_tools(self, context, call_next):
        static = list(await call_next(context))
        seen = {t.name for t in static}
        return static + [t for t in _registry_tools() if t.name not in seen]

    async def on_call_tool(self, context, call_next):
        name = context.message.name
        for tool in _registry_tools():
            if tool.name == name:
                return await tool.run(context.message.arguments or {})
        # Not a registry tool — hand back to FastMCP for its statically-registered ones
        # (piaar_whoami), which also produces the proper unknown-tool error for a bad name.
        return await call_next(context)
