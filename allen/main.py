from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

from . import brands, docs, scripts, speech
from .config import settings
from .models import DraftRequest, DraftResponse, HealthResponse, SpeakRequest

app = FastAPI(title="ALLEN", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    checks = {
        "llm": "ok" if settings.llm_ready else "unconfigured",
        "tts": "ok" if settings.tts_ready else "unconfigured",
        "stt": "ok" if settings.stt_ready else "unconfigured",
        "docs": "ok" if settings.docs_ready else "unconfigured",
    }
    return HealthResponse(status="ok" if settings.llm_ready else "degraded", checks=checks)


@app.get("/brands")
def get_brands() -> list[dict[str, str]]:
    return brands.list_brands()


@app.post("/draft", response_model=DraftResponse)
def draft(req: DraftRequest) -> DraftResponse:
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        title, script, model = scripts.generate_script(req)
    except Exception as exc:  # upstream LLM error
        raise HTTPException(502, f"LLM error: {exc}") from exc

    doc_id = doc_url = None
    if req.write_doc:
        if not settings.docs_ready:
            raise HTTPException(503, "Docs not configured (set GDRIVE_* + GDRIVE_SCRIPTS_FOLDER_ID)")
        try:
            doc_id, doc_url = docs.write_script_doc(title, script, req.brand, req.persona, req.output_kind)
        except Exception as exc:
            raise HTTPException(502, f"Drive/Docs error: {exc}") from exc

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


@app.post("/speak")
def speak(req: SpeakRequest) -> Response:
    if not settings.tts_ready:
        raise HTTPException(503, "TTS not configured (set ELEVENLABS_API_KEY)")
    try:
        audio = speech.synthesize(req.text, req.voice_id)
    except Exception as exc:
        raise HTTPException(502, f"TTS error: {exc}") from exc
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/listen")
async def listen(file: UploadFile = File(...)) -> dict[str, str]:
    if not settings.stt_ready:
        raise HTTPException(503, "STT not configured (set OPENAI_API_KEY)")
    audio = await file.read()
    try:
        text = speech.transcribe(audio, file.filename or "audio.wav")
    except Exception as exc:
        raise HTTPException(502, f"STT error: {exc}") from exc
    return {"text": text}
