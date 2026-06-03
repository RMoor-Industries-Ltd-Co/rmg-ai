"""Write script drafts to Google Docs for review (the 'approval gate').
Reuses the Creator OS rclone Drive OAuth (refresh token). Creates a native Google
Doc by uploading markdown with Drive conversion — no Docs API required."""

import time
from typing import Optional

import requests

from .config import settings

_token_cache: dict[str, float | str] = {"access_token": "", "expires_at": 0.0}


def _access_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and now < float(_token_cache["expires_at"]) - 60:
        return str(_token_cache["access_token"])
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.gdrive_client_id,
            "client_secret": settings.gdrive_client_secret,
            "refresh_token": settings.gdrive_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3600))
    return data["access_token"]


def write_script_doc(
    title: str, script: str, brand: str, persona: Optional[str], output_kind: str
) -> tuple[str, str]:
    """Create a Google Doc draft in the scripts folder. Returns (doc_id, doc_url)."""
    token = _access_token()

    md = (
        f"# {title}\n\n"
        f"**Brand:** {brand}  |  **Persona:** {persona or '—'}  |  "
        f"**Type:** {output_kind}  |  **Status:** DRAFT (ALLEN)\n\n---\n\n{script}\n"
    )

    boundary = "rmgallenboundary"
    metadata = (
        '{"name": %s, "parents": ["%s"], "mimeType": "application/vnd.google-apps.document"}'
        % (_json_str(f"{title} — {brand} [DRAFT]"), settings.gdrive_scripts_folder_id)
    )
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
        f"--{boundary}\r\nContent-Type: text/markdown\r\n\r\n{md}\r\n--{boundary}--"
    ).encode("utf-8")

    resp = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        params={"uploadType": "multipart", "fields": "id,webViewLink", "supportsAllDrives": "true"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/related; boundary={boundary}"},
        data=body,
        timeout=60,
    )
    resp.raise_for_status()
    j = resp.json()
    return j["id"], j.get("webViewLink", f"https://docs.google.com/document/d/{j['id']}/edit")


def _json_str(s: str) -> str:
    import json

    return json.dumps(s)
