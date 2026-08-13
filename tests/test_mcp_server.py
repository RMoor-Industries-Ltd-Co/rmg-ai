"""MCP server tests — the surface an external client sees.

These run the real Streamable HTTP endpoint in-process (no network, no credentials, no
database) and assert the three things that matter for a surface handed to client software:

1. It is CLOSED without a valid key, and fails closed when no key is configured at all.
2. It publishes the registry's tools with valid MCP schemas.
3. The withheld set really is withheld, and scope really is the privilege boundary.
"""

import pytest
from fastapi import FastAPI
from fastmcp import Client

from allen import mcp_server, registry

KEY = "test-mcp-key"


@pytest.fixture()
def configured(monkeypatch):
    """A configured ALLEN with one shared key and no database (stateless mode)."""
    from allen import db
    from allen.config import settings

    monkeypatch.setattr(type(settings), "allen_api_key", property(lambda self: KEY), raising=False)
    monkeypatch.setattr(db, "db_ready", lambda: False)
    return settings


def _app():
    """The MCP ASGI app wired the same way main.py wires it."""
    mcp_app = mcp_server.build().http_app(path="/")
    api = FastAPI(lifespan=mcp_app.lifespan)
    api.mount("/mcp", mcp_app)
    return api


@pytest.fixture()
def connect(configured):
    """An MCP client bound to the in-process app over ASGI transport.

    The app's lifespan is entered explicitly: httpx's ASGITransport does NOT emit lifespan
    events, and without them FastMCP's StreamableHTTPSessionManager task group is never
    initialized and every request fails. That is the same coupling main.py has to honour —
    which is why the combined lifespan there is load-bearing rather than tidy-up.
    """
    from contextlib import asynccontextmanager

    import httpx
    from fastmcp.client.transports import StreamableHttpTransport

    app = _app()

    @asynccontextmanager
    async def _make(key=KEY):
        headers = {"x-allen-key": key} if key else {}

        def factory(**kw):
            kw.pop("transport", None)
            kw.pop("base_url", None)
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver", **kw
            )

        transport = StreamableHttpTransport(
            "http://testserver/mcp/", headers=headers, httpx_client_factory=factory
        )
        async with app.router.lifespan_context(app):
            async with Client(transport) as client:
                yield client

    return _make


# --------------------------------------------------------------------------------------
# 1. Closed by default
# --------------------------------------------------------------------------------------


def test_no_key_is_rejected(connect):
    """An MCP endpoint reaching ClickUp and Drive must never answer an anonymous caller."""
    assert mcp_server._authorized(None) is None
    assert mcp_server._authorized("") is None
    assert mcp_server._authorized("wrong-key") is None


def test_valid_key_resolves_to_a_project(configured):
    proj = mcp_server._authorized(KEY)
    assert proj and proj["namespace"] == "atelier"


def test_fails_closed_when_no_key_is_configured(monkeypatch):
    """main.current_project falls back to an OPEN surface when ALLEN_API_KEY is unset
    (stateless single-user mode). The MCP endpoint must NOT inherit that — an unset key
    has to mean 'closed', not 'anyone'."""
    from allen import db
    from allen.config import settings

    monkeypatch.setattr(type(settings), "allen_api_key", property(lambda self: ""), raising=False)
    monkeypatch.setattr(db, "db_ready", lambda: False)
    assert mcp_server._authorized("anything") is None
    assert mcp_server._authorized("") is None


def test_key_comparison_is_constant_time():
    """A plain != leaks timing proportional to the matching prefix, which is enough to
    recover a key character by character. Mirrors Cappo's timingSafeEqual."""
    import inspect

    src = inspect.getsource(mcp_server._authorized)
    assert "compare_digest" in src, "MCP key comparison must be constant-time"


# --------------------------------------------------------------------------------------
# 2. It speaks MCP
# --------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tools_list_over_real_mcp_protocol(connect, monkeypatch):
    """End-to-end through the real Streamable HTTP transport — this is what a Claude client
    does on connect."""
    _force_ready(monkeypatch)
    async with connect() as c:
        tools = await c.list_tools()
    names = {t.name for t in tools}
    assert "piaar_whoami" in names, "the orientation tool must always be present"
    assert "clickup_list_tasks" in names, "the registry's tools must be published"
    for t in tools:
        assert t.inputSchema.get("type") == "object", f"{t.name} has a non-object schema"


@pytest.mark.anyio
async def test_calling_a_tool_routes_through_the_registry(connect, monkeypatch):
    """A tools/call must land in registry.dispatch — that is what keeps the audit trail and
    the fault log on the MCP path."""
    _force_ready(monkeypatch)
    seen = {}

    def fake_dispatch(name, args, *, scope, namespace, actor):
        seen.update({"name": name, "scope": scope, "namespace": namespace, "actor": actor})
        return "dispatched"

    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    async with connect() as c:
        res = await c.call_tool("clickup_list_tasks", {})
    assert seen["name"] == "clickup_list_tasks"
    assert seen["actor"] == "mcp", "MCP calls must be attributed to 'mcp' in the audit log"
    assert seen["scope"] == "allie", "an MCP client runs at the business profile by default"
    assert "dispatched" in str(res.content[0].text)


@pytest.mark.anyio
async def test_a_fault_is_surfaced_as_an_error_not_as_content(connect, monkeypatch):
    """tools_* return faults as ordinary strings. The MCP client must see a failed call as
    failed rather than silently treating the error text as a successful result."""
    _force_ready(monkeypatch)
    monkeypatch.setattr(registry, "dispatch", lambda *a, **k: "ClickUp API error: 401 denied")
    async with connect() as c:
        res = await c.call_tool("clickup_list_tasks", {}, raise_on_error=False)
    assert res.is_error is True


# --------------------------------------------------------------------------------------
# 3. Withholding + scope
# --------------------------------------------------------------------------------------


def _force_ready(monkeypatch):
    from allen import forms, tools_calendar, tools_gdrive, tools_gmail, tools_youtube
    from allen.config import settings

    for flag in ("clickup_ready", "notion_ready", "github_ready", "whatsapp_ready",
                 "cappo_report_ready", "constance_report_ready", "vale_report_ready"):
        monkeypatch.setattr(type(settings), flag, property(lambda self: True), raising=False)
    monkeypatch.setattr(type(settings), "database_url", property(lambda self: "postgres://x"), raising=False)
    monkeypatch.setattr(forms, "ensure_seed_forms", lambda ns: None)
    monkeypatch.setattr(forms, "build_tool_schemas", lambda ns: [{
        "name": "submit_form_business_task", "description": "stub",
        "input_schema": {"type": "object", "properties": {}},
    }])
    for mod in (tools_calendar, tools_gdrive, tools_gmail):
        monkeypatch.setattr(mod, "ready", lambda: True)
    monkeypatch.setattr(tools_youtube, "ready", lambda: True)
    monkeypatch.setattr(tools_youtube, "any_ready", lambda: True)
    for name in ("tools_cappo", "tools_constance", "tools_vale", "tools_anpu", "tools_thoth"):
        mod = __import__(f"allen.{name}", fromlist=["ready"])
        monkeypatch.setattr(mod, "ready", lambda: True)


def test_withheld_tools_are_absent_at_every_scope(monkeypatch):
    """Gmail, form submissions, and anything that pushes to Rahm's phone stay off the MCP
    surface in v1 even when the scope is widened to ALLEN."""
    _force_ready(monkeypatch)
    for scope in ("allie", "allen"):
        names = {t["name"] for t in mcp_server.visible_tools("ns", scope)}
        leaked = [
            n for n in names
            if n.startswith(("gmail_", "submit_form_"))
            or n in {"send_alert", "schedule_reminder", "list_reminders", "cancel_reminder"}
        ]
        assert leaked == [], f"withheld tools leaked at scope={scope}: {leaked}"


def test_default_scope_keeps_personal_systems_off_the_surface(monkeypatch):
    _force_ready(monkeypatch)
    assert mcp_server._mcp_scope() == "allie"
    names = {t["name"] for t in mcp_server.visible_tools("ns")}
    assert not any(n.startswith("calendar_") for n in names), "Rahm's calendar is not an MCP surface"


def test_invalid_scope_falls_back_to_least_privilege(monkeypatch):
    """A typo in MCP_SCOPE must not fail open into overseer reach."""
    from allen.config import settings

    monkeypatch.setattr(type(settings), "mcp_scope", property(lambda self: "root"), raising=False)
    assert mcp_server._mcp_scope() == "allie"


def test_tool_order_is_stable(monkeypatch):
    """llm._cached_tools caches the tool block as one prompt prefix; a list that reshuffles
    between calls would miss that cache every turn."""
    _force_ready(monkeypatch)
    a = [t["name"] for t in mcp_server.visible_tools("ns")]
    b = [t["name"] for t in mcp_server.visible_tools("ns")]
    assert a == b == sorted(a)


# --------------------------------------------------------------------------------------
# 4. Mounting MCP must not have cost ALLEN his scheduler
# --------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lifespan_still_starts_and_stops_the_scheduler(monkeypatch):
    """The regression this whole mount is most likely to cause.

    FastMCP needs `lifespan=` on the FastAPI constructor, and FastAPI ignores @app.on_event
    handlers entirely once a lifespan is set. ALLEN's startup used on_event, so a naive
    mount would have silently stopped scheduler.start() — no morning briefing, no feed
    watch, no rollups, no reminders, and nothing in the logs to say why.
    """
    from allen import db, main, scheduler

    calls = {"start": 0, "stop": 0}
    monkeypatch.setattr(scheduler, "start", lambda: calls.__setitem__("start", calls["start"] + 1))
    monkeypatch.setattr(scheduler, "stop", lambda: calls.__setitem__("stop", calls["stop"] + 1))
    monkeypatch.setattr(db, "db_ready", lambda: False)

    async with main._lifespan(main.app):
        assert calls["start"] == 1, "scheduler must start with the app"
    assert calls["stop"] == 1, "scheduler must stop with the app"


@pytest.mark.anyio
async def test_scheduler_stops_even_if_the_mcp_lifespan_fails(monkeypatch):
    """A failure bringing the MCP session manager up must not leave the scheduler running
    against a half-dead app."""
    from contextlib import asynccontextmanager

    from allen import db, main, scheduler

    calls = {"stop": 0}
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "stop", lambda: calls.__setitem__("stop", calls["stop"] + 1))
    monkeypatch.setattr(db, "db_ready", lambda: False)

    @asynccontextmanager
    async def broken(app):
        raise RuntimeError("session manager failed")
        yield  # pragma: no cover

    class _BrokenApp:
        lifespan = staticmethod(broken)

    monkeypatch.setattr(main, "_mcp_app", _BrokenApp())
    with pytest.raises(RuntimeError):
        async with main._lifespan(main.app):
            pass  # pragma: no cover
    assert calls["stop"] == 1


@pytest.fixture
def anyio_backend():
    return "asyncio"
