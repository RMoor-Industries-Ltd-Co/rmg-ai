"""Project-key issuance tests — the write side of the per-key MCP privilege boundary.

`mcp_server.scope_for_project` decides what a credential may reach by reading
`projects.mcp_scope`. That makes ISSUANCE the moment the boundary is actually set, and it
is the moment with no second chance: the API key is returned exactly once and is live from
the instant the row commits.

Three properties are locked here:

1. **The intended scope is stored, atomically.** `mcp_scope` goes into the same INSERT as
   the key, so a row never exists at a privilege level nobody asked for — not even for the
   width of a follow-up UPDATE.
2. **An invalid scope is refused, loudly.** Issuance rejects rather than degrading. The
   read path degrades to least privilege on a bad value (a live request must not fail
   open); the write path must not, because minting a key at a level the caller did not ask
   for while reporting success is how a credential ends up trusted for reach it lacks.
3. **Omitting the field changes nothing.** Every key issued before per-key scope existed
   has a NULL column and must keep following the process default.

Most of this needs neither a database nor credentials. The storage round-trip does, and is
skipped without DATABASE_URL exactly like tests/test_namespace_isolation.py.
"""

import os
import uuid

import pytest
from fastapi import HTTPException

from allen import main, registry
from allen.models import CreateProjectRequest


# --------------------------------------------------------------------------------------
# Pure validation — registry.normalize_scope
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["allen", "allie"])
def test_valid_scopes_pass_through(scope):
    assert registry.normalize_scope(scope) == scope


@pytest.mark.parametrize("raw,expected", [("  ALLEN  ", "allen"), ("Allie", "allie")])
def test_scope_is_normalized(raw, expected):
    """Case and surrounding whitespace must not decide a privilege level."""
    assert registry.normalize_scope(raw) == expected


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_scope_means_not_set(blank):
    """Blank folds into NULL — the same "use the process default" the read side applies."""
    assert registry.normalize_scope(blank) is None


# "allie-business" is a namespace, not a scope — the most plausible confusion at issuance,
# and the trap is that its sibling "allen-business" IS a valid scope.
@pytest.mark.parametrize("bad", ["root", "admin", "allie-business", "alle", "overseer"])
def test_invalid_scope_raises(bad):
    with pytest.raises(ValueError):
        registry.normalize_scope(bad)


def test_rejection_does_not_leak_into_least_privilege():
    """The asymmetry that matters: read degrades, write refuses.

    `scope_for_project` maps an unrecognised value to 'allie'. If `normalize_scope` did the
    same, `POST /projects {"mcp_scope": "alien"}` would answer 201 and hand back a key the
    caller believes is an overseer credential. Refusing is the only answer that cannot be
    misread.
    """
    from allen import mcp_server

    assert mcp_server.scope_for_project({"mcp_scope": "alien"}) == "allie"
    with pytest.raises(ValueError):
        registry.normalize_scope("alien")


# --------------------------------------------------------------------------------------
# The route — POST /projects, with the data layer faked
# --------------------------------------------------------------------------------------


class _FakeCreate:
    """Stands in for db.create_project, recording exactly what the route handed it."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, namespace, mcp_scope=None, capabilities=None):
        self.calls.append(
            {"name": name, "namespace": namespace, "mcp_scope": mcp_scope, "capabilities": capabilities or []}
        )
        return {
            "id": f"proj-{namespace}",
            "name": name,
            "namespace": namespace,
            "mcp_scope": mcp_scope,
            "capabilities": capabilities or [],
            "api_key": "av_fake",
        }


@pytest.fixture()
def fake_db(monkeypatch):
    created = _FakeCreate()
    monkeypatch.setattr(main.db, "db_ready", lambda: True)
    monkeypatch.setattr(main.db, "create_project", created)
    return created


@pytest.mark.parametrize("scope", ["allen", "allie"])
def test_route_passes_scope_to_the_data_layer(fake_db, scope):
    """Both credentials PIAAR Business needs: allen-business and allie-business."""
    req = CreateProjectRequest(name=f"PIAAR Business — {scope}", namespace=f"{scope}-business", mcp_scope=scope)
    out = main.create_project_ep(req)

    assert fake_db.calls == [
        {
            "name": f"PIAAR Business — {scope}", "namespace": f"{scope}-business",
            "mcp_scope": scope, "capabilities": [],
        }
    ]
    assert out["mcp_scope"] == scope
    assert out["api_key"], "the key is returned once, here, or it is unrecoverable"


def test_route_rejects_an_invalid_scope_with_400(fake_db):
    req = CreateProjectRequest(name="Bad", namespace="bad-scope", mcp_scope="root")
    with pytest.raises(HTTPException) as exc:
        main.create_project_ep(req)

    assert exc.value.status_code == 400
    assert "root" in str(exc.value.detail)
    assert fake_db.calls == [], "nothing may be written when the scope is refused"


def test_invalid_scope_is_not_reported_as_a_namespace_collision(fake_db):
    """Guards the specific mislabelling: the create is wrapped in a broad `except Exception`
    that blames name/namespace uniqueness. Scope validation must sit outside it, or a typo'd
    privilege level is diagnosed as a taken namespace and 'fixed' by renaming."""
    req = CreateProjectRequest(name="Bad", namespace="bad-scope", mcp_scope="root")
    with pytest.raises(HTTPException) as exc:
        main.create_project_ep(req)

    assert "namespace taken" not in str(exc.value.detail).lower()


@pytest.mark.parametrize("omitted", [None, "", "   "])
def test_route_backward_compatibility(fake_db, omitted):
    """A caller that predates this field, or sends it blank, still gets a NULL column and
    therefore the process-default scope — unchanged behaviour."""
    req = CreateProjectRequest(name="Legacy", namespace="legacy", mcp_scope=omitted)
    out = main.create_project_ep(req)

    assert fake_db.calls[0]["mcp_scope"] is None
    assert out["mcp_scope"] is None


def test_omitting_the_field_entirely_still_validates():
    """The field is genuinely optional on the model, not merely nullable."""
    req = CreateProjectRequest(name="Legacy", namespace="legacy")
    assert req.mcp_scope is None


# --------------------------------------------------------------------------------------
# Storage round-trip — needs a real Postgres, same gate as test_namespace_isolation.py
# --------------------------------------------------------------------------------------

_needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="no DATABASE_URL (test Postgres) configured"
)


@pytest.fixture()
def issued():
    """Issues projects and cleans them up, returning the creator."""
    from allen import db

    db.init_db()
    made = []

    def _make(scope):
        ns = f"test_scope_{uuid.uuid4().hex[:8]}"
        made.append(ns)
        return db.create_project(f"Test {ns}", ns, mcp_scope=scope)

    yield _make

    with db._cursor() as cur:
        for ns in made:
            cur.execute("DELETE FROM projects WHERE namespace = %s", (ns,))


@_needs_db
@pytest.mark.parametrize("scope", ["allen", "allie"])
def test_scope_is_stored_and_read_back(issued, scope):
    from allen import db, mcp_server

    proj = issued(scope)
    assert proj["mcp_scope"] == scope

    # The property that actually matters: authenticating with this key yields this scope.
    resolved = db.project_by_key(proj["api_key"])
    assert resolved["mcp_scope"] == scope
    assert mcp_server.scope_for_project(resolved) == scope


@_needs_db
def test_omitted_scope_stores_null_and_follows_the_process_default(issued, monkeypatch):
    from allen import db, mcp_server
    from allen.config import settings

    proj = issued(None)
    assert proj["mcp_scope"] is None

    resolved = db.project_by_key(proj["api_key"])
    assert resolved["mcp_scope"] is None

    monkeypatch.setattr(type(settings), "mcp_scope", property(lambda self: "allen"), raising=False)
    assert mcp_server.scope_for_project(resolved) == "allen", "NULL must follow the process default"


# --------------------------------------------------------------------------------------
# Capability grants — the authorization boundary for the Accord research service
# (Founder review correction on PR #94). Authentication (a valid key) and authorization
# (what that key may do) are deliberately two different checks.
# --------------------------------------------------------------------------------------


def test_route_rejects_an_unknown_capability_with_400(fake_db):
    req = CreateProjectRequest(name="Bad", namespace="bad-cap", capabilities=["not_a_real_capability"])
    with pytest.raises(HTTPException) as exc:
        main.create_project_ep(req)

    assert exc.value.status_code == 400
    assert fake_db.calls == [], "nothing may be written when a capability name is unrecognized"


def test_route_passes_known_capabilities_to_the_data_layer(fake_db):
    req = CreateProjectRequest(name="Accord caller", namespace="accord-caller", capabilities=["accord_research"])
    out = main.create_project_ep(req)

    assert fake_db.calls[0]["capabilities"] == ["accord_research"]
    assert out["capabilities"] == ["accord_research"]


def test_omitting_capabilities_defaults_to_none_granted():
    """A key is never capable of anything by default -- fail closed."""
    req = CreateProjectRequest(name="Plain", namespace="plain")
    assert req.capabilities == []


def test_require_accord_research_denies_a_project_with_no_capability():
    with pytest.raises(HTTPException) as exc:
        main.require_accord_research({"id": "proj-x", "capabilities": []})
    assert exc.value.status_code == 403


def test_require_accord_research_denies_a_project_with_other_capabilities_only():
    with pytest.raises(HTTPException) as exc:
        main.require_accord_research({"id": "proj-x", "capabilities": ["some_other_capability"]})
    assert exc.value.status_code == 403


def test_require_accord_research_denies_a_project_with_no_capabilities_key_at_all():
    """A legacy row/stateless fallback with no 'capabilities' field at all must deny,
    not crash and not fail open."""
    with pytest.raises(HTTPException) as exc:
        main.require_accord_research({"id": "proj-x"})
    assert exc.value.status_code == 403


def test_require_accord_research_allows_a_project_with_the_capability():
    project = {"id": "proj-x", "capabilities": ["accord_research"]}
    assert main.require_accord_research(project) is project


@_needs_db
def test_capabilities_are_stored_and_read_back():
    from allen import db

    db.init_db()
    ns = f"test_cap_{uuid.uuid4().hex[:8]}"
    try:
        proj = db.create_project(f"Test {ns}", ns, capabilities=["accord_research"])
        assert proj["capabilities"] == ["accord_research"]

        resolved = db.project_by_key(proj["api_key"])
        assert resolved["capabilities"] == ["accord_research"]
    finally:
        with db._cursor() as cur:
            cur.execute("DELETE FROM projects WHERE namespace = %s", (ns,))


@_needs_db
def test_omitted_capabilities_stores_an_empty_array_not_null():
    from allen import db

    db.init_db()
    ns = f"test_cap_{uuid.uuid4().hex[:8]}"
    try:
        proj = db.create_project(f"Test {ns}", ns)
        assert proj["capabilities"] == []

        resolved = db.project_by_key(proj["api_key"])
        assert resolved["capabilities"] == []
    finally:
        with db._cursor() as cur:
            cur.execute("DELETE FROM projects WHERE namespace = %s", (ns,))


@_needs_db
def test_data_layer_refuses_an_invalid_scope(issued):
    """Belt-and-braces: the column has no CHECK constraint, and create_project is its only
    writer. A caller bypassing the route must still not be able to write junk."""
    with pytest.raises(ValueError):
        issued("root")
