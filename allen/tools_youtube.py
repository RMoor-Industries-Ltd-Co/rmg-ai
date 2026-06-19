"""YouTube ingest tool — downloads audio, video, and transcript from a YouTube URL,
then saves each file to Google Drive (rahm@rmasters.group) for ALLIE's research and b-roll use."""

import os
import re
import tempfile
from typing import Optional

from .config import settings

TOOLS = [
    {
        "name": "youtube_ingest",
        "description": (
            "Download a YouTube video's audio (MP3), subtitles/transcript (plain text), and optionally "
            "the full video (MP4), then save all files to Google Drive for research and b-roll use. "
            "Returns Google Drive links for each file so ALLIE can reference or share them. "
            "Use this when Rahm or the task requires saving a YouTube video for research, script "
            "inspiration, or b-roll sourcing. Audio + transcript are always downloaded; video is "
            "optional (large files — only request when explicitly needed)."
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
            },
            "required": ["url"],
        },
    }
]


def _vtt_to_text(vtt: str) -> str:
    """Strip VTT timing metadata and return clean transcript text."""
    lines = vtt.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}", line) or re.match(r"^[\d:.]+ --> ", line):
            continue
        if re.match(r"^\d+$", line):
            continue
        # Strip HTML tags (e.g. <c>, <00:00:01.234>)
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)


def _ingest(url: str, include_video: bool = False) -> str:
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

    results: dict[str, Optional[str]] = {"audio": None, "transcript": None, "video": None}
    errors: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # --- Step 1: Audio + transcript ---
        audio_opts: dict = {
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en", "en-US"],
            "subtitlesformat": "vtt",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        video_title = "youtube_video"
        try:
            with yt_dlp.YoutubeDL(audio_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_title = info.get("title", "youtube_video")
                safe_title = re.sub(r'[^\w\s\-]', '', video_title).strip()[:80]
        except Exception as e:
            errors.append(f"Download failed: {e}")
            return f"YouTube ingest failed: {'; '.join(errors)}"

        # Find downloaded audio file
        for fname in os.listdir(tmpdir):
            if fname.endswith(".mp3"):
                audio_path = os.path.join(tmpdir, fname)
                with open(audio_path, "rb") as f:
                    audio_data = f.read()
                try:
                    _, link = upload_file_to_drive(
                        f"{safe_title}.mp3", "audio/mpeg", folder_id, audio_data
                    )
                    results["audio"] = link
                except Exception as e:
                    errors.append(f"Audio upload failed: {e}")
                break

        # Find VTT subtitle file and convert to plain text
        for fname in os.listdir(tmpdir):
            if fname.endswith(".vtt"):
                vtt_path = os.path.join(tmpdir, fname)
                with open(vtt_path, "r", encoding="utf-8", errors="replace") as f:
                    vtt_content = f.read()
                transcript_text = _vtt_to_text(vtt_content)
                if transcript_text:
                    transcript_bytes = transcript_text.encode("utf-8")
                    try:
                        _, link = upload_file_to_drive(
                            f"{safe_title} — Transcript.txt", "text/plain", folder_id, transcript_bytes
                        )
                        results["transcript"] = link
                    except Exception as e:
                        errors.append(f"Transcript upload failed: {e}")
                break

        # --- Step 2: Video (optional) ---
        if include_video:
            video_opts: dict = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": os.path.join(tmpdir, f"{safe_title}_video.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }
            try:
                with yt_dlp.YoutubeDL(video_opts) as ydl:
                    ydl.download([url])
            except Exception as e:
                errors.append(f"Video download failed: {e}")

            for fname in os.listdir(tmpdir):
                if "_video." in fname and fname.endswith((".mp4", ".mkv", ".webm")):
                    video_path = os.path.join(tmpdir, fname)
                    ext = fname.rsplit(".", 1)[-1]
                    mime = "video/mp4" if ext == "mp4" else "video/x-matroska" if ext == "mkv" else "video/webm"
                    with open(video_path, "rb") as f:
                        video_data = f.read()
                    try:
                        _, link = upload_file_to_drive(
                            f"{safe_title}.{ext}", mime, folder_id, video_data
                        )
                        results["video"] = link
                    except Exception as e:
                        errors.append(f"Video upload failed: {e}")
                    break

    # Build response
    lines = [f'Ingested: "{video_title}"']
    if results["audio"]:
        lines.append(f"Audio (MP3): {results['audio']}")
    if results["transcript"]:
        lines.append(f"Transcript: {results['transcript']}")
    if results["video"]:
        lines.append(f"Video (MP4): {results['video']}")
    if not results["transcript"]:
        lines.append("Transcript: not available (no auto-captions on this video)")
    if errors:
        lines.append(f"Warnings: {'; '.join(errors)}")
    return "\n".join(lines)


def handle(name: str, args: dict) -> str:
    if not settings.docs_ready:
        return "Google Drive is not configured."
    if name == "youtube_ingest":
        return _ingest(args.get("url", ""), args.get("include_video", False))
    return f"(unknown youtube tool: {name})"


def ready() -> bool:
    return settings.docs_ready and bool(settings.gdrive_youtube_folder_id)
