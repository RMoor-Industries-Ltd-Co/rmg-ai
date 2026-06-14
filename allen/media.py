"""Multimodal analysis — ALLEN reads, analyzes, and interprets the media Rahm shares:
images and photos (vision), PDFs and documents (read), audio (transcribe), and video
(sampled frames + audio transcript). Returns ALLEN's interpretation in his own voice."""

import base64
import os
import subprocess
import tempfile

from .llm import get_llm
from . import speech

IMAGE_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp",
}
AUDIO_EXT = {"mp3", "wav", "m4a", "ogg", "oga", "flac", "aac", "webm"}
VIDEO_EXT = {"mp4", "mov", "mkv", "avi", "webm", "m4v"}
TEXT_EXT = {"txt", "md", "markdown", "csv", "tsv", "json", "log", "rtf", "html", "xml", "yaml", "yml"}

_SYSTEM = (
    "You are ALLEN, Rahm's Chief of Staff. Rahm has shared a file with you. Read, analyze, and "
    "interpret it clearly and usefully: say what it is, what it shows or contains, what stands out, "
    "and anything Rahm should notice, decide, or do. Be specific and decisive — no fluff. If it is "
    "business or brand material, relate it to the right world (RMG, RMI, a specific brand) when obvious. "
    "Plain prose, tight. If something is unclear or unreadable, say so honestly rather than guessing."
)


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _img_block(data: bytes, mime: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": _b64(data)}}


def _ffmpeg_available() -> bool:
    from shutil import which

    return which("ffmpeg") is not None


def _video_frames_and_audio(data: bytes, ext: str, max_frames: int = 6) -> tuple[list[bytes], str]:
    """Sample up to max_frames evenly across the video, and pull an audio transcript."""
    frames: list[bytes] = []
    transcript = ""
    with tempfile.TemporaryDirectory() as d:
        inp = os.path.join(d, f"in.{ext}")
        with open(inp, "wb") as fh:
            fh.write(data)
        # duration via ffprobe (fallback to a fixed sampling rate if unavailable)
        dur = 0.0
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", inp],
                capture_output=True, text=True, timeout=30,
            )
            dur = float((out.stdout or "0").strip() or 0)
        except Exception:
            dur = 0.0
        fps = (max_frames / dur) if dur > 1 else 1.0
        try:
            subprocess.run(
                ["ffmpeg", "-i", inp, "-vf", f"fps={fps:.4f}", "-frames:v", str(max_frames),
                 "-q:v", "4", os.path.join(d, "f_%02d.jpg")],
                capture_output=True, timeout=120,
            )
            for name in sorted(os.listdir(d)):
                if name.startswith("f_") and name.endswith(".jpg"):
                    with open(os.path.join(d, name), "rb") as fh:
                        frames.append(fh.read())
        except Exception:
            pass
        # audio -> wav -> Whisper (best-effort)
        if speech_ready():
            try:
                wav = os.path.join(d, "a.wav")
                subprocess.run(
                    ["ffmpeg", "-i", inp, "-vn", "-ac", "1", "-ar", "16000", wav],
                    capture_output=True, timeout=120,
                )
                if os.path.exists(wav) and os.path.getsize(wav) > 2000:
                    with open(wav, "rb") as fh:
                        transcript = speech.transcribe(fh.read(), "audio.wav")
            except Exception:
                transcript = ""
    return frames[:max_frames], transcript


def speech_ready() -> bool:
    from .config import settings

    return settings.stt_ready


def _extract_text(data: bytes, ext: str) -> str:
    if ext == "docx":
        try:
            import io
            from docx import Document  # python-docx

            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return ""
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def analyze(data: bytes, filename: str, note: str | None = None, context: str | None = None) -> dict:
    """Route a shared file to the right modality and return ALLEN's interpretation.
    `context` (ALLEN's memories) grounds the analysis in what he knows about Rahm's worlds."""
    ext = _ext(filename)
    system = _SYSTEM
    if context:
        system += "\n\nWHAT YOU KNOW (use it — e.g. brand names like COM, VLOG, RMI):\n" + context[:3500]
    ask = (note or "").strip() or "Tell me what this is, what it shows, and anything important."
    blocks: list = []
    kind = "document"

    if ext in IMAGE_MIME:
        kind = "image"
        blocks = [{"type": "text", "text": ask}, _img_block(data, IMAGE_MIME[ext])]
    elif ext == "pdf":
        kind = "pdf"
        blocks = [
            {"type": "text", "text": ask},
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": _b64(data)}},
        ]
    elif ext in AUDIO_EXT and ext not in VIDEO_EXT:
        kind = "audio"
        if not speech_ready():
            return {"kind": kind, "analysis": "I can't transcribe audio yet — speech-to-text isn't configured on my server."}
        transcript = speech.transcribe(data, filename)
        blocks = [{"type": "text", "text": f"{ask}\n\nHere is the transcript of the audio:\n{transcript[:12000]}"}]
    elif ext in VIDEO_EXT:
        kind = "video"
        if not _ffmpeg_available():
            return {"kind": kind, "analysis": "I can't process video yet — the video toolkit (ffmpeg) isn't installed on my server."}
        frames, transcript = _video_frames_and_audio(data, ext)
        if not frames and not transcript:
            return {"kind": kind, "analysis": "I couldn't read that video — it may be an unsupported codec or corrupted."}
        head = ask + (f"\n\nAudio transcript:\n{transcript[:8000]}" if transcript else "")
        head += f"\n\nBelow are {len(frames)} frames sampled across the video, in order."
        blocks = [{"type": "text", "text": head}] + [_img_block(f, "image/jpeg") for f in frames]
    else:
        kind = "document"
        text = _extract_text(data, ext)
        if not text.strip():
            return {"kind": kind, "analysis": f"I received '{filename}' but couldn't extract readable text from it. If it's a scanned image, send it as an image and I'll read it visually."}
        blocks = [{"type": "text", "text": f"{ask}\n\nFile name: {filename}\n\nContents:\n{text[:14000]}"}]

    analysis = get_llm().complete_blocks(system, blocks, max_tokens=900)
    return {"kind": kind, "analysis": analysis}
