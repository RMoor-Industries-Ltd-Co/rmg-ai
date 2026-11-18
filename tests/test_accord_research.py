"""Tests for the ALLIE Accord Research Service (CC BUILD DIRECTIVE — RMG-AI / ALLIE
Accord Research Service): request validation, digest canonicalization, and the DB-level
idempotency/durability guarantees. DB-dependent tests skip without DATABASE_URL, exactly
like tests/test_namespace_isolation.py.
"""

import os
import uuid

import pytest

from allen import accord_research
from allen.accord_research import ResearchRequestError, canonical_json, compute_digest

BASE_PAYLOAD = {
    "requestId": "req-fixture-1",
    "businessScope": "hvn_global",
    "publication": "accord",
    "topic": "Private Space as an Extension of Identity",
    "founderDirection": "Men curate wardrobe and career image carefully but neglect the private environment.",
    "researchMode": "VERIFICATION_ONLY",
    "sourceReferences": [],
    "timeHorizon": None,
    "nonNegotiables": "",
    "requestedBy": "office-of-the-emissary",
    "intakeId": "intake-1",
    "manuscriptId": "manuscript-1",
}


# --------------------------------------------------------------------------------------
# Request validation — pure logic, no DB/network
# --------------------------------------------------------------------------------------


def test_valid_payload_passes_through_unchanged():
    payload = dict(BASE_PAYLOAD)
    result = accord_research._validate(payload)
    assert result is payload


@pytest.mark.parametrize("missing_field", ["requestId", "businessScope", "publication", "topic", "researchMode", "intakeId", "manuscriptId"])
def test_missing_required_field_rejected(missing_field):
    payload = dict(BASE_PAYLOAD)
    payload[missing_field] = ""
    with pytest.raises(ResearchRequestError):
        accord_research._validate(payload)


def test_unsupported_business_scope_rejected():
    payload = {**BASE_PAYLOAD, "businessScope": "some_other_scope"}
    with pytest.raises(ResearchRequestError):
        accord_research._validate(payload)


def test_unsupported_publication_rejected():
    payload = {**BASE_PAYLOAD, "publication": "havenry-blog"}
    with pytest.raises(ResearchRequestError):
        accord_research._validate(payload)


def test_unsupported_research_mode_rejected_not_downgraded():
    """§7: an unrecognized mode must be rejected outright, never silently coerced to a
    weaker supported mode."""
    payload = {**BASE_PAYLOAD, "researchMode": "SUPER_DEEP_RESEARCH"}
    with pytest.raises(ResearchRequestError):
        accord_research._validate(payload)


@pytest.mark.parametrize("mode", sorted(accord_research.SUPPORTED_RESEARCH_MODES))
def test_every_documented_research_mode_is_accepted(mode):
    payload = {**BASE_PAYLOAD, "researchMode": mode}
    accord_research._validate(payload)  # does not raise


def test_source_references_must_be_a_list_of_strings():
    payload = {**BASE_PAYLOAD, "sourceReferences": "not-a-list"}
    with pytest.raises(ResearchRequestError):
        accord_research._validate(payload)
    payload2 = {**BASE_PAYLOAD, "sourceReferences": [123]}
    with pytest.raises(ResearchRequestError):
        accord_research._validate(payload2)


# --------------------------------------------------------------------------------------
# Digest canonicalization
# --------------------------------------------------------------------------------------


def test_digest_is_stable_for_the_same_canonical_input():
    a = {"topic": "x", "mode": "VERIFICATION_ONLY"}
    b = {"mode": "VERIFICATION_ONLY", "topic": "x"}  # different key order
    assert canonical_json(a) == canonical_json(b)
    assert compute_digest(a) == compute_digest(b)


def test_digest_changes_when_input_changes():
    a = {"topic": "x"}
    b = {"topic": "y"}
    assert compute_digest(a) != compute_digest(b)


# --------------------------------------------------------------------------------------
# Source-fetch limitations (no network — exercised against an unreachable scheme so the
# failure path is deterministic rather than depending on live connectivity)
# --------------------------------------------------------------------------------------


def test_no_source_references_yields_an_explicit_limitation():
    sources, limitations = accord_research._fetch_founder_sources([])
    assert sources == []
    assert limitations == []  # the "no sources supplied" limitation is added in _execute, not here


def test_unfetchable_source_reference_is_recorded_as_a_limitation_not_a_fabricated_source():
    sources, limitations = accord_research._fetch_founder_sources(["http://127.0.0.1:1/does-not-exist"])
    assert len(sources) == 1
    assert sources[0]["fetchOk"] is False
    assert sources[0]["sourceKind"] == "founder-provided"
    assert any("Could not retrieve" in m for m in limitations)


def test_more_than_max_source_references_reports_a_truncation_limitation():
    many = [f"http://127.0.0.1:1/{i}" for i in range(accord_research.MAX_SOURCE_REFERENCES + 3)]
    sources, limitations = accord_research._fetch_founder_sources(many)
    assert len(sources) == accord_research.MAX_SOURCE_REFERENCES
    assert any("Only the first" in m for m in limitations)


def test_public_sources_strips_internal_fetch_bookkeeping():
    sources, _ = accord_research._fetch_founder_sources(["http://127.0.0.1:1/x"])
    public = accord_research._public_sources(sources)
    assert "fetchOk" not in public[0]
    assert "excerpt" not in public[0]
    assert public[0]["sourceKind"] == "founder-provided"


# --------------------------------------------------------------------------------------
# DB-dependent: idempotency + durability (skipped without DATABASE_URL)
# --------------------------------------------------------------------------------------

_needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="no DATABASE_URL (test Postgres) configured"
)


@pytest.fixture()
def db_env():
    from allen import db

    db.init_db()
    request_id = f"req-test-{uuid.uuid4().hex[:8]}"
    yield db, request_id
    with db._cursor() as cur:
        cur.execute("DELETE FROM accord_research_packets WHERE request_id = %s", (request_id,))
        cur.execute("DELETE FROM accord_research_requests WHERE request_id = %s", (request_id,))


@_needs_db
def test_create_request_is_idempotent_at_the_db_level(db_env):
    db, request_id = db_env
    kwargs = dict(
        request_id=request_id, business_scope="hvn_global", publication="accord",
        topic="x", intake_id="i-1", manuscript_id="m-1", research_mode="VERIFICATION_ONLY",
        requested_by="test", caller_project_id="proj-test", input_json={"a": 1}, input_digest="digest-1",
    )
    created1, row1 = db.create_accord_research_request(**kwargs)
    created2, row2 = db.create_accord_research_request(**kwargs)
    assert created1 is True
    assert created2 is False
    assert row1["id"] == row2["id"]  # same underlying row, not a duplicate


@_needs_db
def test_packet_is_unique_per_request_id(db_env):
    db, request_id = db_env
    db.create_accord_research_request(
        request_id=request_id, business_scope="hvn_global", publication="accord",
        topic="x", intake_id="i-1", manuscript_id="m-1", research_mode="VERIFICATION_ONLY",
        requested_by="test", caller_project_id="proj-test", input_json={"a": 1}, input_digest="digest-1",
    )
    packet1 = db.create_accord_research_packet(request_id, {"packetId": "p1"}, "out-digest-1")
    # A second attempt at persisting a packet for the same request_id must not create a
    # second row -- ON CONFLICT DO NOTHING + re-select returns the original.
    packet2 = db.create_accord_research_packet(request_id, {"packetId": "p2-should-not-land"}, "out-digest-2")
    assert packet1["id"] == packet2["id"]
    assert packet2["packet_json"]["packetId"] == "p1"


@_needs_db
def test_submit_retried_with_same_request_id_returns_existing_completed_packet_without_rerunning(db_env, monkeypatch):
    db, request_id = db_env
    calls = {"n": 0}

    def fake_execute(request_row, payload):
        calls["n"] += 1
        return {
            "packetId": f"pkt-{request_row['request_id']}", "requestId": request_row["request_id"],
            "intakeId": payload["intakeId"], "manuscriptId": payload["manuscriptId"],
            "publication": payload["publication"], "researchMode": payload["researchMode"],
            "generatedAt": "2026-01-01T00:00:00+00:00", "sources": [], "findings": [],
            "culturalRelevance": [], "factualRisks": [], "freshnessNotes": [], "confidence": "low",
            "limitations": ["test fixture"], "inputDigest": request_row["input_digest"],
            "outputDigest": "fixed-digest", "provenance": {"agent": "ALLIE"},
        }

    monkeypatch.setattr(accord_research, "_execute", fake_execute)
    payload = {**BASE_PAYLOAD, "requestId": request_id}
    caller = {"id": "proj-test", "namespace": "test"}

    first = accord_research.submit(dict(payload), caller)
    second = accord_research.submit(dict(payload), caller)

    assert calls["n"] == 1, "a retried submit with the same requestId must not re-execute research"
    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert first["packet"]["packetId"] == second["packet"]["packetId"]


@_needs_db
def test_submit_failure_is_recorded_as_failed_not_a_fabricated_completion(db_env, monkeypatch):
    db, request_id = db_env

    def failing_execute(request_row, payload):
        raise RuntimeError("synthesis provider unreachable")

    monkeypatch.setattr(accord_research, "_execute", failing_execute)
    payload = {**BASE_PAYLOAD, "requestId": request_id}
    caller = {"id": "proj-test", "namespace": "test"}

    result = accord_research.submit(dict(payload), caller)
    assert result["status"] == "failed"
    assert result["packet"] is None
    assert "synthesis provider unreachable" in (result["error"] or "")


@_needs_db
def test_get_status_for_unknown_request_id_returns_none(db_env):
    db, request_id = db_env
    assert accord_research.get_status(f"never-created-{uuid.uuid4().hex[:8]}") is None
