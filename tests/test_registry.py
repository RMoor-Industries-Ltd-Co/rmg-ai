"""Registry tests — the safety net for pulling tool assembly + dispatch out of agent.py
and allie.py into allen/registry.py.

Three things must never regress, and none of them need credentials or a database:

1. **Scope is the privilege boundary.** ALLIE must never be handed a personal-scope tool,
   and her ClickUp/Notion calls must carry the business-scoping arguments.
2. **Writes are audited.** Every WRITE_NAMES tool records an audit row, for every consumer.
   Losing this silently was the whole risk of adding a third consumer (the MCP server).
3. **Faults leave a trail.** A raised exception or a fault-shaped result string is recorded
   to the error log rather than being swallowed.
"""

import pytest

from allen import registry


# --------------------------------------------------------------------------------------
# Fakes — no network, no DB, no credentials
# --------------------------------------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.audits = []
        self.errors = []

    def add_audit(self, namespace, actor, action, detail, result):
        self.audits.append({"namespace": namespace, "actor": actor, "action": action,
                            "detail": detail, "result": result})

    def add_error(self, namespace, source, summary, detail):
        self.errors.append({"namespace": namespace, "source": source,
                            "summary": summary, "detail": detail})


@pytest.fixture()
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(registry.db, "add_audit", r.add_audit)
    monkeypatch.setattr(registry.db, "add_error", r.add_error)
    return r


@pytest.fixture()
def clickup(monkeypatch):
    """Stub ClickUp so dispatch routing is observable without a real workspace."""
    from allen import tools_clickup

    calls = []

    def fake_handle(name, args, scope=None):
        calls.append({"name": name, "args": args, "scope": scope})
        return "ok"

    monkeypatch.setattr(tools_clickup, "handle", fake_handle)
    monkeypatch.setattr(tools_clickup, "WRITE_NAMES", {"clickup_create_task"})
    return calls


# --------------------------------------------------------------------------------------
# 1. Scope is the privilege boundary
# --------------------------------------------------------------------------------------


def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError):
        registry.build_tools("root", "ns")
    with pytest.raises(ValueError):
        registry.dispatch("x", {}, scope="root", namespace="ns", actor="t")


def test_allie_dispatch_scopes_clickup_to_business(rec, clickup):
    registry.dispatch("clickup_list_tasks", {}, scope="allie", namespace="ns", actor="allie")
    assert clickup[0]["scope"] == "business", "the gatekeeper rule must reach tools_clickup"


def test_allen_dispatch_gets_full_clickup_reach(rec, clickup):
    registry.dispatch("clickup_list_tasks", {}, scope="allen", namespace="ns", actor="allen")
    assert clickup[0]["scope"] == "all", "ALLEN is the overseer — personal + business + AMG"


def test_allie_notion_is_business_only(rec, monkeypatch):
    from allen import tools_notion

    seen = {}

    def fake_handle(name, args, business_only=False):
        seen["business_only"] = business_only
        return "ok"

    monkeypatch.setattr(tools_notion, "handle", fake_handle)
    registry.dispatch("notion_search", {}, scope="allie", namespace="ns", actor="allie")
    assert seen["business_only"] is True


def test_allie_never_sees_personal_tools(monkeypatch):
    """ALLIE's profile must exclude calendar, Gmail, GitHub and the virtual forms — those
    are ALLEN's personal/overseer surface. This is the gatekeeper rule as a list check."""
    _force_all_integrations_ready(monkeypatch)
    names = {t["name"] for t in registry.build_tools("allie", "ns")}
    forbidden = [n for n in names if n.startswith(("calendar_", "gmail_", "github_", "submit_form_"))]
    assert forbidden == [], f"ALLIE must not reach personal systems, got {forbidden}"


# --------------------------------------------------------------------------------------
# 2. Writes are audited — for every consumer
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope,actor", [("allen", "allen"), ("allie", "allie"), ("allie", "mcp")])
def test_write_tools_are_audited(rec, clickup, scope, actor):
    registry.dispatch("clickup_create_task", {"name": "x"}, scope=scope, namespace="ns", actor=actor)
    assert len(rec.audits) == 1, "a write must always leave an audit row"
    assert rec.audits[0]["actor"] == actor
    assert rec.audits[0]["action"] == "clickup_create_task"


@pytest.mark.parametrize("scope", ["allen", "allie"])
def test_read_tools_are_not_audited(rec, clickup, scope):
    registry.dispatch("clickup_list_tasks", {}, scope=scope, namespace="ns", actor="t")
    assert rec.audits == [], "reads must not spam the audit log"


def test_audit_failure_does_not_break_the_tool_call(monkeypatch, clickup):
    """An audit write is bookkeeping — it must never take down the actual tool call."""
    def boom(*a, **k):
        raise RuntimeError("audit table gone")

    monkeypatch.setattr(registry.db, "add_audit", boom)
    monkeypatch.setattr(registry.db, "add_error", lambda *a, **k: None)
    assert registry.dispatch(
        "clickup_create_task", {}, scope="allen", namespace="ns", actor="allen"
    ) == "ok"


# --------------------------------------------------------------------------------------
# 3. Faults leave a trail
# --------------------------------------------------------------------------------------


def test_raised_exception_is_logged_and_not_propagated(rec, monkeypatch):
    from allen import tools_clickup

    def boom(name, args, scope=None):
        raise RuntimeError("clickup exploded")

    monkeypatch.setattr(tools_clickup, "handle", boom)
    res = registry.dispatch("clickup_list_tasks", {}, scope="allen", namespace="ns", actor="allen")
    assert len(rec.errors) == 1
    assert "exception" in rec.errors[0]["summary"]
    assert "clickup exploded" in rec.errors[0]["detail"]
    assert isinstance(res, str) and res, "the model must get a spoken-language reply, not a traceback"


def test_fault_shaped_result_is_logged(rec, monkeypatch):
    from allen import tools_clickup

    monkeypatch.setattr(tools_clickup, "handle", lambda n, a, scope=None: "ClickUp API error: 401 denied")
    registry.dispatch("clickup_list_tasks", {}, scope="allen", namespace="ns", actor="allen")
    assert len(rec.errors) == 1, "a fault-shaped result string must still leave a trail"


def test_error_log_tools_are_exempt_from_fault_detection(rec, monkeypatch):
    """read_error_log's output is fault-shaped by nature — running the detector over it
    would log a new fault every time the log is read."""
    registry.dispatch(
        "read_error_log", {}, scope="allen", namespace="ns", actor="allen",
        fallback=lambda n, i: "Recent faults: drive_create_file: API error",
    )
    assert rec.errors == []


def test_allie_now_gets_fault_capture(rec, monkeypatch):
    """ALLIE previously had no fault capture at all. Sharing the wrapper closes that gap."""
    from allen import tools_clickup

    monkeypatch.setattr(tools_clickup, "handle", lambda n, a, scope=None: "call failed: timeout")
    registry.dispatch("clickup_list_tasks", {}, scope="allie", namespace="ns", actor="allie")
    assert len(rec.errors) == 1


# --------------------------------------------------------------------------------------
# Fallback + action classification
# --------------------------------------------------------------------------------------


def test_fallback_handles_names_the_scope_does_not_own(rec):
    res = registry.dispatch(
        "delegate_to_allie", {"task": "x"}, scope="allen", namespace="ns", actor="allen",
        fallback=lambda n, i: f"handled {n}",
    )
    assert res == "handled delegate_to_allie"


def test_unknown_tool_without_fallback_is_reported(rec):
    res = registry.dispatch("nope_not_real", {}, scope="allen", namespace="ns", actor="allen")
    assert "unknown tool" in res


def test_is_action_marks_side_effects_not_reads():
    assert registry.is_action("delegate_to_cappo")
    assert registry.is_action("submit_form_business_task")
    assert registry.is_action("notion_create_page")
    assert not registry.is_action("clickup_list_tasks")
    assert not registry.is_action("notion_search")
    assert not registry.is_action("cappo_get_report")


# --------------------------------------------------------------------------------------
# Schema shape — this is what makes the MCP server a rename rather than a rewrite
# --------------------------------------------------------------------------------------


def _force_all_integrations_ready(monkeypatch):
    """Turn every readiness gate on so tool assembly can be inspected without credentials."""
    from allen import forms, tools_calendar, tools_gdrive, tools_gmail, tools_youtube
    from allen.config import settings

    for flag in ("clickup_ready", "notion_ready", "github_ready", "whatsapp_ready",
                 "cappo_report_ready", "constance_report_ready", "vale_report_ready"):
        monkeypatch.setattr(type(settings), flag, property(lambda self: True), raising=False)
    monkeypatch.setattr(type(settings), "database_url", property(lambda self: "postgres://x"), raising=False)
    # Virtual forms are generated from DB rows; stub them so assembly is inspectable
    # without Postgres. One representative form keeps the submit_form_ prefix covered.
    monkeypatch.setattr(forms, "ensure_seed_forms", lambda ns: None)
    monkeypatch.setattr(forms, "build_tool_schemas", lambda ns: [{
        "name": "submit_form_business_task",
        "description": "stub",
        "input_schema": {"type": "object", "properties": {}},
    }])
    for mod in (tools_calendar, tools_gdrive, tools_gmail):
        monkeypatch.setattr(mod, "ready", lambda: True)
    monkeypatch.setattr(tools_youtube, "ready", lambda: True)
    monkeypatch.setattr(tools_youtube, "any_ready", lambda: True)
    for name in ("tools_cappo", "tools_constance", "tools_vale", "tools_anpu", "tools_thoth"):
        mod = __import__(f"allen.{name}", fromlist=["ready"])
        monkeypatch.setattr(mod, "ready", lambda: True)


@pytest.mark.parametrize("scope", ["allen", "allie"])
def test_every_tool_is_a_valid_mcp_schema(monkeypatch, scope):
    """MCP's tools/list wants {name, description, inputSchema}; ALLEN's modules already
    emit {name, description, input_schema}. Assert that shape holds so the MCP server
    stays a key rename rather than a rewrite."""
    _force_all_integrations_ready(monkeypatch)
    tools = registry.build_tools(scope, "ns")
    assert tools, "expected a non-empty tool list with every integration forced ready"
    for t in tools:
        assert set(("name", "description", "input_schema")) <= set(t), f"malformed tool: {t}"
        assert isinstance(t["name"], str) and t["name"]
        assert t["input_schema"].get("type") == "object", f"{t['name']} has a non-object schema"


def test_tool_names_are_unique_within_a_scope(monkeypatch):
    """A duplicate name would make tools/list ambiguous and silently shadow a tool."""
    _force_all_integrations_ready(monkeypatch)
    for scope in ("allen", "allie"):
        names = [t["name"] for t in registry.build_tools(scope, "ns")]
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"duplicate tool names in {scope}: {dupes}"


def test_build_tools_returns_a_fresh_list_each_call(monkeypatch):
    """llm._cached_tools marks the last entry with cache_control. If build_tools handed
    back the shared module-level TOOLS, that marker would leak between call sites."""
    _force_all_integrations_ready(monkeypatch)
    a = registry.build_tools("allie", "ns")
    b = registry.build_tools("allie", "ns")
    assert a is not b
    a.append({"name": "injected"})
    assert len(b) != len(a)


def test_allen_scoped_call_attaches_fewer_tools_than_full(monkeypatch):
    """A scoped call (the scheduled morning brief) must not pay for schemas it never uses."""
    _force_all_integrations_ready(monkeypatch)
    full = registry.build_tools("allen", "ns")
    scoped = registry.build_tools("allen", "ns", categories={"clickup"})
    assert len(scoped) < len(full)


def test_readiness_drives_both_the_tool_list_and_the_note(monkeypatch):
    """The delegation note is built from readiness() and so is the tool list — that shared
    source is what stops the note describing a capability that isn't attached."""
    _force_all_integrations_ready(monkeypatch)
    on = registry.readiness({"clickup"})
    assert on["clickup"] is True
    assert on["gmail"] is False and on["github"] is False
    names = {t["name"] for t in registry.build_tools("allen", "ns", categories={"clickup"})}
    assert not any(n.startswith("gmail_") for n in names)
