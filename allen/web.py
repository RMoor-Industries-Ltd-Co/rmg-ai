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
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.responses import Response as RawResponse

from . import chat, classify, db, speech
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
    """Memories grouped by lane → silo (with ids) so ALLEN can use the lane relevant to the topic."""
    if not db.db_ready():
        return None
    mems = db.list_memories(namespace)
    if not mems:
        return None
    lanes: "OrderedDict[str, OrderedDict[str, list]]" = OrderedDict()
    for m in mems:
        lane = (m.get("lane") or "personal").upper()
        silo = m.get("silo") or "general"
        lanes.setdefault(lane, OrderedDict()).setdefault(silo, []).append(m)
    out = ["What you remember about Rahm — use the lane and silo relevant to what he's talking about:"]
    for lane, silos in lanes.items():
        out.append(lane)
        for silo, items in silos.items():
            for m in items:
                out.append(f"  [{silo} | id:{m['id']}] {m['content']}")
    return "\n".join(out)


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
                db.add_memory(namespace, o["content"].strip(), cls["lane"], cls["silo"], source="allen")
                changed = True
            elif op == "update" and o.get("id") and (o.get("content") or "").strip():
                db.update_memory(namespace, o["id"], o["content"].strip())
                changed = True
            elif op == "delete" and o.get("id"):
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


# ---- console (session-gated; namespace comes from the session) ----
@router.post("/console/chat")
def console_chat(body: dict, request: Request) -> dict:
    user = _session_user(request)
    ns = user["namespace"]
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured")
    context = _memory_context(ns)
    raw = chat.respond(
        (body or {}).get("message", ""),
        (body or {}).get("brand"),
        None,
        (body or {}).get("history", []),
        700,
        context,
    )
    reply, changed = _apply_memory_ops(ns, raw)
    return {"reply": reply, "memoryChanged": changed}


@router.post("/console/speak")
def console_speak(body: dict, request: Request) -> RawResponse:
    _session_user(request)
    if not settings.tts_ready:
        raise HTTPException(503, "TTS not configured")
    audio = speech.synthesize((body or {}).get("text", ""))
    return RawResponse(content=audio, media_type="audio/mpeg")


@router.post("/console/listen")
async def console_listen(request: Request, file: UploadFile = File(...)) -> dict:
    _session_user(request)
    if not settings.stt_ready:
        raise HTTPException(503, "STT not configured")
    audio = await file.read()
    return {"text": speech.transcribe(audio, file.filename or "audio.webm")}


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
    if not lane:
        cls = classify.classify_memory(content)
        lane, silo = cls["lane"], cls["silo"]
    return db.add_memory(user["namespace"], content, lane, silo)


@router.delete("/console/memory/{mem_id}")
def console_del_memory(mem_id: str, request: Request) -> dict:
    user = _session_user(request)
    if db.db_ready():
        db.delete_memory(user["namespace"], mem_id)
    return {"ok": True}
