"""Shared tool registry — the one place ALLEN, ALLIE, and the MCP server assemble their
tool schemas and execute a tool call.

Before this module the tool list was assembled twice (``agent.respond_agentic`` and
``allie.run``) and the audit/fault wrapper lived inside ``agent.py``'s closure. A third
consumer — the MCP server — calling ``tools_*.handle()`` directly would silently lose both
the audit trail and the fault log on every write. Extracting them here makes that bypass
structurally impossible: every consumer goes through :func:`dispatch`.

SCOPE IS THE PRIVILEGE BOUNDARY, and it is data rather than duplicated code:

- ``"allen"`` — the overseer. Every ClickUp space (personal + RMG/RMI + AMG), all of
  Notion, calendar, Gmail, GitHub, Drive, forms.
- ``"allen-business"`` — ALLEN's breadth with ALLIE's domain constraints. Same overseer
  tools (GitHub reads, Drive, web, YouTube) but ClickUp ``scope="business"``, Notion
  ``business_only=True``, and no calendar at all. This is the scope a BUSINESS-domain
  MCP credential runs at.
- ``"allie"`` — the gatekeeper rule. ClickUp ``scope="business"``, Notion
  ``business_only=True``, plus delegation down to Cappo/Constance/Vale and read-only
  pulls from Anpu/Thoth. Rahm's PERSONAL systems stay out of reach.

An MCP client gets ``"allie"`` by default: least privilege, and it keeps Rahm's personal
systems off the MCP surface entirely.

WHY ``"allen-business"`` HAD TO BE A SCOPE rather than a withholding list: ``clickup_*``
and ``notion_*`` are dual-domain tools. The SAME tool name reaches personal or business
data depending on the argument the dispatcher passes — ``scope="all"`` vs
``scope="business"``, ``business_only`` set or not. A name-based filter (which is all
``mcp_server._WITHHELD_NAMES`` can express) is structurally incapable of drawing that
line, because there is no name to withhold. The boundary has to be applied where the
argument is chosen, which is here.
"""

import json
import logging
from typing import Callable, Optional

from . import db, forms

logger = logging.getLogger(__name__)

SCOPES = ("allen", "allen-business", "allie")

#: Returned by a scope dispatcher when it does not own the tool, so :func:`dispatch` can
#: fall through to the caller's own built-ins. A sentinel object rather than ``None``
#: because a tool legitimately returning ``None``/empty must not be mistaken for a miss.
_UNHANDLED = object()


# --------------------------------------------------------------------------------------
# Fault detection (moved verbatim from agent.py so ALLIE and MCP get it too)
# --------------------------------------------------------------------------------------

# Substrings that mark a fault-shaped tool RESULT (tools return error strings, not
# exceptions). Matched only against the head of the result to avoid flagging legit content
# that merely mentions "error".
_FAULT_MARKERS = (
    "api error", "call failed", "isn't configured", "is not configured", "not configured",
    "(unknown ", "ingest failed", "could not create", "could not reach", "failed:", "error code",
    "denied", "invalid or missing", "no refresh token", "not connected", "isn't connected",
)

#: Tools whose whole job is to talk ABOUT faults — their output is fault-shaped by nature,
#: so running the fault detector over them would log a fault every time they are read.
_FAULT_EXEMPT = ("log_error", "read_error_log", "review_activity")


def looks_like_fault(res: str) -> bool:
    if not res:
        return False
    head = res[:200].lower()
    return any(m in head for m in _FAULT_MARKERS)


# --------------------------------------------------------------------------------------
# Tool assembly
# --------------------------------------------------------------------------------------


def readiness(categories: Optional[set[str]] = None) -> dict:
    """Which of ALLEN's tool categories are actually attachable this turn.

    ``categories=None`` is the full interactive set; a scoped call (e.g. the scheduled
    morning brief) attaches only the named ones so a background job doesn't pay to send
    schemas it will never use.

    This is deliberately the SINGLE source of truth for both the tool list and the
    delegation note in ``agent._build_delegation_note``. They were computed from the same
    inline flags before; keeping one function means the note can never drift into
    describing a capability that isn't actually attached — the exact bug the note's
    docstring warns about.
    """
    from . import tools_calendar, tools_gdrive, tools_gmail, tools_youtube
    from .config import settings

    full = categories is None

    def want(cat: str) -> bool:
        return full or cat in categories

    return {
        "full": full,
        "clickup": settings.clickup_ready and want("clickup"),
        "notion": settings.notion_ready and want("notion"),
        "calendar": tools_calendar.ready() and want("calendar"),
        "youtube": tools_youtube.any_ready() and want("youtube"),
        "gdrive": tools_gdrive.ready() and want("gdrive"),
        "github": settings.github_ready and want("github"),
        "gmail": tools_gmail.ready() and want("gmail"),
        "reminders": bool(settings.whatsapp_ready and settings.database_url) and want("reminders"),
        "web": want("web"),
        "forms": want("forms"),
    }


def _allen_tools(namespace: str, on: dict) -> list:
    """ALLEN's per-turn tool list, built from the :func:`readiness` flags so a
    misconfigured integration is never advertised."""
    from . import (
        agent,
        tools_calendar,
        tools_clickup,
        tools_gdrive,
        tools_github,
        tools_gmail,
        tools_notion,
        tools_web,
        tools_youtube,
    )

    tools = list(agent.ALLEN_TOOLS)
    if on["reminders"]:
        tools += agent.REMINDER_TOOLS  # push alerts + scheduled WhatsApp reminders
    if on["clickup"]:
        tools += tools_clickup.TOOLS  # read tools always; writes only on full (interactive) calls
        if on["full"]:
            tools += tools_clickup.WRITE_TOOLS  # full CRUD across all spaces (personal + RMG/RMI + AMG)
    if on["notion"]:
        tools += tools_notion.TOOLS
    if on["calendar"]:
        tools += tools_calendar.TOOLS  # ALLEN manages Rahm's personal calendar
    if on["web"]:
        tools += tools_web.TOOLS
    if on["youtube"]:
        tools += tools_youtube.available_tools()  # ingest (save) + transcript library (read)
    if on["gdrive"]:
        tools += tools_gdrive.TOOLS  # Drive read + CRUD (TOOLS already includes WRITE_TOOLS)
    if on["github"]:
        tools += tools_github.TOOLS + tools_github.WRITE_TOOLS  # allen-piaar-control-bot
    if on["gmail"]:
        tools += tools_gmail.TOOLS  # search/read/send/reply/archive across Rahm's accounts
    if on["forms"]:
        forms.ensure_seed_forms(namespace)
        tools += forms.build_tool_schemas(namespace) + forms.META_TOOLS
    return tools


def _allen_business_tools(namespace: str) -> list:
    """ALLEN's profile with every PERSONAL-domain capability removed.

    What is deliberately absent, and why each one:

    - **calendar_\\*** — Rahm's personal calendar, and ``_allen_tools`` grants write as well
      as read. There is no business subset of it to keep, so the whole module is out.
    - **gmail_\\*, forms, reminders** — personal or push-to-Rahm's-phone. Already withheld
      from MCP at every scope; omitted here too so the profile is honest on its own rather
      than relying on a downstream filter to clean it up.
    - **``tools_github.WRITE_TOOLS``** — reads are legitimate business breadth, writes are
      withheld in v1. ``mcp_server`` enforces that at the transport as well; both, because
      this profile is the claim and that list is the enforcement.
    - **``agent.ALLEN_TOOLS``** — ``delegate_to_allie``, ``get_agent_rollup``,
      ``log_error``, ``read_error_log``, ``review_activity``. These need ``agent.py``'s
      per-turn closure and reach ``dispatch`` via ``fallback=``, which the MCP server does
      not supply. Published at ``"allen"`` scope they answer ``(unknown tool: ...)`` and log
      a fault row for the privilege. Advertising a tool that cannot run is worse than not
      advertising it: a client cannot tell it apart from an outage.

    ALLIE's delegation tools (Cappo/Constance/Vale) are NOT grafted on. They are hers, and
    this scope's job is to make ALLEN's existing reach safe, not to invent a new capability
    set. Adding them later is one line if a client turns out to need them.
    """
    from . import tools_clickup, tools_gdrive, tools_github, tools_notion, tools_web, tools_youtube
    from .config import settings

    tools: list = []
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS + tools_clickup.WRITE_TOOLS  # constrained to business at dispatch
    if settings.notion_ready:
        tools += tools_notion.TOOLS  # business_only applied at dispatch
    tools += tools_web.TOOLS
    if tools_youtube.any_ready():
        tools += tools_youtube.available_tools()
    if tools_gdrive.ready():
        tools += tools_gdrive.TOOLS
    if settings.github_ready:
        tools += tools_github.TOOLS  # reads only — WRITE_TOOLS deliberately not added
    return tools


def _allie_tools(namespace: str) -> list:
    """ALLIE's tool list — the business profile. No calendar, no Gmail, no GitHub, no
    forms; those are ALLEN's. Delegation and cached-report pulls are hers."""
    from . import (
        tools_anpu,
        tools_cappo,
        tools_clickup,
        tools_constance,
        tools_gdrive,
        tools_notion,
        tools_thoth,
        tools_vale,
        tools_youtube,
    )
    from .config import settings

    tools: list = []
    if settings.clickup_ready:
        tools += tools_clickup.TOOLS + tools_clickup.WRITE_TOOLS
    if settings.notion_ready:
        tools += tools_notion.TOOLS
    if tools_cappo.ready():
        tools += tools_cappo.TOOLS  # delegate AMG work down to Cappo
    if settings.cappo_report_ready:
        tools += tools_cappo.REPORT_TOOLS  # pull his cached report (separate URL from delegation)
    if tools_constance.ready():
        tools += tools_constance.TOOLS  # delegate a Connection Circle task to Constance
    if settings.constance_report_ready:
        tools += tools_constance.REPORT_TOOLS  # pull her cached executive status report
    if tools_vale.ready():
        tools += tools_vale.TOOLS  # delegate HVN showroom questions to Vale
    if settings.vale_report_ready:
        tools += tools_vale.REPORT_TOOLS  # pull her cached HVN<->AMG activity report
    if tools_anpu.ready():
        tools += tools_anpu.TOOLS  # pull AXIS/Anpu's already-cached oversight reviews
    if tools_thoth.ready():
        tools += tools_thoth.TOOLS  # pull AXIS/Thoth's already-cached candidate board
    if tools_youtube.ready():
        tools += tools_youtube.TOOLS  # YouTube → Drive for research + b-roll
    if tools_gdrive.ready():
        tools += tools_gdrive.TOOLS  # Drive read + CRUD (TOOLS already includes WRITE_TOOLS)
    return tools


def normalize_scope(raw: Optional[str]) -> Optional[str]:
    """Validate a scope at ISSUANCE time, returning the canonical value or ``None``.

    ``None`` or blank means "not set": the ``projects`` row keeps a NULL ``mcp_scope`` and
    ``mcp_server.scope_for_project`` falls back to the process-wide default, which is how
    every key issued before per-key scope existed keeps behaving. Blank folds into "not
    set" rather than erroring so that what an empty scope means is decided in one place and
    matches the read side exactly.

    Anything else raises ``ValueError``.

    Note the deliberate asymmetry with ``mcp_server.scope_for_project``, which falls back to
    least privilege on an unrecognised value. Reading is the quiet end of the boundary — a
    live request must never fail open, so it degrades. Issuing is the loud end: the caller
    asked for a *specific* privilege level, and minting a key at some other level while
    reporting success is how a credential ends up trusted for reach it does not have.
    """
    if raw is None or not str(raw).strip():
        return None
    scope = str(raw).strip().lower()
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r} — expected one of {', '.join(SCOPES)}")
    return scope


def build_tools(
    scope: str,
    namespace: str,
    *,
    categories: Optional[set[str]] = None,
) -> list:
    """Assemble the Anthropic/MCP tool schemas for ``scope``.

    ``categories=None`` means the full interactive set (ALLEN only — ALLIE's profile is
    fixed). The returned list is a fresh list each call, so a caller marking one entry
    with ``cache_control`` never mutates the shared module-level ``TOOLS``.

    Ordering is deterministic for a given scope + namespace so the rendered tool payload
    is byte-stable and stays promptcache-friendly (see ``llm._cached_tools``).
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r} — expected one of {SCOPES}")
    if scope == "allie":
        return _allie_tools(namespace)
    if scope == "allen-business":
        return _allen_business_tools(namespace)
    return _allen_tools(namespace, readiness(categories))


def write_names() -> set:
    """Every tool name that performs a write. This is the audit + privilege boundary; an
    MCP profile that withholds writes filters on exactly this set."""
    from . import tools_calendar, tools_clickup, tools_gdrive, tools_github, tools_gmail

    return (
        set(getattr(tools_gdrive, "WRITE_NAMES", set()))
        | set(getattr(tools_calendar, "WRITE_NAMES", set()))
        | set(getattr(tools_clickup, "WRITE_NAMES", set()))
        | set(getattr(tools_github, "WRITE_NAMES", set()))
        | set(getattr(tools_gmail, "WRITE_NAMES", set()))
    )


#: Single-name tools that ARE a side effect even though they carry no WRITE_NAMES marker.
_ACTION_SINGLETONS = {
    "delegate_to_allie", "delegate_to_cappo", "delegate_to_constance", "delegate_to_vale",
    "send_alert", "schedule_reminder", "cancel_reminder", "youtube_ingest",
    "define_virtual_form", "set_conversation_folder",
}


def is_action(name: str) -> bool:
    """Whether ``name`` constitutes actually DOING something (a write / side effect) rather
    than a read. Feeds agent.py's confabulation guard — the check that tells "he did it"
    from "he only said he did.\""""
    return (
        name in write_names()
        or name in _ACTION_SINGLETONS
        or name.startswith("submit_form_")
        or (name.startswith("notion_") and any(
            k in name for k in ("create", "update", "append", "add", "delete", "move")
        ))
    )


# --------------------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------------------


def _audit(namespace: str, actor: str, name: str, detail: str, res: str) -> None:
    try:
        db.add_audit(namespace, actor, name, detail, res)
    except Exception as exc:  # an audit write must never take down the tool call itself
        logger.error("[registry] audit write failed for %s: %s", name, exc)


def _dispatch_allen(name: str, inp: dict, namespace: str, actor: str):
    """ALLEN's module routing — full reach. Built-ins (delegate_to_allie, reminders,
    error log, ...) are NOT here: they depend on agent.py's per-turn closure state, so
    they arrive via ``dispatch(fallback=...)``."""
    from . import tools_calendar, tools_clickup, tools_gdrive, tools_github, tools_gmail, tools_notion, tools_web, tools_youtube

    if name.startswith("clickup_"):
        res = tools_clickup.handle(name, inp, scope="all")  # personal + RMG/RMI + AMG
        if name in tools_clickup.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("notion_"):
        return tools_notion.handle(name, inp)  # ALLEN sees all Notion (overseer)
    if name.startswith("calendar_"):
        res = tools_calendar.handle(name, inp)
        if name in tools_calendar.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("web_"):
        return tools_web.run_tool(name, inp)
    if name.startswith("youtube_"):
        return tools_youtube.handle(name, inp)
    if name.startswith("drive_"):
        res = tools_gdrive.handle(name, inp)
        if name in tools_gdrive.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("github_"):
        res = tools_github.handle(name, inp)
        if name in tools_github.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("gmail_"):
        res = tools_gmail.handle(name, inp)
        if name in tools_gmail.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name == "list_virtual_forms":
        return forms.list_forms_summary(namespace)
    if name == "define_virtual_form":
        res = forms.define_form(namespace, inp)
        _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("submit_form_"):
        res = forms.dispatch_submit(namespace, name, inp)
        _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    return _UNHANDLED


def _dispatch_allen_business(name: str, inp: dict, namespace: str, actor: str):
    """ALLEN's module routing with ALLIE's constraining arguments.

    This function is where the business/personal boundary is actually drawn for this scope,
    and it has to be here rather than in a tool-name filter: ``clickup_list_tasks`` and
    ``notion_search`` are the same names at every scope, and what makes a call business-safe
    is the argument passed alongside them. ``scope="business"`` and ``business_only=True``
    are copied from ``_dispatch_allie`` deliberately — one rule for what "business" means,
    applied at both scopes that claim it.

    Personal modules (calendar, Gmail, forms) are simply not routed. They fall through to
    ``_UNHANDLED``, and the MCP server supplies no ``fallback``, so a client that calls one
    anyway is refused — the same way ``_dispatch_allie`` already refuses them.

    GitHub writes are refused with an explicit denial rather than silence. The denial string
    trips ``looks_like_fault``, so an attempt to write through a business credential lands in
    the error log instead of vanishing.
    """
    from . import tools_clickup, tools_gdrive, tools_github, tools_notion, tools_web, tools_youtube

    if name.startswith("clickup_"):
        res = tools_clickup.handle(name, inp, scope="business")
        if name in tools_clickup.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("notion_"):
        return tools_notion.handle(name, inp, business_only=True)
    if name.startswith("web_"):
        return tools_web.run_tool(name, inp)
    if name.startswith("youtube_"):
        res = tools_youtube.handle(name, inp)
        _audit(namespace, actor, name, inp.get("url", ""), res[:200])
        return res
    if name.startswith("drive_"):
        res = tools_gdrive.handle(name, inp)
        if name in tools_gdrive.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("github_"):
        if name in tools_github.WRITE_NAMES:
            return f"denied: {name} is a GitHub write, withheld from the business scope"
        return tools_github.handle(name, inp)
    return _UNHANDLED


def _dispatch_allie(name: str, inp: dict, namespace: str, actor: str):
    """ALLIE's module routing — the gatekeeper rule enforced by the scope/business_only
    arguments, exactly as allie.py did inline."""
    from . import tools_anpu, tools_cappo, tools_clickup, tools_constance, tools_gdrive, tools_notion, tools_thoth, tools_vale, tools_youtube

    if name.startswith("clickup_"):
        res = tools_clickup.handle(name, inp, scope="business")
        if name in tools_clickup.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    if name.startswith("notion_"):
        return tools_notion.handle(name, inp, business_only=True)
    if name == "delegate_to_cappo":
        res = tools_cappo.handle(inp.get("task", ""))
        _audit(namespace, actor, "delegate_to_cappo", inp.get("task", ""), res)
        return res
    if name == "cappo_get_report":
        return tools_cappo.get_report()
    if name == "delegate_to_constance":
        res = tools_constance.handle(inp.get("task", ""))
        _audit(namespace, actor, "delegate_to_constance", inp.get("task", ""), res)
        return res
    if name == "constance_get_report":
        return tools_constance.get_report()
    if name == "delegate_to_vale":
        res = tools_vale.handle(inp.get("task", ""))
        _audit(namespace, actor, "delegate_to_vale", inp.get("task", ""), res)
        return res
    if name == "vale_get_report":
        return tools_vale.get_report()
    if name == "anpu_get_reviews":
        return tools_anpu.handle(name, inp)
    if name == "thoth_get_status":
        return tools_thoth.handle(name, inp)
    if name.startswith("youtube_"):
        res = tools_youtube.handle(name, inp)
        _audit(namespace, actor, name, inp.get("url", ""), res[:200])
        return res
    if name.startswith("drive_"):
        res = tools_gdrive.handle(name, inp)
        if name in tools_gdrive.WRITE_NAMES:
            _audit(namespace, actor, name, json.dumps(inp), res)
        return res
    return _UNHANDLED


_DISPATCHERS = {
    "allen": _dispatch_allen,
    "allen-business": _dispatch_allen_business,
    "allie": _dispatch_allie,
}


def dispatch(
    name: str,
    args: Optional[dict],
    *,
    scope: str,
    namespace: str,
    actor: str,
    fallback: Optional[Callable[[str, dict], str]] = None,
) -> str:
    """Execute one tool call and return its result text.

    Every call is wrapped: a raised exception or a fault-shaped result is recorded to the
    onboard error log, so a fault leaves a trail even if the model glosses over it. The
    HONESTY directive tells ALLEN to also surface it and never claim success.

    ``fallback`` handles names this scope's module routing doesn't own — ALLEN's built-ins
    live there because they need his per-turn closure (``conversation_id``, ALLIE handle).
    It is wrapped by the same fault capture, so built-ins are covered too.
    """
    if scope not in _DISPATCHERS:
        raise ValueError(f"unknown scope {scope!r} — expected one of {SCOPES}")
    inp = args or {}
    try:
        res = _DISPATCHERS[scope](name, inp, namespace, actor)
        if res is _UNHANDLED:
            res = fallback(name, inp) if fallback else f"(unknown tool: {name})"
    except Exception as exc:
        logger.error("[registry] tool %s raised: %s", name, exc)
        try:
            db.add_error(namespace, name, f"tool {name} raised an exception", f"{type(exc).__name__}: {exc}")
        except Exception:  # never let the error-log write mask the original fault
            pass
        from . import replies

        return replies.get("tool_error_generic", error=str(exc)[:200])
    if name not in _FAULT_EXEMPT and looks_like_fault(res):
        try:
            db.add_error(namespace, name, f"tool {name} reported a fault", (res or "")[:1000])
        except Exception:
            pass
    return res
