from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response

from . import brands, docs, emotion, scripts, speech
from .config import settings
from .models import (
    DirectRequest,
    DirectResponse,
    DraftRequest,
    DraftResponse,
    HealthResponse,
    SpeakRequest,
)

app = FastAPI(title="ALLEN", version="0.1.0")


def require_key(x_allen_key: str | None = Header(default=None)) -> None:
    """Guard credit-consuming endpoints. Open if ALLEN_API_KEY is unset."""
    if settings.allen_api_key and x_allen_key != settings.allen_api_key:
        raise HTTPException(401, "invalid or missing x-allen-key")


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


@app.post("/direct", response_model=DirectResponse, dependencies=[Depends(require_key)])
def direct(req: DirectRequest) -> DirectResponse:
    """Emotion Director: annotate an approved script with v3 audio tags + emphasis +
    pauses, and recommend a stability mode, in the brand's emotional register."""
    if not settings.llm_ready:
        raise HTTPException(503, "LLM not configured (set ANTHROPIC_API_KEY)")
    try:
        result = emotion.direct(
            req.script, req.brand, req.persona, req.intensity, req.stability_mode
        )
    except Exception as exc:
        raise HTTPException(502, f"Emotion Director error: {exc}") from exc
    return DirectResponse(**result)


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
