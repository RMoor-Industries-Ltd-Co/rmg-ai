"""YouTube ingest tool — downloads audio, transcript, and optionally video from a YouTube URL,
then saves all files into a dated subfolder in Google Drive (rahm@rmasters.group).

Folder layout in Drive:
  <GDRIVE_YOUTUBE_FOLDER_ID>/
    {title[:12]}_{YYYYMMDD_HHMMSS}/
      {safe_title}.mp3
      {safe_title} — Transcript.txt
      {safe_title} — Metadata.txt
      {safe_title}.mp4  (only when include_video=true)

Transcript strategy (in order):
  1. YouTube auto-captions / manual subtitles (VTT)
  2. Whisper transcription — faster-whisper first, openai-whisper fallback
"""

import os
import re
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

from .config import settings

TOOLS = [
    {
        "name": "youtube_ingest",
        "description": (
            "Download a YouTube video's audio (MP3), transcript (plain text), and metadata, "
            "then save all files into a dated folder in Google Drive under rahm@rmasters.group. "
            "Always returns the transcript inline so ALLEN can read it immediately. "
            "When YouTube captions are unavailable, Whisper transcribes the audio automatically. "
            "Use this whenever Rahm pastes or mentions a YouTube URL — no additional prompting needed. "
            "Video (MP4) is optional and off by default (large files — only when b-roll is explicitly needed)."
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
                        "Also download and save the full MP4 video to Drive. Defaults to false. "
                        "Only set true when b-roll or visual content is explicitly needed."
                    ),
                },
                "whisper_model": {
                    "type": "string",
                    "description": (
                        "Whisper model size used when captions are unavailable. "
                        "Options: tiny, base, small, medium, large. Defaults to 'small'."
                    ),
                },
            },
            "required": ["url"],
        },
    }
]


def _vtt_to_text(vtt: str) -> str:
    """Strip VTT timing metadata and return clean transcript text."""
    seen: set[str] = set()
    out: list[str] = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)


def _retry(fn, retries: int = 4, base_delay: float = 3.0):
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
        return "(Whisper not installed — install faster-whisper or openai-whisper)"
    except Exception as e:
        raise RuntimeError(f"openai-whisper failed: {e}") from e


def _probe_captions(info: dict) -> bool:
    for key in ("subtitles", "automatic_captions"):
        caps = info.get(key) or {}
        for lang in ("en", "en-US", "en-GB"):
            if lang in caps and caps[lang]:
                return True
    return False


def _folder_name(title: str) -> str:
    """Build the Drive subfolder name: first 12 safe chars of title + UTC datetime stamp."""
    slug = re.sub(r"[^\w\s\-]", "", title).strip().replace(" ", "_")[:12].rstrip("_") or "yt"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{slug}_{stamp}"


def _ingest(url: str, include_video: bool = False, whisper_model: str = "small") -> str:
    try:
        import yt_dlp
    except ImportError:
        return "yt-dlp is not installed. Run: pip install yt-dlp"

    from .docs import create_drive_folder, upload_file_to_drive

    root_folder_id = settings.gdrive_video_folder_id
    if not root_folder_id:
        return "GDRIVE_VIDEO_FOLDER_ID (the save target) is not configured — cannot save to Drive."
    if not settings.docs_ready:
        return "Google Drive credentials are not configured (GDRIVE_CLIENT_ID / SECRET / REFRESH_TOKEN)."

    errors: list[str] = []
    transcript_text: str = ""
    audio_link: Optional[str] = None
    transcript_link: Optional[str] = None
    metadata_link: Optional[str] = None
    video_link: Optional[str] = None

    with tempfile.TemporaryDirectory() as tmpdir:
        # --- Probe metadata (no download) ---
        try:
            def _probe():
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                    return ydl.extract_info(url, download=False)
            info = _retry(_probe)
        except Exception as e:
            return f"YouTube ingest failed (could not reach video): {e}"

        video_title = info.get("title", "youtube_video")
        safe_title = re.sub(r"[^\w\s\-]", "", video_title).strip()[:80] or "youtube_video"
        has_captions = _probe_captions(info)

        # --- Create per-video subfolder in Drive ---
        folder_name = _folder_name(video_title)
        try:
            folder_id = create_drive_folder(folder_name, root_folder_id)
        except Exception as e:
            return f"Could not create Drive folder '{folder_name}': {e}"

        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

        # --- Upload metadata ---
        meta_lines = [
            f"Title: {video_title}",
            f"Author: {info.get('uploader', 'Unknown')}",
            f"Channel: {info.get('channel', info.get('uploader', ''))}",
            f"Published: {info.get('upload_date', 'Unknown')}",
            f"Duration: {info.get('duration_string', info.get('duration', 'Unknown'))}",
            f"URL: {url}",
            f"Tags: {', '.join(info.get('tags') or [])}",
            f"\nDescription:\n{(info.get('description') or '').strip()[:2000]}",
        ]
        try:
            _, metadata_link = upload_file_to_drive(
                f"{safe_title} — Metadata.txt", "text/plain", folder_id,
                "\n".join(meta_lines).encode("utf-8")
            )
        except Exception as e:
            errors.append(f"Metadata upload failed: {e}")

        # --- Download audio (+ captions if available) ---
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
            def _dl_audio():
                with yt_dlp.YoutubeDL(audio_opts) as ydl:
                    ydl.download([url])
            _retry(_dl_audio)
        except Exception as e:
            errors.append(f"Audio download failed: {e}")

        for fname in os.listdir(tmpdir):
            fpath = os.path.join(tmpdir, fname)
            if fname.endswith(".mp3"):
                audio_path = fpath
                with open(fpath, "rb") as f:
                    data = f.read()
                try:
                    _, audio_link = upload_file_to_drive(
                        f"{safe_title}.mp3", "audio/mpeg", folder_id, data
                    )
                except Exception as e:
                    errors.append(f"Audio upload failed: {e}")

        # --- Transcript: VTT first, Whisper fallback ---
        for fname in os.listdir(tmpdir):
            if fname.endswith(".vtt"):
                with open(os.path.join(tmpdir, fname), "r", encoding="utf-8", errors="replace") as f:
                    parsed = _vtt_to_text(f.read())
                if parsed.strip():
                    transcript_text = parsed
                break

        if not transcript_text and audio_path and os.path.exists(audio_path):
            try:
                transcript_text = _transcribe_with_whisper(audio_path, whisper_model)
            except Exception as e:
                errors.append(f"Whisper transcription failed: {e}")

        if transcript_text:
            try:
                _, transcript_link = upload_file_to_drive(
                    f"{safe_title} — Transcript.txt", "text/plain", folder_id,
                    transcript_text.encode("utf-8")
                )
            except Exception as e:
                errors.append(f"Transcript upload failed: {e}")

        # --- Video (optional) ---
        if include_video:
            video_opts: dict = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": os.path.join(tmpdir, f"{safe_title}_video.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }
            try:
                def _dl_video():
                    with yt_dlp.YoutubeDL(video_opts) as ydl:
                        ydl.download([url])
                _retry(_dl_video)
            except Exception as e:
                errors.append(f"Video download failed: {e}")

            for fname in os.listdir(tmpdir):
                if "_video." in fname and fname.endswith((".mp4", ".mkv", ".webm")):
                    fpath = os.path.join(tmpdir, fname)
                    ext = fname.rsplit(".", 1)[-1]
                    mime = {"mp4": "video/mp4", "mkv": "video/x-matroska", "webm": "video/webm"}.get(ext, "video/mp4")
                    with open(fpath, "rb") as f:
                        data = f.read()
                    try:
                        _, video_link = upload_file_to_drive(
                            f"{safe_title}.{ext}", mime, folder_id, data
                        )
                    except Exception as e:
                        errors.append(f"Video upload failed: {e}")
                    break

    # --- Build response ---
    lines = [f'Ingested: "{video_title}"', f"Drive folder: {folder_url}"]
    if audio_link:
        lines.append(f"Audio (MP3): {audio_link}")
    if transcript_link:
        lines.append(f"Transcript: {transcript_link}")
    if metadata_link:
        lines.append(f"Metadata: {metadata_link}")
    if video_link:
        lines.append(f"Video (MP4): {video_link}")
    if errors:
        lines.append(f"Warnings: {'; '.join(errors)}")

    if transcript_text:
        preview = transcript_text[:6000]
        if len(transcript_text) > 6000:
            preview += "\n... [truncated — full transcript saved to Drive]"
        lines.append(f"\nTRANSCRIPT:\n{preview}")
    else:
        lines.append("Transcript: not available (no captions and Whisper transcription failed or skipped)")

    return "\n".join(lines)


# ---- READ side: ALLEN's autonomous transcript library ----
#
# The YOUTUBE SCRAPES read folder (settings.gdrive_youtube_folder_id) is a nested tree:
#   <read root>/<CATEGORY>/<CHANNEL>/<video_YYYYMMDD_HHMMSS>/{transcript (Google Doc), ...}
# (older scrapes also drop a title-named transcript Google Doc directly in the channel folder).
# These helpers let ALLEN browse + read those transcripts himself, with no folder id from Rahm.

from . import tools_gdrive  # noqa: E402  (read helpers reuse Drive token + read path)

_FOLDER_MIME = "application/vnd.google-apps.folder"
_DOC_MIME = "application/vnd.google-apps.document"

READ_TOOLS = [
    {
        "name": "youtube_list_transcripts",
        "description": (
            "List the YouTube video transcripts in Rahm's read-only transcript library "
            "(the YOUTUBE SCRAPES Drive folder MyTubeScript fills). Optionally filter by a "
            "keyword in the video title / channel / category. Returns titles + file ids to pass "
            "to youtube_read_transcript. Use this to discover what's been scraped."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional keyword to filter by title/channel/category."},
                "limit": {"type": "integer", "description": "Max results (default 25)."},
            },
        },
    },
    {
        "name": "youtube_read_transcript",
        "description": (
            "Read the FULL text of a scraped YouTube transcript from Rahm's library so you can "
            "interpret, summarize, or quote it. Pass either file_id (from youtube_list_transcripts) "
            "OR a query keyword matching the video title — with a query and no file_id the best/most-"
            "recent match is read. Call this autonomously whenever Rahm asks about a scraped video."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Transcript file id from youtube_list_transcripts."},
                "query": {"type": "string", "description": "Keyword matching the video title, when no file_id is given."},
            },
        },
    },
]


def read_ready() -> bool:
    """Read-library readiness — needs Drive access + the READ folder. Deliberately uses
    tools_gdrive.ready() (legacy/unified OAuth) rather than docs_ready, since reading a
    transcript doesn't need the scripts-folder that docs_ready also requires."""
    return tools_gdrive.ready() and bool(settings.gdrive_youtube_folder_id)


def _children(folder_id: str, headers: dict) -> list[dict]:
    import requests

    params = {
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,createdTime)",
        "pageSize": 200,
        "orderBy": "createdTime desc",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    r = requests.get(f"{tools_gdrive.DRIVE_BASE}/files", headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("files", [])


def _is_transcript(f: dict) -> bool:
    name = (f.get("name") or "").lower()
    mime = f.get("mimeType")
    if mime == _FOLDER_MIME:
        return False
    if "biblio" in name or "metadata" in name:
        return False  # skip the sidecar files
    if mime == _DOC_MIME:
        return True
    return name.endswith(".txt") and "transcript" in name


def _label(f: dict, parent_name: str) -> str:
    name = f.get("name") or ""
    lbl = parent_name if name.lower().startswith("transcript") and parent_name else name
    lbl = re.sub(r"_\d{8}_\d{6}$", "", lbl)  # strip MyTubeScript's _YYYYMMDD_HHMMSS stamp
    return lbl.replace("_", " ").strip() or name


def _walk_transcripts(root: str, query: Optional[str] = None, limit: int = 25, max_nodes: int = 500) -> list[dict]:
    """Breadth-first walk of the read folder, collecting transcript files. Query filters the
    leaf transcripts (folder traversal isn't pruned, since the title lives deep in the tree)."""
    q_low = (query or "").lower().strip()
    headers = tools_gdrive._h(None)  # mint the Drive token once, reuse across the whole walk
    results: list[dict] = []
    queue: list[tuple[str, str, str]] = [(root, "", "")]
    visited = 0
    while queue and len(results) < limit and visited < max_nodes:
        fid, fname, path = queue.pop(0)
        visited += 1
        try:
            kids = _children(fid, headers)
        except Exception:
            continue
        for f in kids:
            if f.get("mimeType") == _FOLDER_MIME:
                queue.append((f["id"], f.get("name", ""), f"{path}/{f.get('name','')}".strip("/")))
            elif _is_transcript(f):
                label = _label(f, fname)
                if q_low and q_low not in f"{label} {path} {f.get('name','')}".lower():
                    continue
                results.append({"label": label, "file_id": f["id"], "path": path, "created": f.get("createdTime", "")})
    results.sort(key=lambda r: r["created"], reverse=True)
    return results[:limit]


def _list_transcripts(args: dict) -> str:
    root = settings.gdrive_youtube_folder_id
    query = args.get("query")
    limit = max(1, min(int(args.get("limit", 25) or 25), 100))
    items = _walk_transcripts(root, query, limit)
    if not items:
        return "No transcripts found" + (f" matching '{query}'." if query else " in the library.")
    lines = [f"- {it['label']}  (id {it['file_id']}{'; ' + it['path'] if it['path'] else ''})" for it in items]
    header = f"Transcripts matching '{query}':" if query else "Transcripts in the library:"
    return header + "\n" + "\n".join(lines)


def _read_transcript(args: dict) -> str:
    fid = args.get("file_id")
    if fid:
        return tools_gdrive._read_file({"file_id": fid})
    query = args.get("query")
    if not query:
        return "Provide a file_id (from youtube_list_transcripts) or a query keyword to pick a transcript."
    items = _walk_transcripts(settings.gdrive_youtube_folder_id, query, limit=5)
    if not items:
        return f"No transcript found matching '{query}'."
    top = items[0]
    body = tools_gdrive._read_file({"file_id": top["file_id"]})
    if len(items) > 1:
        others = ", ".join(it["label"] for it in items[1:])
        body += f"\n\n(Read '{top['label']}' — the best match. Others: {others}.)"
    return body


INGEST_TOOLS = TOOLS
TOOLS = INGEST_TOOLS + READ_TOOLS  # exported set (all youtube tools)


def available_tools() -> list[dict]:
    """The youtube tools actually usable right now — ingest only if a save target is set,
    read tools only if the read library is configured."""
    out: list[dict] = []
    if ready():
        out += INGEST_TOOLS
    if read_ready():
        out += READ_TOOLS
    return out


def any_ready() -> bool:
    return ready() or read_ready()


def handle(name: str, args: dict) -> str:
    if name == "youtube_ingest":
        if not ready():
            return "YouTube ingest isn't configured (needs Drive creds + GDRIVE_VIDEO_FOLDER_ID save target)."
        return _ingest(
            args.get("url", ""),
            args.get("include_video", False),
            args.get("whisper_model", "small"),
        )
    if name in ("youtube_list_transcripts", "youtube_read_transcript"):
        if not read_ready():
            return "The YouTube transcript library isn't configured (needs Drive access + GDRIVE_YOUTUBE_FOLDER_ID)."
        return _list_transcripts(args) if name == "youtube_list_transcripts" else _read_transcript(args)
    return f"(unknown youtube tool: {name})"


def ready() -> bool:
    """Ingest (save) readiness."""
    return settings.docs_ready and bool(settings.gdrive_video_folder_id)
