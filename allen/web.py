"""ALLEN I VERSE console — the web/mobile front door. Google sign-in (single
authorized user) issues a signed session cookie; the console then talks to ALLEN
same-origin, so the API key never touches the browser."""

import base64
import hashlib
import hmac
import json
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import requests
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.responses import Response as RawResponse

from . import agent, classify, db, google_auth, media, memory, speech, tools_calendar, usage
from .config import settings

router = APIRouter()

SESSION_COOKIE = "av_session"
_STATIC = Path(__file__).parent / "static" / "console.html"


def _console_html() -> str:
    try:
        return _STATIC.read_text(encoding="utf-8")
    except Exception:
        return "<!doctype html><h1>ALLEN I VERSE</h1><p>console not built</p>"


def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(settings.cookie_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify(token: Optional[str]) -> Optional[dict]:
    if not token or not settings.cookie_secret:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(settings.cookie_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(body))
        if float(data.get("exp", 0)) < time.time():
            return None
        return data
    except Exception:
        return None


def _session_user(request: Request) -> dict:
    data = _verify(request.cookies.get(SESSION_COOKIE))
    if not data:
        raise HTTPException(401, "login required")
    return data


def _memory_context(namespace: str) -> Optional[str]:
    """ALLEN's full view — everything he remembers (see allen.memory for ALLIE's filtered view)."""
    return memory.allen_context(namespace)


_MEM_RE = re.compile(r"@@MEMORY\s*(\{[\s\S]*?\})\s*@@")


def _apply_memory_ops(namespace: str, reply: str) -> tuple[str, bool]:
    """Parse ALLEN's @@MEMORY ops out of a reply, classify adds into lane/silo, apply, and strip."""
    cleaned = re.sub(r"@@MEMORY[\s\S]*?@@", "", reply).strip()
    m = _MEM_RE.search(reply)
    if not m:
        return reply.strip(), False
    try:
        ops = json.loads(m.group(1)).get("ops", [])
    except Exception:
        return cleaned, False
    changed = False
    for o in ops:
        try:
            op = o.get("op")
            if op == "add" and (o.get("content") or "").strip():
                cls = classify.classify_memory(o["content"])
                db.add_memory(
                    namespace, o["content"].strip(), cls["lane"], cls["silo"], source="allen",
                    unit=cls.get("unit"), memory_class=cls.get("memory_class"), sensitivity=cls.get("sensitivity"),
                )
                changed = True
            elif op == "update" and o.get("id") and (o.get("content") or "").strip():
                # correction flow: supersede (keep audit trail), never silently overwrite
                db.supersede_memory(namespace, o["id"], o["content"].strip())
                changed = True
            elif op == "delete" and o.get("id"):
                # deletion flow: tombstone (or hard-delete session-class) inside db.delete_memory
                db.delete_memory(namespace, o["id"])
                changed = True
        except Exception:
            continue
    return cleaned, changed


# ---- the page ----
@router.get("/", response_class=HTMLResponse)
def console_page() -> str:
    return _console_html()


# ---- auth ----
@router.get("/auth/config")
def auth_config() -> dict:
    return {
        "clientId": settings.google_client_id,
        "enabled": bool(settings.google_client_id and settings.auth_allowed_email and settings.cookie_secret),
    }


@router.post("/auth/google")
def auth_google(body: dict, response: Response) -> dict:
    cred = (body or {}).get("credential", "")
    if not cred:
        raise HTTPException(400, "credential required")
    r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": cred}, timeout=10)
    if not r.ok:
        raise HTTPException(401, "invalid token")
    info = r.json()
    if info.get("aud") != settings.google_client_id:
        raise HTTPException(401, "token audience mismatch")
    allowed = {e.strip().lower() for e in settings.auth_allowed_email.split(",") if e.strip()}
    if (info.get("email") or "").lower() not in allowed:
        raise HTTPException(403, "that account is not authorized")
    if str(info.get("email_verified")).lower() != "true":
        raise HTTPException(403, "email not verified")
    token = _sign({"email": info["email"], "namespace": "atelier", "exp": time.time() + 7 * 86400})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=True, samesite="lax", max_age=7 * 86400, path="/")
    return {"ok": True, "email": info["email"]}


@router.get("/auth/me")
def auth_me(request: Request) -> dict:
    return {"email": _session_user(request)["email"]}


@router.post("/auth/logout")
def auth_logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ---- legacy single-account Calendar authorization (kept for backward compat) ----
@router.get("/oauth/calendar/start")
def calendar_start(request: Request):
    _session_user(request)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@router.get("/oauth/calendar/callback", response_class=HTMLResponse)
def calendar_callback(request: Request, code: str = "", error: str = "") -> str:
    _session_user(request)
    if error or not code:
        return f"<h3>Calendar authorization failed: {error or 'no code returned'}</h3>"
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "code": code,
            "redirect_uri": settings.google_oauth_redirect,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if not r.ok:
        return f"<h3>Token exchange failed: {r.text[:300]}</h3>"
    rt = r.json().get("refresh_token")
    if not rt:
        return "<h3>No refresh token returned. Revoke ALLEN's access in your Google account and retry.</h3>"
    db.set_config("google_calendar_refresh_token", rt)
    return "<h3>✅ Calendar connected. ALLEN can now manage your calendar. You can close this tab.</h3>"


# ---- unified multi-account Google authorization (Calendar + Gmail + Drive) ----
@router.get("/oauth/google/start")
def google_start(request: Request, account: str = ""):
    _session_user(request)
    if not account:
        account = google_auth.default_account()
    # Encode account in state so the callback knows where to store the token
    state = base64.urlsafe_b64encode(account.encode()).decode()
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_unified_redirect,
        "response_type": "code",
        "scope": google_auth.UNIFIED_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "login_hint": account,
        "state": state,
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@router.get("/oauth/google/callback", response_class=HTMLResponse)
def google_callback(request: Request, code: str = "", error: str = "", state: str = "") -> str:
    _session_user(request)
    if error or not code:
        return f"<h3>Google authorization failed: {error or 'no code returned'}</h3>"
    try:
        account = base64.urlsafe_b64decode(state + "==").decode()
    except Exception:
        account = google_auth.default_account()
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "code": code,
            "redirect_uri": settings.google_oauth_unified_redirect,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if not r.ok:
        return f"<h3>Token exchange failed: {r.text[:300]}</h3>"
    rt = r.json().get("refresh_token")
    if not rt:
        return (
            "<h3>No refresh token returned. "
            "Revoke ALLEN's access for this account in Google Account settings and retry.</h3>"
        )
    google_auth.store_refresh_token(account, rt)
    connected = google_auth.connected_accounts()
    remaining = [
        a for a in google_auth.KNOWN_ACCOUNTS if a not in connected
    ]
    next_hint = ""
    if remaining:
        next_account = remaining[0]
        next_hint = (
            f"<p>Next: authorize <strong>{next_account}</strong> at "
            f"<a href='/oauth/google/start?account={next_account}'>"
            f"/oauth/google/start?account={next_account}</a></p>"
        )
    return (
        f"<h3>✅ {account} connected — Calendar, Gmail, and Drive authorized.</h3>"
        f"<p>Connected accounts: {len(connected)} / {len(google_auth.KNOWN_ACCOUNTS)}</p>"
        + next_hint
    )


# ---- console (session-gated; namespace comes from the session) ----
@router.post("/console/chat")
def console_chat(body: dict, request: Request) -> dict:
    user = _session_user(request)
    ns = user["namespace"]
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured")
    msg = ((body or {}).get("message") or "").strip()
    if not msg:
        raise HTTPException(400, "message required")
    conv_id = (body or {}).get("conversationId")
    title = None
    if db.db_ready():
        if not (conv_id and db.get_conversation(ns, conv_id)):
            folder = (body or {}).get("folder") or "General"
            title = msg[:48] + ("…" if len(msg) > 48 else "")
            conv_id = db.create_conversation(ns, folder, title)["id"]
        history = [{"role": m["role"], "content": m["content"]} for m in db.get_messages(conv_id)][-12:]
        db.add_message(conv_id, "user", msg)
    else:
        history = (body or {}).get("history", [])
    context = _memory_context(ns)
    now = (body or {}).get("now")
    if now:
        context = f"Current date and time (Rahm's local): {now}" + (("\n\n" + context) if context else "")
    model_override = (body or {}).get("model") or None
    # ALLEN answers; he may delegate operational legwork to ALLIE behind the scenes (agentic).
    try:
        raw = agent.respond_agentic(msg, history, context, ns, max_tokens=900, model=model_override)
    except Exception as exc:
        raise HTTPException(500, f"ALLEN encountered an error: {exc}") from exc
    reply, changed = _apply_memory_ops(ns, raw)
    if db.db_ready() and conv_id:
        db.add_message(conv_id, "assistant", reply)
    return {"reply": reply, "memoryChanged": changed, "conversationId": conv_id, "title": title}


@router.get("/console/conversations")
def list_conversations_ep(request: Request) -> dict:
    user = _session_user(request)
    return {"conversations": db.list_conversations(user["namespace"]) if db.db_ready() else []}


@router.post("/console/conversations")
def new_conversation_ep(body: dict, request: Request) -> dict:
    user = _session_user(request)
    if not db.db_ready():
        raise HTTPException(503, "DB not configured")
    return db.create_conversation(
        user["namespace"], (body or {}).get("folder") or "General", (body or {}).get("title") or "New chat"
    )


@router.get("/console/conversations/{cid}")
def get_conversation_ep(cid: str, request: Request) -> dict:
    user = _session_user(request)
    if not db.db_ready():
        return {"messages": []}
    conv = db.get_conversation(user["namespace"], cid)
    if not conv:
        raise HTTPException(404, "not found")
    return {"conversation": conv, "messages": db.get_messages(cid)}


@router.patch("/console/conversations/{cid}")
def patch_conversation_ep(cid: str, body: dict, request: Request) -> dict:
    user = _session_user(request)
    if db.db_ready():
        db.rename_conversation(user["namespace"], cid, (body or {}).get("title"), (body or {}).get("folder"))
    return {"ok": True}


@router.delete("/console/conversations/{cid}")
def delete_conversation_ep(cid: str, request: Request) -> dict:
    user = _session_user(request)
    if db.db_ready():
        db.delete_conversation(user["namespace"], cid)
    return {"ok": True}


# ---- inspiration (home-screen greeting; rate 0-3 thumbs to weight future appearances) ----
@router.get("/console/inspiration")
def inspiration_ep(request: Request) -> dict:
    user = _session_user(request)
    if not db.db_ready():
        return {"id": None, "text": "Make today count.", "rating": 2}
    return db.random_inspiration(user["namespace"]) or {"id": None, "text": "Make today count.", "rating": 2}


@router.post("/console/inspiration/{iid}/rate")
def rate_inspiration_ep(iid: str, body: dict, request: Request) -> dict:
    user = _session_user(request)
    if db.db_ready():
        db.rate_inspiration(user["namespace"], iid, int((body or {}).get("rating", 0)))
    return {"ok": True}


@router.post("/console/inspiration")
def add_inspiration_ep(body: dict, request: Request) -> dict:
    user = _session_user(request)
    text = ((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    if not db.db_ready():
        raise HTTPException(503, "DB not configured")
    return {"id": db.add_inspiration(user["namespace"], text)}


@router.post("/console/speak")
def console_speak(body: dict, request: Request) -> RawResponse:
    user = _session_user(request)
    if not settings.tts_ready:
        raise HTTPException(503, "TTS not configured")
    audio = speech.synthesize((body or {}).get("text", ""), namespace=user["namespace"], feature="tts")
    return RawResponse(content=audio, media_type="audio/mpeg")


@router.post("/console/listen")
async def console_listen(request: Request, file: UploadFile = File(...)) -> dict:
    user = _session_user(request)
    if not settings.stt_ready:
        raise HTTPException(503, "STT not configured")
    audio = await file.read()
    text = speech.transcribe(audio, file.filename or "audio.webm", namespace=user["namespace"], feature="dictate")
    return {"text": text}


@router.get("/console/usage")
def console_usage(request: Request, days: int = 30) -> dict:
    """Data source for the "$" dashboard panel — session-gated same as the rest of the
    console (no separate admin key needed; the console is already single-user-gated)."""
    _session_user(request)
    return usage.dashboard(days=days)


@router.post("/console/attach")
async def console_attach(
    request: Request,
    files: list[UploadFile] = File(...),
    message: str = Form(""),
    conversationId: str = Form(None),
) -> dict:
    """Rahm stages up to MAX_ATTACH_FILES files in one turn. ALLEN reads/sees/hears each, then
    synthesises a single reply across all of them. Exchange saved into the conversation."""
    user = _session_user(request)
    ns = user["namespace"]
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured")
    if not files:
        raise HTTPException(400, "no files")
    if len(files) > settings.max_attach_files:
        raise HTTPException(413, f"Too many files — max {settings.max_attach_files} per turn")

    ctx = _memory_context(ns)
    results = []
    fnames = []
    for upload in files:
        data = await upload.read()
        if not data:
            continue
        if len(data) > settings.max_upload_bytes:
            mb = settings.max_upload_bytes // (1024 * 1024)
            raise HTTPException(413, f"'{upload.filename}' exceeds the {mb} MB upload limit")
        fname = upload.filename or "file"
        fnames.append(fname)
        result = media.analyze(data, fname, None, context=ctx)
        results.append((fname, result))

    if not results:
        raise HTTPException(400, "all files were empty")

    note = (message or "").strip()
    if len(results) == 1:
        fname, result = results[0]
        reply = result["analysis"]
        if note:
            # Let ALLEN factor the user's note into a follow-up synthesis
            try:
                follow = agent.respond_agentic(
                    f"[Regarding {fname} I just shared] {note}",
                    [{"role": "user", "content": f"📎 {fname}"}, {"role": "assistant", "content": reply}],
                    ctx, ns, max_tokens=900,
                )
            except Exception as exc:
                raise HTTPException(500, f"ALLEN encountered an error: {exc}") from exc
            reply, _ = _apply_memory_ops(ns, follow)
        kind = result["kind"]
    else:
        # Multi-file: build a combined analysis turn
        combined = "\n\n---\n\n".join(
            f"**{fn}** ({r['kind']}):\n{r['analysis']}" for fn, r in results
        )
        prompt = (note or "Summarise all these files together.") + "\n\n" + combined
        try:
            raw = agent.respond_agentic(prompt, [], ctx, ns, max_tokens=1200)
        except Exception as exc:
            raise HTTPException(500, f"ALLEN encountered an error: {exc}") from exc
        reply, _ = _apply_memory_ops(ns, raw)
        kind = "multi"

    conv_id = conversationId
    title = None
    if db.db_ready():
        if not (conv_id and db.get_conversation(ns, conv_id)):
            label = ", ".join(fnames[:2]) + ("…" if len(fnames) > 2 else "")
            title = (note or f"Shared {label}")[:48]
            conv_id = db.create_conversation(ns, "General", title)["id"]
        shared_label = "📎 " + ", ".join(fnames) + (f" — {note}" if note else "")
        db.add_message(conv_id, "user", shared_label)
        db.add_message(conv_id, "assistant", reply)
    return {"reply": reply, "kind": kind, "filenames": fnames, "conversationId": conv_id, "title": title}


# Available models for the quick-switch picker
_MODELS = [
    {"id": "claude-sonnet-4-6",  "label": "Sonnet 4.6",  "note": "default — fast & capable"},
    {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5", "note": "fastest / lowest cost"},
    {"id": "claude-opus-4-8",    "label": "Opus 4.8",    "note": "most powerful — higher cost"},
    {"id": "claude-fable-5",     "label": "Fable 5",     "note": "latest generation"},
]

@router.get("/console/models")
def console_models(request: Request) -> dict:
    _session_user(request)
    return {"models": _MODELS, "default": settings.anthropic_model}


@router.get("/console/memory")
def console_get_memory(request: Request) -> dict:
    user = _session_user(request)
    return {"memories": db.list_memories(user["namespace"]) if db.db_ready() else []}


@router.post("/console/memory")
def console_add_memory(body: dict, request: Request) -> dict:
    user = _session_user(request)
    if not db.db_ready():
        raise HTTPException(503, "DB not configured")
    content = ((body or {}).get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content required")
    # Honour an explicit lane/silo, else let ALLEN classify it.
    lane = (body or {}).get("lane")
    silo = (body or {}).get("silo")
    unit = (body or {}).get("unit")
    cls = classify.classify_memory(content)
    if not lane:
        lane, silo, unit = cls["lane"], cls["silo"], cls.get("unit")
    # a memory added by hand in the console is a direct statement from Rahm
    return db.add_memory(
        user["namespace"], content, lane, silo, source="rahm_direct", unit=unit,
        memory_class=cls.get("memory_class"), sensitivity=cls.get("sensitivity"),
    )


@router.delete("/console/memory/{mem_id}")
def console_del_memory(mem_id: str, request: Request) -> dict:
    user = _session_user(request)
    if db.db_ready():
        db.delete_memory(user["namespace"], mem_id)
    return {"ok": True}


@router.post("/console/memory/{mem_id}/pin")
def console_pin_memory(mem_id: str, body: dict, request: Request) -> dict:
    user = _session_user(request)
    if db.db_ready():
        db.set_pinned(user["namespace"], mem_id, bool((body or {}).get("pinned", True)))
    return {"ok": True}
