"""Google Drive tool suite for ALLEN and ALLIE — search, list folder, read file.

Each tool accepts an optional `account` param (default: rahmind.consulting@rmoorind.com).
Required OAuth scope: https://www.googleapis.com/auth/drive
"""

import requests

from . import google_auth

DRIVE_BASE = "https://www.googleapis.com/drive/v3"

WRITE_TOOLS = [
    {
        "name": "drive_create_folder",
        "description": (
            "Create a new folder in Google Drive. "
            "Returns the new folder's id and link."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Folder name"},
                "parent_id": {
                    "type": "string",
                    "description": "Parent folder id (omit to create in My Drive root).",
                },
                "account": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "drive_create_file",
        "description": (
            "Create a plain-text file in Google Drive with the given content. "
            "Use for .txt, .md, .csv, or any text-based content. "
            "Returns the new file's id and link."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name including extension"},
                "content": {"type": "string", "description": "Text content of the file"},
                "mime_type": {
                    "type": "string",
                    "description": "MIME type (default: text/plain). E.g. text/csv, text/markdown.",
                },
                "parent_id": {
                    "type": "string",
                    "description": "Parent folder id (omit for My Drive root).",
                },
                "account": {"type": "string"},
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "drive_update_file",
        "description": (
            "Replace the content of an existing Google Drive file. "
            "Optionally rename the file at the same time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "content": {"type": "string", "description": "New text content"},
                "name": {"type": "string", "description": "New file name (optional rename)"},
                "mime_type": {"type": "string", "description": "MIME type of the new content"},
                "account": {"type": "string"},
            },
            "required": ["file_id", "content"],
        },
    },
    {
        "name": "drive_move_file",
        "description": "Move a file or folder to a different parent folder in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "new_parent_id": {"type": "string", "description": "Destination folder id"},
                "account": {"type": "string"},
            },
            "required": ["file_id", "new_parent_id"],
        },
    },
    {
        "name": "drive_delete_file",
        "description": (
            "Move a file or folder to Google Drive Trash. "
            "The item can be restored from Trash for 30 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["file_id"],
        },
    },
]

TOOLS = [
    {
        "name": "drive_search",
        "description": (
            "Search one of Rahm's Google Drive accounts for files or folders. "
            "Returns file names, ids, types, modified dates, and links. "
            "Accepts any plain keyword or Drive query syntax."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search term or Drive query, e.g. 'budget Q3' or "
                        "\"name contains 'proposal'\"."
                    ),
                },
                "max_results": {"type": "integer", "description": "max results (default 15)"},
                "account": {
                    "type": "string",
                    "description": "Rahm's Google account email (default: rahmind.consulting@rmoorind.com)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_list_folder",
        "description": "List the files inside a Google Drive folder by folder_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Drive folder id"},
                "account": {"type": "string"},
            },
            "required": ["folder_id"],
        },
    },
    {
        "name": "drive_read_file",
        "description": (
            "Read the text content of a Google Drive file "
            "(Google Docs, Sheets, plain text, or any exportable type). "
            "Returns extracted text (up to 5 000 chars)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["file_id"],
        },
    },
] + WRITE_TOOLS

WRITE_NAMES = {t["name"] for t in WRITE_TOOLS}

_GDOC = "application/vnd.google-apps.document"
_GSHEET = "application/vnd.google-apps.spreadsheet"
_GSLIDE = "application/vnd.google-apps.presentation"


def _h(account: str) -> dict:
    return google_auth.auth_headers(account)


def _search(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    q = (args.get("query") or "").strip()
    max_r = min(int(args.get("max_results") or 15), 50)
    # Wrap plain keywords in Drive query syntax
    if " contains " not in q and "'" not in q and "=" not in q:
        safe = q.replace("'", "\\'")
        q = f"(name contains '{safe}' or fullText contains '{safe}')"
    params = {
        "q": q + " and trashed=false",
        "pageSize": max_r,
        "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        "orderBy": "modifiedTime desc",
    }
    r = requests.get(f"{DRIVE_BASE}/files", headers=_h(account), params=params, timeout=30)
    r.raise_for_status()
    files = r.json().get("files", [])
    if not files:
        return f"No Drive files found for '{args.get('query')}' in {account}."
    lines = [f"Drive search in {account}:"]
    for f in files:
        mt = (f.get("modifiedTime") or "")[:10]
        kind = f.get("mimeType", "").split(".")[-1]
        lines.append(
            f"- [{f['id']}] {f['name']} ({kind}) modified {mt} — {f.get('webViewLink', '')}"
        )
    return "\n".join(lines)


def _list_folder(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    fid = args["folder_id"]
    params = {
        "q": f"'{fid}' in parents and trashed=false",
        "pageSize": 50,
        "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        "orderBy": "name",
    }
    r = requests.get(f"{DRIVE_BASE}/files", headers=_h(account), params=params, timeout=30)
    r.raise_for_status()
    files = r.json().get("files", [])
    if not files:
        return f"Folder {fid} is empty (or not accessible) in {account}."
    lines = [f"Contents of folder {fid} in {account}:"]
    for f in files:
        kind = f.get("mimeType", "").split(".")[-1]
        lines.append(f"- [{f['id']}] {f['name']} ({kind})")
    return "\n".join(lines)


def _read_file(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    fid = args["file_id"]
    h = _h(account)
    meta = requests.get(
        f"{DRIVE_BASE}/files/{fid}",
        headers=h,
        params={"fields": "name,mimeType"},
        timeout=30,
    ).json()
    mime = meta.get("mimeType", "")
    name = meta.get("name", fid)

    export_params: dict | None = None
    if mime == _GDOC:
        export_params = {"mimeType": "text/plain"}
    elif mime == _GSHEET:
        export_params = {"mimeType": "text/csv"}
    elif mime == _GSLIDE:
        export_params = {"mimeType": "text/plain"}
    elif mime == "application/pdf":
        return f"'{name}' is a PDF — open at drive.google.com to read it."

    if export_params is not None:
        r = requests.get(
            f"{DRIVE_BASE}/files/{fid}/export",
            headers=h,
            params=export_params,
            timeout=60,
        )
    else:
        r = requests.get(
            f"{DRIVE_BASE}/files/{fid}",
            headers=h,
            params={"alt": "media"},
            timeout=60,
        )
    r.raise_for_status()
    text = r.text[:5000]
    return f"Contents of '{name}' ({fid}) in {account}:\n\n{text}"


def _create_folder(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    body: dict = {
        "name": args["name"],
        "mimeType": "application/vnd.google-apps.folder",
    }
    if args.get("parent_id"):
        body["parents"] = [args["parent_id"]]
    r = requests.post(
        f"{DRIVE_BASE}/files",
        headers=_h(account),
        params={"fields": "id,name,webViewLink"},
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    f = r.json()
    return f"Created folder '{f['name']}' (id {f['id']}) in {account} — {f.get('webViewLink', '')}"


def _create_file(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    mime = args.get("mime_type") or "text/plain"
    meta: dict = {"name": args["name"]}
    if args.get("parent_id"):
        meta["parents"] = [args["parent_id"]]
    content = (args.get("content") or "").encode()
    # Multipart upload: metadata + media in one request
    boundary = "allen_drive_boundary"
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        + __import__("json").dumps(meta)
        + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--".encode()
    headers = _h(account)
    headers["Content-Type"] = f"multipart/related; boundary={boundary}"
    r = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        headers=headers,
        params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
        data=body,
        timeout=60,
    )
    r.raise_for_status()
    f = r.json()
    return f"Created file '{f['name']}' (id {f['id']}) in {account} — {f.get('webViewLink', '')}"


def _update_file(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    fid = args["file_id"]
    mime = args.get("mime_type") or "text/plain"
    meta: dict = {}
    if args.get("name"):
        meta["name"] = args["name"]
    content = (args.get("content") or "").encode()
    if meta:
        boundary = "allen_drive_boundary"
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            + __import__("json").dumps(meta)
            + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--".encode()
        headers = _h(account)
        headers["Content-Type"] = f"multipart/related; boundary={boundary}"
        r = requests.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{fid}",
            headers=headers,
            params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
            data=body,
            timeout=60,
        )
    else:
        headers = _h(account)
        headers["Content-Type"] = mime
        r = requests.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{fid}",
            headers=headers,
            params={"uploadType": "media", "fields": "id,name,webViewLink"},
            data=content,
            timeout=60,
        )
    r.raise_for_status()
    f = r.json()
    return f"Updated file '{f['name']}' (id {f['id']}) in {account} — {f.get('webViewLink', '')}"


def _move_file(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    fid = args["file_id"]
    new_parent = args["new_parent_id"]
    # Fetch current parents so we can remove them
    meta = requests.get(
        f"{DRIVE_BASE}/files/{fid}",
        headers=_h(account),
        params={"fields": "name,parents"},
        timeout=30,
    ).json()
    old_parents = ",".join(meta.get("parents") or [])
    r = requests.patch(
        f"{DRIVE_BASE}/files/{fid}",
        headers=_h(account),
        params={
            "addParents": new_parent,
            "removeParents": old_parents,
            "fields": "id,name,parents",
        },
        json={},
        timeout=30,
    )
    r.raise_for_status()
    return f"Moved '{meta.get('name', fid)}' to folder {new_parent} in {account}."


def _delete_file(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    fid = args["file_id"]
    r = requests.patch(
        f"{DRIVE_BASE}/files/{fid}",
        headers=_h(account),
        params={"fields": "id,name"},
        json={"trashed": True},
        timeout=30,
    )
    r.raise_for_status()
    name = r.json().get("name", fid)
    return f"Moved '{name}' to Trash in {account}."


def handle(name: str, args: dict) -> str:
    if not google_auth.oauth_ready():
        return "Google OAuth not configured (needs GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET)."
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
    except RuntimeError as e:
        return str(e)
    except requests.HTTPError as e:
        return f"Drive API error ({args.get('account', '?')}): {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"Drive call failed ({name}): {e}"
    return f"(unknown drive tool: {name})"
