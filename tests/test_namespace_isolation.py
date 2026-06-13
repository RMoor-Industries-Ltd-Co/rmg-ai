"""Policy #6 — namespace access tests. Prove one project's API key (e.g. atelier) can never
read another namespace's memories (Axis, Cappo, …), plus the core governance invariants:
supersede keeps an audit trail, tombstone hides from retrieval, retrieval excludes inactive.

Runs only when a test Postgres is available (DATABASE_URL set). Skips cleanly otherwise, so
it never blocks environments without a DB. Use a DISPOSABLE database — it writes/cleans rows.
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="no DATABASE_URL (test Postgres) configured")

from allen import db  # noqa: E402


@pytest.fixture()
def two_namespaces():
    db.init_db()
    a = f"test_a_{uuid.uuid4().hex[:8]}"
    b = f"test_b_{uuid.uuid4().hex[:8]}"
    proj_a = db.create_project(f"Test A {a}", a)
    proj_b = db.create_project(f"Test B {b}", b)
    yield proj_a, proj_b
    with db._cursor() as cur:  # cleanup
        for ns in (a, b):
            cur.execute("DELETE FROM memories WHERE namespace = %s", (ns,))
            cur.execute("DELETE FROM projects WHERE namespace = %s", (ns,))


def _ids(mems):
    return {m["id"] for m in mems}


def test_namespace_memory_isolation(two_namespaces):
    proj_a, proj_b = two_namespaces
    ma = db.add_memory(proj_a["namespace"], "secret for A", source="rahm_direct")
    mb = db.add_memory(proj_b["namespace"], "secret for B", source="rahm_direct")

    a_ids = _ids(db.list_memories(proj_a["namespace"]))
    b_ids = _ids(db.list_memories(proj_b["namespace"]))

    assert ma["id"] in a_ids and ma["id"] not in b_ids
    assert mb["id"] in b_ids and mb["id"] not in a_ids
    assert a_ids.isdisjoint(b_ids)


def test_api_key_resolves_only_its_own_namespace(two_namespaces):
    proj_a, proj_b = two_namespaces
    # each key resolves to its own namespace, and never the other's
    assert db.project_by_key(proj_a["api_key"])["namespace"] == proj_a["namespace"]
    assert db.project_by_key(proj_b["api_key"])["namespace"] == proj_b["namespace"]
    assert db.project_by_key(proj_a["api_key"])["namespace"] != proj_b["namespace"]
    assert db.project_by_key("av_not_a_real_key") is None


def test_supersede_keeps_audit_trail(two_namespaces):
    proj_a, _ = two_namespaces
    ns = proj_a["namespace"]
    old = db.add_memory(ns, "Rahm posts on Tuesdays", source="rahm_direct", memory_class="project")
    new = db.supersede_memory(ns, old["id"], "Rahm has no fixed posting schedule")

    active = db.list_memories(ns)
    audit = db.list_memories(ns, include_inactive=True)

    assert new["id"] in _ids(active) and old["id"] not in _ids(active)  # only the correction is live
    assert old["id"] in _ids(audit)  # but the old one is retained for audit
    old_row = next(m for m in audit if m["id"] == old["id"])
    assert old_row["status"] == "superseded"
    assert new["supersedes"] == old["id"]  # the replacement records what it replaced


def test_tombstone_vs_hard_delete_by_class(two_namespaces):
    proj_a, _ = two_namespaces
    ns = proj_a["namespace"]
    sensitive = db.add_memory(ns, "a private health note", source="rahm_direct", memory_class="sensitive")
    session = db.add_memory(ns, "fleeting context", source="allen", memory_class="session")

    db.delete_memory(ns, sensitive["id"])  # non-session -> tombstone (kept for audit)
    db.delete_memory(ns, session["id"])    # session -> hard delete

    active_ids = _ids(db.list_memories(ns))
    audit = db.list_memories(ns, include_inactive=True)

    assert sensitive["id"] not in active_ids
    assert sensitive["id"] in _ids(audit)
    assert next(m for m in audit if m["id"] == sensitive["id"])["status"] == "tombstoned"
    assert session["id"] not in _ids(audit)  # truly gone
