import logging

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response, PlainTextResponse

from . import brands, chat, db, docs, emotion, meeting, metadata, scheduler, scripts, speech, topics, web
from .config import settings
from .models import (
    ChatRequest,
    ChatResponse,
    CreateProjectRequest,
    DirectRequest,
    DirectResponse,
    DraftRequest,
    DraftResponse,
    HealthResponse,
    MeetingRequest,
    MeetingResponse,
    MemoryRequest,
    MemoryUpdateRequest,
    MetadataRequest,
    MetadataResponse,
    SpeakRequest,
    TopicsRequest,
    TopicsResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="ALLEN", version="0.1.0")
app.include_router(web.router)

from pathlib import Path as _Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_static_dir = _Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.on_event("startup")
def _startup() -> None:
    if db.db_ready():
        try:
            db.init_db()
            db.seed_default()
        except Exception as exc:  # don't crash the brain if the DB is slow to come up
            print(f"[allen] DB init deferred: {exc}")
    scheduler.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    scheduler.stop()


def require_key(x_allen_key: str | None = Header(default=None)) -> None:
    """Guard credit-consuming endpoints. Open if ALLEN_API_KEY is unset."""
    if settings.allen_api_key and x_allen_key != settings.allen_api_key:
        raise HTTPException(401, "invalid or missing x-allen-key")


def current_project(x_allen_key: str | None = Header(default=None)) -> dict:
    """Resolve the caller's API key to a project + namespace (multi-tenant)."""
    if db.db_ready():
        proj = db.project_by_key(x_allen_key or "")
        if proj:
            return proj
        # fall back to the shared key as the default 'atelier' project
        if settings.allen_api_key and x_allen_key == settings.allen_api_key:
            return {"id": "proj-atelier", "name": "Master Atelier", "namespace": "atelier"}
        raise HTTPException(401, "invalid or missing API key")
    # stateless mode: single shared key, one namespace
    if settings.allen_api_key and x_allen_key != settings.allen_api_key:
        raise HTTPException(401, "invalid or missing API key")
    return {"id": "proj-default", "name": "default", "namespace": "default"}


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(401, "admin key required")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    checks = {
        "llm": "ok" if settings.llm_ready else "unconfigured",
        "tts": "ok" if settings.tts_ready else "unconfigured",
        "stt": "ok" if settings.stt_ready else "unconfigured",
        "docs": "ok" if settings.docs_ready else "unconfigured",
        "db": "ok" if settings.database_url else "unconfigured",
        "whatsapp": "ok" if settings.whatsapp_ready else "unconfigured",
    }
    return HealthResponse(status="ok" if settings.llm_ready else "degraded", checks=checks)


# ---- platform: identity, projects, namespaced memory ----
@app.get("/me")
def me(project: dict = Depends(current_project)) -> dict:
    return {"project": project["name"], "namespace": project["namespace"]}


@app.post("/projects", dependencies=[Depends(require_admin)])
def create_project_ep(req: CreateProjectRequest) -> dict:
    if not db.db_ready():
        raise HTTPException(503, "platform DB not configured")
    ns = "".join(c for c in req.namespace.lower() if c.isalnum() or c in "-_")
    if not ns:
        raise HTTPException(400, "namespace must be alphanumeric")
    try:
        return db.create_project(req.name, ns)
    except Exception as exc:
        raise HTTPException(400, f"could not create project (name/namespace taken?): {exc}") from exc


@app.get("/projects", dependencies=[Depends(require_admin)])
def list_projects_ep() -> dict:
    return {"projects": db.list_projects() if db.db_ready() else []}


@app.get("/memory")
def get_memory(project: dict = Depends(current_project)) -> dict:
    if not db.db_ready():
        return {"namespace": project["namespace"], "memories": []}
    return {"namespace": project["namespace"], "memories": db.list_memories(project["namespace"])}


@app.post("/memory")
def post_memory(req: MemoryRequest, project: dict = Depends(current_project)) -> dict:
    if not db.db_ready():
        raise HTTPException(503, "platform DB not configured")
    return db.add_memory(project["namespace"], req.content, brand=req.brand)


@app.put("/memory/{mem_id}")
def put_memory(mem_id: str, req: MemoryUpdateRequest, project: dict = Depends(current_project)) -> dict:
    if not db.db_ready():
        raise HTTPException(503, "platform DB not configured")
    db.update_memory(project["namespace"], mem_id, req.content)
    return {"ok": True}


@app.delete("/memory/{mem_id}")
def delete_memory(mem_id: str, project: dict = Depends(current_project)) -> dict:
    if not db.db_ready():
        raise HTTPException(503, "platform DB not configured")
    db.delete_memory(project["namespace"], mem_id)
    return {"ok": True}


@app.get("/brands")
def get_brands() -> list[dict[str, str]]:
    return brands.list_brands()


@app.get("/emotion/profiles")
def emotion_profiles() -> dict:
    """Per-brand emotion profiles + tag rules (for the Voice Direction UI). No credits."""
    return emotion.profiles()


@app.post("/draft", response_model=DraftResponse, dependencies=[Depends(require_key)])
def draft(req: DraftRequest) -> DraftResponse:
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        title, script, model = scripts.generate_script(req)
    except Exception as exc:  # upstream LLM error
        raise HTTPException(502, f"LLM error: {exc}") from exc

    doc_id = doc_url = None
    if req.write_doc and settings.docs_ready:
        try:
            doc_id, doc_url = docs.write_script_doc(title, script, req.brand, req.persona, req.output_kind)
        except Exception as exc:
            logger.warning("[draft] Drive/Docs write failed (non-fatal): %s", exc)

    return DraftResponse(
        brand=req.brand,
        persona=req.persona,
        output_kind=req.output_kind,
        title=title,
        script=script,
        doc_url=doc_url,
        doc_id=doc_id,
        model=model,
    )


@app.post("/direct", response_model=DirectResponse, dependencies=[Depends(require_key)])
def direct(req: DirectRequest) -> DirectResponse:
    """Emotion Director: annotate an approved script with v3 audio tags + emphasis +
    pauses, and recommend a stability mode, in the brand's emotional register."""
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        result = emotion.direct(
            req.script, req.brand, req.persona, req.intensity, req.stability_mode,
            brand_examples=req.brand_examples, version=req.version,
        )
    except Exception as exc:
        raise HTTPException(502, f"Emotion Director error: {exc}") from exc
    return DirectResponse(**result)


@app.post("/meeting", response_model=MeetingResponse, dependencies=[Depends(require_key)])
def post_meeting(req: MeetingRequest) -> MeetingResponse:
    """ALLEN Transcriber: distill a transcript into summary + action items + highlights."""
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        result = meeting.summarize(req.transcript, req.brand)
    except Exception as exc:
        raise HTTPException(502, f"meeting error: {exc}") from exc
    return MeetingResponse(**result)


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_key)])
def post_chat(req: ChatRequest) -> ChatResponse:
    """Talk to ALLEN. Reply is written to be spoken aloud (pair with /speak)."""
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        reply = chat.respond(
            req.message,
            req.brand,
            req.persona,
            [m.model_dump() for m in req.history],
            req.max_tokens,
            req.context,
        )
    except Exception as exc:
        raise HTTPException(502, f"chat error: {exc}") from exc
    return ChatResponse(reply=reply)


@app.post("/topics", response_model=TopicsResponse, dependencies=[Depends(require_key)])
def post_topics(req: TopicsRequest) -> TopicsResponse:
    """ALLIE: suggested next topics per brand (grounded in brand voice; context-aware)."""
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        items = topics.suggest(req.brand, req.count, req.context)
    except Exception as exc:
        raise HTTPException(502, f"topics error: {exc}") from exc
    return TopicsResponse(topics=items)


@app.post("/metadata", response_model=MetadataResponse, dependencies=[Depends(require_key)])
def post_metadata(req: MetadataRequest) -> MetadataResponse:
    """ALLIE v1: suggested post metadata (caption, hashtags, first comment, audience, title)."""
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        result = metadata.suggest(req.brand, req.persona, req.topic, req.script, req.platform)
    except Exception as exc:
        raise HTTPException(502, f"metadata error: {exc}") from exc
    return MetadataResponse(**result)


@app.post("/speak", dependencies=[Depends(require_key)])
def speak(req: SpeakRequest) -> Response:
    if not settings.tts_ready:
        raise HTTPException(503, "TTS not configured (set ELEVENLABS_API_KEY)")
    try:
        audio = speech.synthesize(req.text, req.voice_id, req.model_id, req.stability)
    except Exception as exc:
        raise HTTPException(502, f"TTS error: {exc}") from exc
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/listen", dependencies=[Depends(require_key)])
async def listen(file: UploadFile = File(...)) -> dict[str, str]:
    if not settings.stt_ready:
        raise HTTPException(503, "STT not configured (set OPENAI_API_KEY)")
    audio = await file.read()
    try:
        text = speech.transcribe(audio, file.filename or "audio.wav")
    except Exception as exc:
        raise HTTPException(502, f"STT error: {exc}") from exc
    return {"text": text}


@app.post("/whatsapp/inbound")
async def whatsapp_inbound(request: Request) -> PlainTextResponse:
    """Receive inbound WhatsApp messages from Twilio.

    Validates the sender is the authorized number, then processes the message
    asynchronously and replies via the Twilio REST API. Returns empty TwiML
    immediately so Twilio doesn't time out waiting for the agent.
    """
    from . import agent, whatsapp

    form = await request.form()
    from_ = str(form.get("From", ""))
    body = str(form.get("Body", "")).strip()

    authorized = whatsapp.is_authorized(from_)
    logger.info("[whatsapp/inbound] from=%r body=%r authorized=%s", from_, body[:80], authorized)

    if not authorized:
        logger.warning(
            "[whatsapp/inbound] rejected — expected %r got %r",
            settings.twilio_whatsapp_to,
            from_,
        )
        return PlainTextResponse("<Response/>", media_type="text/xml")

    def _handle(text: str) -> str:
        return agent.respond_agentic(
            message=text,
            history=[],
            context="Message received via WhatsApp.",
            namespace="atelier",
            max_tokens=900,
        )

    whatsapp.reply_async(body, _handle)
    return PlainTextResponse("<Response/>", media_type="text/xml")


@app.post("/whatsapp/test", dependencies=[Depends(require_admin)])
def whatsapp_test() -> dict:
    """Send a test WhatsApp message to the configured recipient. Admin-only."""
    from . import whatsapp

    if not settings.whatsapp_ready:
        raise HTTPException(503, "WhatsApp not configured — check TWILIO_* env vars")
    try:
        whatsapp.send_message("🔔 ALLEN test message — WhatsApp bridge is working.")
        return {"ok": True, "to": settings.twilio_whatsapp_to}
    except Exception as exc:
        raise HTTPException(502, f"send failed: {exc}") from exc
