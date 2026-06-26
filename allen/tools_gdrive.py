"""Google Drive tool client — ALLEN and ALLIE's read + write access to Rahm's Drive.
Uses the same OAuth credentials as the scripts/YouTube uploads (gdrive_* settings)."""

import json

import requests

from . import db
from .config import settings

DRIVE_BASE = "https://www.googleapis.com/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def ready() -> bool:
    return bool(settings.gdrive_client_id and settings.gdrive_client_secret and settings.gdrive_refresh_token)


def _access_token() -> str:
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.gdrive_client_id,
            "client_secret": settings.gdrive_client_secret,
            "refresh_token": settings.gdrive_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _h(token: str | None = None) -> dict:
    t = token or _access_token()
    return {"Authorization": f"Bearer {t}"}


_READ_TOOLS = [
    {
        "name": "drive_search",
        "description": "Search for files or folders in Rahm's Google Drive by name or content query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (Drive q= syntax or plain keywords)."},
                "folder_id": {"type": "string", "description": "Optional folder ID to restrict search."},
                "max_results": {"type": "integer", "description": "Max files to return (default 20)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_list_folder",
        "description": "List files and folders inside a specific Google Drive folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Drive folder ID to list. Use 'root' for the root folder."},
            },
            "required": ["folder_id"],
        },
    },
    {
        "name": "drive_read_file",
        "description": "Read the text content of a Google Drive file (plain text or Google Docs exported as text).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Drive file ID to read."},
            },
            "required": ["file_id"],
        },
    },
]

WRITE_TOOLS = [
    {
        "name": "drive_create_folder",
        "description": "Create a new folder in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the new folder."},
                "parent_id": {"type": "string", "description": "Parent folder ID. Omit to create in root."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "drive_create_file",
        "description": "Create a new text file in Google Drive with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name (include extension, e.g. 'notes.txt')."},
                "content": {"type": "string", "description": "Text content to write into the file."},
                "parent_id": {"type": "string", "description": "Parent folder ID. Omit to create in root."},
                "mime_type": {"type": "string", "description": "MIME type (default 'text/plain')."},
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "drive_update_file",
        "description": "Update an existing Drive file — change its name, content, or both.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Drive file ID to update."},
                "name": {"type": "string", "description": "New file name (optional)."},
                "content": {"type": "string", "description": "New text content (optional)."},
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "drive_move_file",
        "description": "Move a file or folder to a different parent folder in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Drive file/folder ID to move."},
                "new_parent_id": {"type": "string", "description": "Destination folder ID."},
            },
            "required": ["file_id", "new_parent_id"],
        },
    },
    {
        "name": "drive_delete_file",
        "description": "Move a file or folder to the Trash in Google Drive (recoverable from Trash).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Drive file/folder ID to trash."},
            },
            "required": ["file_id"],
        },
    },
]

TOOLS = _READ_TOOLS + WRITE_TOOLS
WRITE_NAMES = {t["name"] for t in WRITE_TOOLS}


def _search(args: dict) -> str:
    q = args["query"]
    if args.get("folder_id"):
        q = f"'{args['folder_id']}' in parents and ({q})"
    q += " and trashed=false"
    params = {
        "q": q,
        "fields": "files(id,name,mimeType,modifiedTime)",
        "pageSize": min(int(args.get("max_results", 20)), 50),
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    r = requests.get(f"{DRIVE_BASE}/files", headers=_h(), params=params, timeout=30)
    r.raise_for_status()
    files = r.json().get("files", [])
    if not files:
        return "No files found matching that query."
    return "\n".join(f"- {f['name']} (id {f['id']}, {f['mimeType']})" for f in files)


def _list_folder(args: dict) -> str:
    folder_id = args["folder_id"]
    params = {
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType)",
        "pageSize": 100,
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    r = requests.get(f"{DRIVE_BASE}/files", headers=_h(), params=params, timeout=30)
    r.raise_for_status()
    files = r.json().get("files", [])
    if not files:
        return "Folder is empty."
    return "\n".join(f"- {f['name']} (id {f['id']}, {f['mimeType']})" for f in files)


def _read_file(args: dict) -> str:
    file_id = args["file_id"]
    meta_r = requests.get(
        f"{DRIVE_BASE}/files/{file_id}",
        headers=_h(),
        params={"fields": "mimeType,name", "supportsAllDrives": "true"},
        timeout=30,
    )
    meta_r.raise_for_status()
    meta = meta_r.json()
    mime = meta.get("mimeType", "")
    if mime == "application/vnd.google-apps.document":
        url = f"{DRIVE_BASE}/files/{file_id}/export"
        params: dict = {"mimeType": "text/plain", "supportsAllDrives": "true"}
    else:
        url = f"{DRIVE_BASE}/files/{file_id}"
        params = {"alt": "media", "supportsAllDrives": "true"}
    r = requests.get(url, headers=_h(), params=params, timeout=30)
    r.raise_for_status()
    return f"=== {meta.get('name', file_id)} ===\n{r.text[:8000]}"


def _create_folder(args: dict) -> str:
    metadata: dict = {"name": args["name"], "mimeType": "application/vnd.google-apps.folder"}
    if args.get("parent_id"):
        metadata["parents"] = [args["parent_id"]]
    r = requests.post(
        f"{DRIVE_BASE}/files",
        headers={**_h(), "Content-Type": "application/json"},
        json=metadata,
        params={"fields": "id,name", "supportsAllDrives": "true"},
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    return f"Created folder '{d['name']}' (id {d['id']})"


def _create_file(args: dict) -> str:
    mime = args.get("mime_type", "text/plain")
    content = args["content"].encode("utf-8")
    metadata: dict = {"name": args["name"]}
    if args.get("parent_id"):
        metadata["parents"] = [args["parent_id"]]
    meta_bytes = json.dumps(metadata).encode("utf-8")
    boundary = b"rmgboundary42"
    body = (
        b"--" + boundary + b"\r\n"
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n" + meta_bytes + b"\r\n"
        b"--" + boundary + b"\r\n"
        b"Content-Type: " + mime.encode() + b"\r\n\r\n" + content + b"\r\n"
        b"--" + boundary + b"--"
    )
    token = _access_token()
    r = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary.decode()}",
        },
        params={"uploadType": "multipart", "fields": "id,name,webViewLink", "supportsAllDrives": "true"},
        data=body,
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    return f"Created file '{d['name']}' (id {d['id']}) — {d.get('webViewLink', '')}"


def _update_file(args: dict) -> str:
    file_id = args["file_id"]
    token = _access_token()
    auth_h = {"Authorization": f"Bearer {token}"}
    if args.get("content") is not None:
        content = args["content"].encode("utf-8")
        meta: dict = {}
        if args.get("name"):
            meta["name"] = args["name"]
        meta_bytes = json.dumps(meta).encode("utf-8")
        boundary = b"rmgupdboundary"
        body = (
            b"--" + boundary + b"\r\n"
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n" + meta_bytes + b"\r\n"
            b"--" + boundary + b"\r\n"
            b"Content-Type: text/plain\r\n\r\n" + content + b"\r\n"
            b"--" + boundary + b"--"
        )
        r = requests.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
            headers={**auth_h, "Content-Type": f"multipart/related; boundary={boundary.decode()}"},
            params={"uploadType": "multipart", "fields": "id,name", "supportsAllDrives": "true"},
            data=body,
            timeout=60,
        )
    elif args.get("name"):
        r = requests.patch(
            f"{DRIVE_BASE}/files/{file_id}",
            headers={**auth_h, "Content-Type": "application/json"},
            params={"fields": "id,name", "supportsAllDrives": "true"},
            json={"name": args["name"]},
            timeout=30,
        )
    else:
        return "Nothing to update — provide name and/or content."
    r.raise_for_status()
    d = r.json()
    return f"Updated file '{d.get('name', file_id)}' (id {d.get('id', file_id)})"


def _move_file(args: dict) -> str:
    file_id = args["file_id"]
    new_parent = args["new_parent_id"]
    meta_r = requests.get(
        f"{DRIVE_BASE}/files/{file_id}",
        headers=_h(),
        params={"fields": "parents,name", "supportsAllDrives": "true"},
        timeout=30,
    )
    meta_r.raise_for_status()
    meta = meta_r.json()
    current_parents = ",".join(meta.get("parents", []))
    name = meta.get("name", file_id)
    r = requests.patch(
        f"{DRIVE_BASE}/files/{file_id}",
        headers={**_h(), "Content-Type": "application/json"},
        params={
            "addParents": new_parent,
            "removeParents": current_parents,
            "fields": "id,name",
            "supportsAllDrives": "true",
        },
        json={},
        timeout=30,
    )
    r.raise_for_status()
    return f"Moved '{name}' to folder {new_parent}."


def _delete_file(args: dict) -> str:
    file_id = args["file_id"]
    r = requests.patch(
        f"{DRIVE_BASE}/files/{file_id}",
        headers={**_h(), "Content-Type": "application/json"},
        params={"supportsAllDrives": "true"},
        json={"trashed": True},
        timeout=30,
    )
    r.raise_for_status()
    return f"Moved file {file_id} to Trash."


def handle(name: str, args: dict) -> str:
    if not ready():
        return "Google Drive isn't configured (needs GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN)."
    args = args or {}
    try:
        if name == "drive_search":
            return _search(args)
        if name == "drive_list_folder":
            return _list_folder(args)
        if name == "drive_read_file":
            return _read_file(args)
        if name == "drive_create_folder":
            return _create_folder(args)
        if name == "drive_create_file":
            return _create_file(args)
        if name == "drive_update_file":
            return _update_file(args)
        if name == "drive_move_file":
            return _move_file(args)
        if name == "drive_delete_file":
            return _delete_file(args)
    except requests.HTTPError as e:
        return f"Drive API error: {e.response.status_code} {e.response.text[:300]}"
    except Exception as e:
        return f"Drive call failed: {e}"
    return f"(unknown drive tool: {name})"
