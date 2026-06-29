"""YouTube ingest tool — downloads audio, video, and transcript from a YouTube URL,
then saves each file to Google Drive (rahm@rmasters.group) for ALLIE's research and b-roll use.

Transcript strategy (in order):
  1. YouTube auto-captions / manual subtitles (VTT)
  2. Whisper transcription — faster-whisper first, openai-whisper fallback
"""

import os
import re
import tempfile
import time
from typing import Optional

from .config import settings

TOOLS = [
    {
        "name": "youtube_ingest",
        "description": (
            "Download a YouTube video's audio (MP3), transcript (plain text), and optionally "
            "the full video (MP4), then save all files to Google Drive for research and b-roll use. "
            "Always returns the transcript text inline so ALLEN can read it immediately. "
            "Also returns Google Drive links for each file. "
            "When YouTube captions are unavailable, Whisper is used to transcribe the audio. "
            "Use this when Rahm or the task requires saving or reading a YouTube video for research, "
            "script inspiration, or b-roll sourcing. Audio + transcript are always downloaded; "
            "video is optional (large files — only request when explicitly needed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full YouTube video URL (https://www.youtube.com/watch?v=... or youtu.be/...)",
                },
                "include_video": {
                    "type": "boolean",
                    "description": (
                        "Also download and save the full MP4 video to Drive. Defaults to false "
                        "(audio + transcript only, much faster). Only set true when b-roll or "
                        "visual content from the video is explicitly needed."
                    ),
                },
                "whisper_model": {
                    "type": "string",
                    "description": (
                        "Whisper model size for audio transcription fallback when captions are unavailable. "
                        "Options: tiny, base, small, medium, large. Defaults to 'small' (good balance of "
                        "speed and accuracy). Use 'tiny' for quick turnaround; 'medium'/'large' for accuracy."
                    ),
                },
            },
            "required": ["url"],
        },
    }
]


def _vtt_to_text(vtt: str) -> str:
    """Strip VTT timing metadata and return clean transcript text, preserving all spoken content."""
    lines = vtt.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        # Skip timing lines: "00:00:01.234 --> 00:00:04.567"
        if "-->" in line:
            continue
        # Skip numeric index lines
        if re.match(r"^\d+$", line):
            continue
        # Strip HTML tags (e.g. <c>, <00:00:01.234>, <i>)
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)


def _retry(fn, retries: int = 4, base_delay: float = 3.0):
    """Run fn() with exponential backoff on exception."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(base_delay * (2 ** attempt))
    raise last_exc  # type: ignore[misc]


def _transcribe_with_whisper(audio_path: str, model_size: str = "small") -> str:
    """Transcribe audio file using faster-whisper, falling back to openai-whisper."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, beam_size=5)
        return " ".join(seg.text.strip() for seg in segments)
    except ImportError:
        pass
    except Exception as e:
        raise RuntimeError(f"faster-whisper failed: {e}") from e

    try:
        import whisper
        model = whisper.load_model(model_size)
        result = model.transcribe(audio_path)
        return result.get("text", "").strip()
    except ImportError:
        return "(Whisper not installed — install faster-whisper or openai-whisper for audio transcription)"
    except Exception as e:
        raise RuntimeError(f"openai-whisper failed: {e}") from e


def _probe_captions(info: dict) -> bool:
    """Return True if the video has usable subtitles or automatic captions."""
    for key in ("subtitles", "automatic_captions"):
        caps = info.get(key) or {}
        for lang in ("en", "en-US", "en-GB"):
            if lang in caps and caps[lang]:
                return True
    return False


def _ingest(url: str, include_video: bool = False, whisper_model: str = "small") -> str:
    try:
        import yt_dlp
    except ImportError:
        return "yt-dlp is not installed. Run: pip install yt-dlp"

    from .docs import upload_file_to_drive

    folder_id = settings.gdrive_youtube_folder_id
    if not folder_id:
        return "GDRIVE_YOUTUBE_FOLDER_ID is not configured — cannot save to Drive."
    if not settings.docs_ready:
        return "Google Drive credentials are not configured (GDRIVE_CLIENT_ID / SECRET / REFRESH_TOKEN)."

    results: dict[str, Optional[str]] = {"audio": None, "transcript": None, "video": None, "metadata": None}
    errors: list[str] = []
    transcript_text: str = ""
    video_title: str = "youtube_video"
    safe_title: str = "youtube_video"

    with tempfile.TemporaryDirectory() as tmpdir:
        # --- Step 1: Probe metadata (no download) ---
        probe_opts: dict = {"quiet": True, "no_warnings": True, "skip_download": True}
        try:
            def _probe():
                with yt_dlp.YoutubeDL(probe_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            info = _retry(_probe)
        except Exception as e:
            return f"YouTube ingest failed (could not reach video): {e}"

        video_title = info.get("title", "youtube_video")
        safe_title = re.sub(r"[^\w\s\-]", "", video_title).strip()[:80] or "youtube_video"
        has_captions = _probe_captions(info)

        # Build and upload metadata file
        meta_lines = [
            f"Title: {video_title}",
            f"Author: {info.get('uploader', 'Unknown')}",
            f"Channel: {info.get('channel', info.get('uploader', ''))}",
            f"Published: {info.get('upload_date', 'Unknown')}",
            f"Duration: {info.get('duration_string', info.get('duration', 'Unknown'))}s",
            f"URL: {url}",
            f"Description:\n{(info.get('description') or '').strip()[:2000]}",
            f"Tags: {', '.join(info.get('tags') or [])}",
        ]
        meta_bytes = "\n".join(meta_lines).encode("utf-8")
        try:
            _, link = upload_file_to_drive(
                f"{safe_title} — Metadata.txt", "text/plain", folder_id, meta_bytes
            )
            results["metadata"] = link
        except Exception as e:
            errors.append(f"Metadata upload failed: {e}")

        # --- Step 2: Audio + captions ---
        audio_opts: dict = {
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            "writeautomaticsub": has_captions,
            "writesubtitles": has_captions,
            "subtitleslangs": ["en", "en-US"],
            "subtitlesformat": "vtt",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        audio_path: Optional[str] = None
        try:
            def _download_audio():
                with yt_dlp.YoutubeDL(audio_opts) as ydl:
                    ydl.download([url])
            _retry(_download_audio)
        except Exception as e:
            errors.append(f"Audio download failed: {e}")

        for fname in os.listdir(tmpdir):
            fpath = os.path.join(tmpdir, fname)
            if fname.endswith(".mp3"):
                audio_path = fpath
                with open(fpath, "rb") as f:
                    audio_data = f.read()
                try:
                    _, link = upload_file_to_drive(
                        f"{safe_title}.mp3", "audio/mpeg", folder_id, audio_data
                    )
                    results["audio"] = link
                except Exception as e:
                    errors.append(f"Audio upload failed: {e}")

        # --- Step 3: Transcript ---
        vtt_found = False
        for fname in os.listdir(tmpdir):
            if fname.endswith(".vtt"):
                vtt_path = os.path.join(tmpdir, fname)
                with open(vtt_path, "r", encoding="utf-8", errors="replace") as f:
                    vtt_content = f.read()
                parsed = _vtt_to_text(vtt_content)
                if parsed.strip():
                    transcript_text = parsed
                    vtt_found = True
                break

        if not vtt_found and audio_path and os.path.exists(audio_path):
            try:
                transcript_text = _transcribe_with_whisper(audio_path, whisper_model)
            except Exception as e:
                errors.append(f"Whisper transcription failed: {e}")

        if transcript_text:
            transcript_bytes = transcript_text.encode("utf-8")
            try:
                _, link = upload_file_to_drive(
                    f"{safe_title} — Transcript.txt", "text/plain", folder_id, transcript_bytes
                )
                results["transcript"] = link
            except Exception as e:
                errors.append(f"Transcript upload failed: {e}")

        # --- Step 4: Video (optional) ---
        if include_video:
            video_opts: dict = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": os.path.join(tmpdir, f"{safe_title}_video.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }
            try:
                def _download_video():
                    with yt_dlp.YoutubeDL(video_opts) as ydl:
                        ydl.download([url])
                _retry(_download_video)
            except Exception as e:
                errors.append(f"Video download failed: {e}")

            for fname in os.listdir(tmpdir):
                if "_video." in fname and fname.endswith((".mp4", ".mkv", ".webm")):
                    fpath = os.path.join(tmpdir, fname)
                    ext = fname.rsplit(".", 1)[-1]
                    mime = {"mp4": "video/mp4", "mkv": "video/x-matroska", "webm": "video/webm"}.get(ext, "video/mp4")
                    with open(fpath, "rb") as f:
                        video_data = f.read()
                    try:
                        _, link = upload_file_to_drive(
                            f"{safe_title}.{ext}", mime, folder_id, video_data
                        )
                        results["video"] = link
                    except Exception as e:
                        errors.append(f"Video upload failed: {e}")
                    break

    # --- Build response ---
    lines = [f'Ingested: "{video_title}"']
    if results["audio"]:
        lines.append(f"Audio (MP3): {results['audio']}")
    if results["transcript"]:
        lines.append(f"Transcript (Drive): {results['transcript']}")
    if results["metadata"]:
        lines.append(f"Metadata: {results['metadata']}")
    if results["video"]:
        lines.append(f"Video (MP4): {results['video']}")
    if errors:
        lines.append(f"Warnings: {'; '.join(errors)}")

    if transcript_text:
        # Inline transcript — truncated to 6000 chars to stay within context
        preview = transcript_text[:6000]
        if len(transcript_text) > 6000:
            preview += f"\n... [truncated — full transcript saved to Drive]"
        lines.append(f"\nTRANSCRIPT:\n{preview}")
    else:
        lines.append("Transcript: not available (no captions and Whisper transcription failed or skipped)")

    return "\n".join(lines)


def handle(name: str, args: dict) -> str:
    if not settings.docs_ready:
        return "Google Drive is not configured."
    if name == "youtube_ingest":
        return _ingest(
            args.get("url", ""),
            args.get("include_video", False),
            args.get("whisper_model", "small"),
        )
    return f"(unknown youtube tool: {name})"


def ready() -> bool:
    return settings.docs_ready and bool(settings.gdrive_youtube_folder_id)
