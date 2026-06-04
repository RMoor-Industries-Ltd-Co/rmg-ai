"""Speech layer — 'Express' (ElevenLabs TTS) and 'Listen' (Whisper STT).
TTS reuses the Creator OS ElevenLabs key. STT is optional (OpenAI Whisper API)."""

import requests

from .config import settings


def synthesize(
    text: str,
    voice_id: str | None = None,
    model_id: str | None = None,
    stability: float | None = None,
) -> bytes:
    """Text -> spoken audio (mp3). Pass model_id='eleven_v3' for audio-tag emotion,
    and a stability (0.0 Creative / 0.5 Natural / 1.0 Robust)."""
    vid = voice_id or settings.allen_voice_id
    body: dict = {"text": text, "model_id": model_id or "eleven_multilingual_v2"}
    if stability is not None:
        body["voice_settings"] = {"stability": stability}
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
        headers={"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    resp.raise_for_status()
    return resp.content


def transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Spoken audio -> text via OpenAI Whisper API (optional)."""
    if not settings.stt_ready:
        raise RuntimeError("STT not configured (set OPENAI_API_KEY)")
    resp = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        files={"file": (filename, audio_bytes)},
        data={"model": "whisper-1"},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("text", "")
