"""Speech layer — 'Express' (ElevenLabs TTS) and 'Listen' (Whisper STT).
TTS reuses the Creator OS ElevenLabs key. STT is optional (OpenAI Whisper API)."""

import requests

from .config import settings


def synthesize(
    text: str,
    voice_id: str | None = None,
    model_id: str | None = None,
    stability: float | None = None,
    *,
    project: str = "rmg-ai",
    namespace: str = "",
    feature: str = "tts",
) -> bytes:
    """Text -> spoken audio (mp3). Pass model_id='eleven_v3' for audio-tag emotion,
    and a stability (0.0 Creative / 0.5 Natural / 1.0 Robust)."""
    vid = voice_id or settings.allen_voice_id
    model = model_id or "eleven_multilingual_v2"
    body: dict = {"text": text, "model_id": model}
    if stability is not None:
        body["voice_settings"] = {"stability": stability}
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
        headers={"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    if not resp.ok:
        _record_failure(project, "elevenlabs", f"[{resp.status_code}] {resp.text[:300]}")
        resp.raise_for_status()
    try:
        from . import usage

        usage.log_tts(len(text), model, project=project, namespace=namespace, feature=feature)
    except Exception:
        pass  # usage tracking must never break the actual synthesis
    _clear_failure(project, "elevenlabs")
    return resp.content


def _record_failure(project: str, usage_provider: str, message: str) -> None:
    """So a currently-broken metered account (quota exhausted, revoked key, ...) shows up
    in the "$" dashboard even before/without a new usage_log row — that table only records
    successful calls, so a blocked account with prior history would otherwise still read
    as healthy."""
    try:
        from . import tech_accounts

        tech_accounts.record_error(project, usage_provider, message)
    except Exception:
        pass  # dashboard error tracking must never break the actual call's own error handling


def _clear_failure(project: str, usage_provider: str) -> None:
    try:
        from . import tech_accounts

        tech_accounts.clear_error(project, usage_provider)
    except Exception:
        pass


def transcribe(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    *,
    project: str = "rmg-ai",
    namespace: str = "",
    feature: str = "dictate",
) -> str:
    """Spoken audio -> text via OpenAI Whisper API (optional)."""
    if not settings.stt_ready:
        raise RuntimeError("STT not configured (set OPENAI_API_KEY)")
    resp = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        files={"file": (filename, audio_bytes)},
        data={"model": "whisper-1", "response_format": "verbose_json"},
        timeout=120,
    )
    if not resp.ok:
        # OpenAI's actual error (rate_limit_exceeded vs insufficient_quota vs invalid key, etc.)
        # lives in the JSON body — raise_for_status() alone discards it.
        try:
            detail = resp.json().get("error", {})
            msg = detail.get("message") or resp.text[:300]
            code = detail.get("code") or resp.status_code
        except Exception:
            msg, code = resp.text[:300], resp.status_code
        _record_failure(project, "openai", f"[{code}] {msg}")
        raise RuntimeError(f"OpenAI Whisper error [{code}]: {msg}")
    data = resp.json()
    try:
        from . import usage

        usage.log_stt(float(data.get("duration") or 0), project=project, namespace=namespace, feature=feature)
    except Exception:
        pass  # usage tracking must never break the actual transcription
    _clear_failure(project, "openai")
    return data.get("text", "")
