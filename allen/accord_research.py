"""ALLIE Accord Research Service — the first real external service boundary for the
Office of the Emissary Functional Authoring Pipeline (CC BUILD DIRECTIVE — RMG-AI /
ALLIE Accord Research Service).

AUTHORITY BOUNDARY (directive §3): ALLIE researches. She does not author the Accord/
Inner Circle article, does not evaluate it, and holds no Founder approval or publication
authority. Nothing in this module may be mistaken for any of those -- it only produces a
durable, attributable research packet for a downstream system (Master Atelier) and a
Founder to use.

HONESTY (directive §13/§21): the only retrieval capability that exists today is a direct
single-page fetch of Founder-supplied URLs (tools_web.web_fetch). There is no multi-source
search/discovery adapter. Every packet says so explicitly in `limitations`, and a finding
is never labeled "sourced-fact" unless it actually cites a fetched excerpt -- see
`_SYNTHESIS_SYSTEM`. The contract (packet shape, digests, provenance) is built to not need
to change when deeper retrieval is added later.
"""

import hashlib
import ipaddress
import json
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from . import db
from .llm import get_llm
from .tools_web import web_fetch

logger = logging.getLogger(__name__)

SUPPORTED_RESEARCH_MODES = {"VERIFICATION_ONLY", "STANDARD_RESEARCH", "DEEP_RESEARCH", "CURRENT_SIGNAL"}
SUPPORTED_PUBLICATIONS = {"accord", "inner-circle"}
#: The only business scope this PR's endpoint accepts (directive §4/§6). A second scope is
#: a future decision, not something this module should silently widen into.
SUPPORTED_BUSINESS_SCOPE = "hvn_global"
#: Bounds how many Founder-supplied references a single request fetches, so one request
#: can't turn into an unbounded number of outbound HTTP calls.
MAX_SOURCE_REFERENCES = 8


class ResearchRequestError(ValueError):
    """A malformed or unsupported request -- maps to HTTP 400, never a fabricated 200."""


def canonical_json(value) -> str:
    """Deterministic JSON text for digesting: sorted keys, no incidental whitespace, so the
    same logical content always produces the same digest regardless of dict insertion order
    or key order from a client (directive §17)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compute_digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate(payload: dict) -> dict:
    """Validates the minimum request contract (directive §6/§7). Raises
    ResearchRequestError (never silently coerces/downgrades a field) on anything
    malformed or unsupported."""
    if not isinstance(payload, dict):
        raise ResearchRequestError("request body must be a JSON object")

    required = ["requestId", "businessScope", "publication", "topic", "researchMode", "intakeId", "manuscriptId"]
    missing = [f for f in required if not str(payload.get(f) or "").strip()]
    if missing:
        raise ResearchRequestError(f"missing required field(s): {', '.join(missing)}")

    if payload["businessScope"] != SUPPORTED_BUSINESS_SCOPE:
        raise ResearchRequestError(
            f"unsupported businessScope {payload['businessScope']!r} -- only {SUPPORTED_BUSINESS_SCOPE!r} is accepted"
        )
    if payload["publication"] not in SUPPORTED_PUBLICATIONS:
        raise ResearchRequestError(f"unsupported publication {payload['publication']!r}")
    if payload["researchMode"] not in SUPPORTED_RESEARCH_MODES:
        # Directive §7: "Do not silently downgrade deep/current research requests to a
        # weaker mode." Rejecting an unrecognized mode outright is the only way to honor
        # that -- there is no safe default to fall back to.
        raise ResearchRequestError(f"unsupported researchMode {payload['researchMode']!r}")

    source_refs = payload.get("sourceReferences") or []
    if not isinstance(source_refs, list) or not all(isinstance(s, str) for s in source_refs):
        raise ResearchRequestError("sourceReferences must be a list of strings")

    return payload


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


def _is_safe_public_url(url: str) -> bool:
    """SSRF guard: this URL comes straight from an external, authenticated API caller's
    `sourceReferences`, not from a trusted internal agent loop -- unlike every other
    `web_fetch` caller in this codebase (allen/registry.py's ALLEN/ALLIE tool dispatch,
    which only ever runs a URL the model itself chose inside an already-trusted session).
    Rejects anything but http(s), and resolves the hostname to make sure it is not a
    loopback/private/link-local/reserved address (e.g. 127.0.0.1, 169.254.169.254 cloud
    metadata, internal service IPs) before this service ever fetches it server-side."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        for family, _, _, _, sockaddr in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                return False
        return True
    except Exception:  # noqa: BLE001 -- any resolution/parse failure is treated as unsafe
        return False


def _fetch_founder_sources(source_refs: list[str]) -> tuple[list[dict], list[str]]:
    """Directly fetches each Founder-supplied URL (bounded). These are retained as
    `sourceKind: "founder-provided"` -- never relabeled as independently discovered
    (directive §15). Returns (internal source records including fetch-only fields, limitation
    strings) -- `_public_sources` strips the fetch-only fields before persisting the packet."""
    sources: list[dict] = []
    limitations: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    for url in source_refs[:MAX_SOURCE_REFERENCES]:
        if not _is_safe_public_url(url):
            sources.append(
                {
                    "sourceId": f"src-{len(sources) + 1}",
                    "title": _domain(url),
                    "publisher": _domain(url),
                    "url": url,
                    "publishedAt": None,
                    "fetchedAt": now,
                    "sourceKind": "founder-provided",
                    "supports": [],
                    "fetchOk": False,
                    "excerpt": "",
                }
            )
            limitations.append(f"Could not retrieve {url}: refused -- not a public http(s) address")
            continue
        text = web_fetch(url)
        ok = not text.startswith(("HTTP ", "Failed to fetch"))
        sources.append(
            {
                "sourceId": f"src-{len(sources) + 1}",
                "title": (text[:120].strip() or _domain(url)) if ok else _domain(url),
                "publisher": _domain(url),
                "url": url,
                "publishedAt": None,
                "fetchedAt": now,
                "sourceKind": "founder-provided",
                "supports": [],
                "fetchOk": ok,
                "excerpt": text[:1500],
            }
        )
        if not ok:
            limitations.append(f"Could not retrieve {url}: {text}")

    if len(source_refs) > MAX_SOURCE_REFERENCES:
        limitations.append(
            f"Only the first {MAX_SOURCE_REFERENCES} of {len(source_refs)} source references were fetched in this pass."
        )
    return sources, limitations


def _public_sources(sources: list[dict]) -> list[dict]:
    """Strips internal-only fetch bookkeeping (fetchOk/excerpt) before the source record
    enters the durable packet -- the packet's source shape is exactly directive §11's
    contract, nothing more."""
    return [{k: v for k, v in s.items() if k not in ("fetchOk", "excerpt")} for s in sources]


_SYNTHESIS_SYSTEM = (
    "You are ALLIE, Rahm's research/intelligence agent, preparing a research packet for an "
    "Accord/Inner Circle article. You are NOT the author and NOT the editorial evaluator -- "
    "you only gather and characterize evidence for Master Atelier and the Founder to use. "
    "Given the topic, Founder direction, and any fetched source excerpts below, produce "
    "STRICT JSON (no prose outside the JSON object) with exactly this shape:\n"
    '{"findings": [{"statement": "...", "kind": "sourced-fact|interpretation|hypothesis", '
    '"sourceIds": ["src-1"], "confidence": "low|medium|high", "notes": "..."}], '
    '"culturalRelevance": ["..."], "factualRisks": ["..."], "freshnessNotes": ["..."]}\n'
    "Rules: a finding with kind 'sourced-fact' MUST cite at least one real sourceId from the "
    "excerpts below and must not claim anything beyond what that excerpt actually supports. "
    "If no source excerpts are provided, you may still return 'interpretation'/'hypothesis' "
    "findings reasoning about the topic itself, but NEVER label an unsourced claim "
    "'sourced-fact'. Keep findings concise (3-6 items). Never invent a source, a URL, or a "
    "statistic that is not in the excerpts."
)


def _synthesize(
    topic: str, founder_direction: str, non_negotiables: str, research_mode: str,
    sources: list[dict], namespace: str,
) -> dict:
    excerpts = (
        "\n\n".join(f"[{s['sourceId']}] {s['url']}\n{s['excerpt']}" for s in sources if s.get("fetchOk"))
        or "(no source excerpts available)"
    )
    user = (
        f"Topic: {topic}\n"
        f"Founder direction: {founder_direction or '(none provided)'}\n"
        f"Non-negotiables: {non_negotiables or '(none)'}\n"
        f"Research mode: {research_mode}\n\n"
        f"Fetched source excerpts:\n{excerpts}"
    )
    raw = get_llm().complete(
        system=_SYNTHESIS_SYSTEM, user=user, max_tokens=1200,
        namespace=namespace, feature="accord_research",
    )
    try:
        match = re.search(r"\{[\s\S]*\}", raw)
        parsed = json.loads(match.group(0) if match else raw)
        if not isinstance(parsed, dict):
            raise ValueError("model output was not a JSON object")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[accord_research] synthesis output could not be parsed as JSON: %s", exc)
        return {
            "findings": [], "culturalRelevance": [], "factualRisks": [], "freshnessNotes": [],
            "_synthesisError": "model research synthesis did not return valid JSON; no findings were recorded",
        }
    return parsed


def _execute(request_row: dict, payload: dict) -> dict:
    """Performs the research this service can actually do today and returns the completed
    packet dict. Raises on a genuine execution failure (e.g. the LLM call itself erroring)
    -- that is surfaced as a `failed` request, never papered over as a thin `completed` one."""
    source_refs = payload.get("sourceReferences") or []
    sources, fetch_limitations = _fetch_founder_sources(source_refs) if source_refs else ([], [])
    limitations = list(fetch_limitations)

    if not source_refs:
        limitations.append(
            "No Founder-provided source references were supplied, and no multi-source "
            "search/discovery adapter is connected yet -- this packet contains no "
            "independently retrieved evidence."
        )
    elif not any(s["fetchOk"] for s in sources):
        limitations.append("None of the supplied Founder source references could be retrieved.")
    limitations.append(
        "Multi-source web search/discovery is not yet implemented in this service; only "
        "direct retrieval of Founder-supplied URLs is available in this version."
    )

    namespace = f"accord-research-{payload['publication']}"
    synthesis = _synthesize(
        payload["topic"], payload.get("founderDirection", ""), payload.get("nonNegotiables", ""),
        payload["researchMode"], sources, namespace,
    )
    if synthesis.get("_synthesisError"):
        limitations.append(synthesis["_synthesisError"])

    confidence = "low"
    if any(s.get("fetchOk") for s in sources) and synthesis.get("findings"):
        confidence = "medium"

    generated_at = datetime.now(timezone.utc).isoformat()
    packet = {
        "packetId": f"pkt-{request_row['request_id']}",
        "requestId": request_row["request_id"],
        "intakeId": payload["intakeId"],
        "manuscriptId": payload["manuscriptId"],
        "publication": payload["publication"],
        "researchMode": payload["researchMode"],
        "generatedAt": generated_at,
        "sources": _public_sources(sources),
        "findings": synthesis.get("findings", []),
        "culturalRelevance": synthesis.get("culturalRelevance", []),
        "factualRisks": synthesis.get("factualRisks", []),
        "freshnessNotes": synthesis.get("freshnessNotes", []),
        "confidence": confidence,
        "limitations": limitations,
        "inputDigest": request_row["input_digest"],
        "outputDigest": None,  # filled in below, once the rest of the packet is final
        "provenance": {
            "agent": "ALLIE",
            "coordinator": "ALLEN",
            "service": "rmg-ai/accord-research",
            "serviceVersion": "v1",
            "requestId": request_row["request_id"],
            "callerProjectId": request_row.get("caller_project_id"),
            "retrievalMethod": "direct-fetch" if source_refs else "none",
            "generatedAt": generated_at,
        },
    }
    packet["outputDigest"] = compute_digest({k: v for k, v in packet.items() if k != "outputDigest"})
    return packet


def _status_response(request_row: dict) -> dict:
    """The one response shape both POST (submit) and GET (retrieve) return (directive §18/
    §19) -- a caller never has to interpret two different payload shapes for the same
    request_id."""
    packet_row = None
    if request_row["status"] == "completed":
        packet_row = db.get_accord_research_packet(request_row["request_id"])
    return {
        "requestId": request_row["request_id"],
        "status": request_row["status"],
        "publication": request_row["publication"],
        "researchMode": request_row["research_mode"],
        "intakeId": request_row["intake_id"],
        "manuscriptId": request_row["manuscript_id"],
        "inputDigest": request_row["input_digest"],
        "error": request_row.get("error"),
        "createdAt": str(request_row.get("created_at")) if request_row.get("created_at") else None,
        "startedAt": str(request_row.get("started_at")) if request_row.get("started_at") else None,
        "completedAt": str(request_row.get("completed_at")) if request_row.get("completed_at") else None,
        "packet": packet_row["packet_json"] if packet_row else None,
    }


def submit(payload: dict, caller_project: dict) -> dict:
    """The POST /api/research/accord entrypoint's logic. Idempotent by `requestId`
    (directive §8): only the caller whose INSERT actually wins the DB-level uniqueness
    race executes the research; every other caller (a genuine retry, or a concurrent
    duplicate) gets back the already-recorded state/packet without re-running anything."""
    payload = _validate(payload)
    input_digest = compute_digest(payload)

    created, request_row = db.create_accord_research_request(
        request_id=payload["requestId"],
        business_scope=payload["businessScope"],
        publication=payload["publication"],
        topic=payload["topic"],
        intake_id=payload["intakeId"],
        manuscript_id=payload["manuscriptId"],
        research_mode=payload["researchMode"],
        requested_by=str(payload.get("requestedBy") or ""),
        caller_project_id=caller_project.get("id"),
        input_json=payload,
        input_digest=input_digest,
    )
    if not created:
        return _status_response(request_row)

    db.update_accord_research_request_status(payload["requestId"], "running", mark_started=True)
    try:
        packet = _execute(request_row, payload)
    except Exception as exc:  # noqa: BLE001 -- a real failure must land as `failed`, not a 500 with no record
        logger.warning("[accord_research] request %s failed: %s", payload["requestId"], exc)
        db.update_accord_research_request_status(payload["requestId"], "failed", error=str(exc), mark_completed=True)
        return _status_response(db.get_accord_research_request(payload["requestId"]))

    db.create_accord_research_packet(payload["requestId"], packet, packet["outputDigest"])
    db.update_accord_research_request_status(payload["requestId"], "completed", mark_completed=True)
    return _status_response(db.get_accord_research_request(payload["requestId"]))


def get_status(request_id: str) -> Optional[dict]:
    """The GET /api/research/accord/{requestId} entrypoint's logic."""
    row = db.get_accord_research_request(request_id)
    if not row:
        return None
    return _status_response(row)
