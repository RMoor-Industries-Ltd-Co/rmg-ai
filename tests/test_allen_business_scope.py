"""The `allen-business` scope — ALLEN's breadth without ALLEN's personal reach.

A pre-issuance audit of the `allen` scope found it publishes Personal-domain capability over
MCP, including writes: Rahm's calendar (read AND write), ClickUp dispatched at `scope="all"`,
and Notion dispatched with no `business_only`. A BUSINESS-domain credential must not obtain
any of that merely because it needs overseer breadth.

The finding that shaped the fix: `clickup_*` and `notion_*` are **dual-domain**. The same
tool name is safe or unsafe depending on the argument the dispatcher passes, so there is no
name to withhold and `mcp_server._WITHHELD_NAMES` cannot draw this line. The boundary lives
in the dispatcher, and these tests assert it there — at the arguments, not just at the
tool list.

Two halves:

1. `allen-business` is genuinely business-safe (profile AND dispatch).
2. `allen` and `allie` are untouched — this scope is additive.

No database, no credentials, no network.
"""

import pytest

from allen import mcp_server, registry


# --------------------------------------------------------------------------------------
# Fakes — every integration "ready", every module call recorded
# --------------------------------------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.calls = []

    def handle(self, name, inp=None, **kwargs):
        self.calls.append({"name": name, "kwargs": kwargs})
        return f"ok:{name}"

    def run_tool(self, name, inp=None, **kwargs):
        return self.handle(name, inp, **kwargs)

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture()
def wired(monkeypatch):
    """All integrations ready + every tools_* module's handle() recorded."""
    from allen import (
        forms,
        tools_anpu,
        tools_calendar,
        tools_cappo,
        tools_clickup,
        tools_constance,
        tools_gdrive,
        tools_github,
        tools_gmail,
        tools_notion,
        tools_thoth,
        tools_vale,
        tools_web,
        tools_youtube,
    )
    from allen.config import settings

    for flag in ("clickup_ready", "notion_ready", "github_ready", "whatsapp_ready",
                 "cappo_report_ready", "constance_report_ready", "vale_report_ready"):
        monkeypatch.setattr(type(settings), flag, property(lambda self: True), raising=False)
    monkeypatch.setattr(type(settings), "database_url", property(lambda self: "postgres://x"), raising=False)

    for mod in (tools_calendar, tools_gdrive, tools_gmail, tools_youtube,
                tools_cappo, tools_constance, tools_vale, tools_anpu, tools_thoth):
        for fn in ("ready", "any_ready"):
            if hasattr(mod, fn):
                monkeypatch.setattr(mod, fn, lambda: True)

    # Virtual forms would hit the DB; the allen profile builds them, allen-business does not.
    monkeypatch.setattr(forms, "ensure_seed_forms", lambda ns: None)
    monkeypatch.setattr(forms, "build_tool_schemas", lambda ns: [])

    rec = _Recorder()
    for mod in (tools_calendar, tools_clickup, tools_gdrive, tools_github,
                tools_gmail, tools_notion, tools_youtube):
        monkeypatch.setattr(mod, "handle", rec.handle)
    monkeypatch.setattr(tools_web, "run_tool", rec.run_tool)
    monkeypatch.setattr(registry.db, "add_audit", lambda *a, **k: None)
    monkeypatch.setattr(registry.db, "add_error", lambda *a, **k: None)
    return rec


def _names(scope, namespace="ns"):
    """Tool names actually PUBLISHED at a scope — withholding applied, as a client sees it."""
    return {t["name"] for t in mcp_server.visible_tools(namespace, scope)}


def _call(scope, name, inp=None):
    return registry.dispatch(name, inp or {}, scope=scope, namespace="ns", actor="mcp")


# --------------------------------------------------------------------------------------
# The scope exists and is reachable
# --------------------------------------------------------------------------------------


def test_scope_is_registered():
    assert "allen-business" in registry.SCOPES
    assert "allen-business" in registry._DISPATCHERS
    assert registry.normalize_scope("allen-business") == "allen-business"


def test_a_key_can_be_issued_at_this_scope():
    """`allen-business` was previously the single most plausible invalid value at issuance
    (it is also the namespace). It must now be accepted — and still normalize."""
    assert registry.normalize_scope("  Allen-Business  ") == "allen-business"


def test_scope_for_project_honours_it():
    assert mcp_server.scope_for_project({"mcp_scope": "allen-business"}) == "allen-business"


# --------------------------------------------------------------------------------------
# Personal-domain capability is gone
# --------------------------------------------------------------------------------------


def test_no_calendar_tools_are_published(wired):
    """The clearest personal exposure at `allen`: read AND write on Rahm's calendar."""
    assert not [n for n in _names("allen-business") if n.startswith("calendar_")]


@pytest.mark.parametrize(
    "name", ["calendar_list_events", "calendar_create_event", "calendar_update_event", "calendar_delete_event"]
)
def test_calendar_is_not_dispatchable(wired, name):
    """Absent from the profile is not enough — a client can still send the name. The
    dispatcher must refuse it, which it does by never routing it."""
    assert _call("allen-business", name) == f"(unknown tool: {name})"
    assert wired.calls == [], "no calendar module call may be made"


@pytest.mark.parametrize("prefix", ["gmail_", "submit_form_"])
def test_personal_and_form_tools_are_absent(wired, prefix):
    assert not [n for n in _names("allen-business") if n.startswith(prefix)]


def test_reminder_and_alert_tools_are_absent(wired):
    """These push to Rahm's phone. Withheld from MCP anyway; also not in this profile."""
    published = _names("allen-business")
    for name in ("send_alert", "schedule_reminder", "list_reminders", "cancel_reminder"):
        assert name not in published


# --------------------------------------------------------------------------------------
# Dual-domain tools — the boundary is the ARGUMENT, so assert the argument
# --------------------------------------------------------------------------------------


def test_clickup_is_constrained_to_business(wired):
    _call("allen-business", "clickup_list_tasks")
    assert wired.last["kwargs"] == {"scope": "business"}


def test_clickup_writes_are_constrained_too(wired):
    """A write is where mis-scoping does damage, not just leaks it."""
    _call("allen-business", "clickup_create_task", {"name": "x"})
    assert wired.last["kwargs"] == {"scope": "business"}


def test_notion_is_business_only(wired):
    _call("allen-business", "notion_search", {"query": "x"})
    assert wired.last["kwargs"] == {"business_only": True}


def test_clickup_and_notion_match_allie_exactly(wired):
    """One rule for what "business" means, applied at both scopes that claim it. If these
    ever drift, one of the two scopes is reaching data the other considers personal."""
    for name, inp in (("clickup_list_tasks", {}), ("notion_search", {"query": "x"})):
        _call("allen-business", name, inp)
        business = wired.last["kwargs"]
        _call("allie", name, inp)
        assert business == wired.last["kwargs"], f"{name} scoping differs from ALLIE's"


def test_the_dual_domain_boundary_is_invisible_to_a_name_filter(wired):
    """States the architectural finding as an executable fact: these names are published at
    BOTH the unsafe and the safe scope, so no `_WITHHELD_NAMES` entry could separate them."""
    shared = _names("allen") & _names("allen-business")
    assert {"clickup_list_tasks", "notion_search"} <= shared

    _call("allen", "clickup_list_tasks")
    unsafe = wired.last["kwargs"]
    _call("allen-business", "clickup_list_tasks")
    assert unsafe == {"scope": "all"} and wired.last["kwargs"] == {"scope": "business"}


# --------------------------------------------------------------------------------------
# GitHub — reads kept, writes withheld
# --------------------------------------------------------------------------------------


def test_github_reads_are_published(wired):
    published = _names("allen-business")
    assert {"github_read_file", "github_get_issue", "github_list_issues",
            "github_get_pull_request", "github_list_pull_requests"} <= published


def test_github_reads_dispatch(wired):
    assert _call("allen-business", "github_read_file", {"path": "README.md"}) == "ok:github_read_file"


def test_github_writes_are_not_published(wired):
    from allen import tools_github

    assert not (tools_github.WRITE_NAMES & _names("allen-business"))


@pytest.mark.parametrize("name", ["github_create_issue", "github_comment_issue", "github_update_file"])
def test_github_writes_are_refused_at_dispatch(wired, name):
    """Defence at the choke point, not only in the published list: a client that sends the
    name anyway is denied, and the denial is fault-shaped so the attempt is logged."""
    res = _call("allen-business", name, {"title": "x"})
    assert res.startswith("denied:")
    assert registry.looks_like_fault(res), "an attempted escalation must leave a trail"
    assert wired.calls == [], "no GitHub module call may be made"


def test_withheld_names_covers_every_github_write():
    """Keeps `_WITHHELD_NAMES` in sync with the source of truth. A new write tool added to
    tools_github must be withheld deliberately, not silently published."""
    from allen import tools_github

    assert tools_github.WRITE_NAMES <= mcp_server._WITHHELD_NAMES


def test_github_writes_are_withheld_at_every_scope(wired):
    """The documented invariant, now actually enforced. It was previously vacuous at `allie`
    (no GitHub tools at all) and false at `allen`."""
    from allen import tools_github

    for scope in registry.SCOPES:
        assert not (tools_github.WRITE_NAMES & _names(scope)), f"leaked at {scope}"


# --------------------------------------------------------------------------------------
# The built-ins that cannot execute over MCP
# --------------------------------------------------------------------------------------


_BROKEN_BUILTINS = ["delegate_to_allie", "get_agent_rollup", "log_error", "read_error_log", "review_activity"]


@pytest.mark.parametrize("name", _BROKEN_BUILTINS)
def test_unexecutable_builtins_are_not_published(wired, name):
    """These reach `dispatch` via `fallback=`, which the MCP server does not supply. At
    `allen` scope they are advertised and answer `(unknown tool: ...)`; a client cannot tell
    that apart from an outage."""
    assert name not in _names("allen-business")


def test_the_builtins_really_are_broken_over_mcp(wired):
    """Justifies the omission rather than asserting it as taste — this is what a client
    calling them at `allen` scope over MCP actually gets back."""
    for name in _BROKEN_BUILTINS:
        assert _call("allen", name) == f"(unknown tool: {name})"


# --------------------------------------------------------------------------------------
# Legitimate business breadth is preserved
# --------------------------------------------------------------------------------------


def test_business_breadth_is_kept(wired):
    published = _names("allen-business")
    for name in ("clickup_list_tasks", "clickup_create_task", "notion_search",
                 "drive_search", "drive_read_file", "web_fetch",
                 "youtube_list_transcripts", "github_read_file"):
        assert name in published, f"{name} is legitimate business reach and must survive"


@pytest.mark.parametrize("name,inp", [("web_fetch", {"url": "https://x"}),
                                      ("drive_search", {"query": "x"}),
                                      ("youtube_list_transcripts", {})])
def test_business_tools_dispatch(wired, name, inp):
    assert _call("allen-business", name, inp) == f"ok:{name}"


def test_drive_writes_are_audited(wired, monkeypatch):
    """The audit row on a write must survive the new dispatcher — losing it silently was the
    original risk of adding consumers to the registry."""
    rows = []
    monkeypatch.setattr(registry.db, "add_audit", lambda *a, **k: rows.append(a))
    _call("allen-business", "drive_create_file", {"name": "x"})
    assert rows, "a Drive write must record an audit row at this scope too"


# --------------------------------------------------------------------------------------
# Regression — `allen` and `allie` are untouched
# --------------------------------------------------------------------------------------


def test_allen_dispatch_is_unchanged(wired):
    """Full overseer reach, including the personal surfaces. This scope is ALLEN's own and
    must keep working exactly as it did."""
    _call("allen", "clickup_list_tasks")
    assert wired.last["kwargs"] == {"scope": "all"}
    _call("allen", "notion_search", {"query": "x"})
    assert wired.last["kwargs"] == {}
    assert _call("allen", "calendar_list_events") == "ok:calendar_list_events"
    assert _call("allen", "gmail_search", {"q": "x"}) == "ok:gmail_search"


def test_allie_dispatch_is_unchanged(wired):
    _call("allie", "clickup_list_tasks")
    assert wired.last["kwargs"] == {"scope": "business"}
    _call("allie", "notion_search", {"query": "x"})
    assert wired.last["kwargs"] == {"business_only": True}
    assert _call("allie", "calendar_list_events") == "(unknown tool: calendar_list_events)"


def test_allie_published_surface_is_unchanged(wired):
    """ALLIE had no GitHub tools, so adding GitHub writes to _WITHHELD_NAMES must be a no-op
    for her — the one scope where the change could not possibly matter, asserted so."""
    published = _names("allie")
    assert not [n for n in published if n.startswith(("github_", "calendar_", "gmail_"))]
    for name in ("delegate_to_cappo", "cappo_get_report", "anpu_get_reviews", "thoth_get_status"):
        assert name in published


def test_allen_agent_surface_keeps_github_writes(wired):
    """The one intentional narrowing is at the MCP TRANSPORT, not in the registry. ALLEN's
    own console builds its tools from `build_tools` directly and never passes through
    `_WITHHELD_NAMES`, so his GitHub writes are untouched."""
    from allen import tools_github

    agent_side = {t["name"] for t in registry.build_tools("allen", "ns")}
    assert tools_github.WRITE_NAMES <= agent_side
    assert _call("allen", "github_update_file", {"path": "x"}) == "ok:github_update_file"


def test_default_scope_is_still_least_privilege():
    assert mcp_server._default_scope() in ("allie", "allen", "allen-business")
    assert mcp_server.scope_for_project({"mcp_scope": "nonsense"}) == "allie", "typos still fail closed"
