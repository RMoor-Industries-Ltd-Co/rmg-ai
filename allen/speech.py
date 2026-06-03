"""Speech layer — 'Express' (ElevenLabs TTS) and 'Listen' (Whisper STT).
TTS reuses the Creator OS ElevenLabs key. STT is optional (OpenAI Whisper API)."""

import requests

from .config import settings


def synthesize(text: str, voice_id: str | None = None) -> bytes:
    """Text -> spoken audio (mp3) in ALLEN's voice (default: COM Coach Rahm)."""
    vid = voice_id or settings.allen_voice_id
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
        headers={"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=120,
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
