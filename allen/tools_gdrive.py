"""Google Drive tool suite for ALLEN and ALLIE — search, list folder, read file.

Each tool accepts an optional `account` param (default: rahmind.consulting@rmoorind.com).
Required OAuth scope: https://www.googleapis.com/auth/drive
"""

import requests

from . import google_auth

DRIVE_BASE = "https://www.googleapis.com/drive/v3"

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
]

WRITE_NAMES: set = set()  # read-only suite

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
    except RuntimeError as e:
        return str(e)
    except requests.HTTPError as e:
        return f"Drive API error ({args.get('account', '?')}): {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"Drive call failed: {e}"
    return f"(unknown drive tool: {name})"
