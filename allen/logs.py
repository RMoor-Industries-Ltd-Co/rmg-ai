"""Fault-log off-loader — archives the onboard error_log to the ALLEN/LOGS Drive folder.

ALLEN records faults to the DB error_log as they happen (auto-captured tool errors + his
own log_error calls). This scheduler-run job appends the not-yet-offloaded rows to a rolling
per-namespace log file in Drive so Rahm can open/request them, then marks them offloaded.
Self-heals the LOGS folder if missing. Faults are (hopefully) rare, so one rolling file per
namespace stays small; it's tail-capped so it can never grow unbounded.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from . import db, tools_gdrive
from .config import settings

logger = logging.getLogger(__name__)

DRIVE_BASE = tools_gdrive.DRIVE_BASE
_LOGS_FOLDER_KEY = "logs_folder_id"          # app_config: resolved/self-healed LOGS folder id
_LAST_RUN_KEY = "error_offload_last_run"


def _account() -> str:
    return settings.memory_backup_account or settings.atelier_drive_account


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _folder_exists(account: str, folder_id: str) -> bool:
    r = requests.get(
        f"{DRIVE_BASE}/files/{folder_id}",
        headers=tools_gdrive._h(account),
        params={"fields": "id,trashed,mimeType", "supportsAllDrives": "true"},
        timeout=20,
    )
    if r.status_code == 200:
        d = r.json()
        return (not d.get("trashed")) and d.get("mimeType") == "application/vnd.google-apps.folder"
    return False


def resolve_logs_folder(account: Optional[str] = None, self_heal: bool = False) -> str:
    """Return the LOGS folder id, self-healing (creating it under the ALLEN root) if missing."""
    account = account or _account()
    try:
        fid = db.get_config(_LOGS_FOLDER_KEY) or settings.allen_logs_folder_id
    except Exception:
        fid = settings.allen_logs_folder_id
    if fid and not self_heal:
        return fid
    if fid:
        try:
            if _folder_exists(account, fid):
                return fid
        except Exception:
            return fid  # transient check failure — don't recreate
    logger.info("[logs] creating/repairing ALLEN/LOGS folder")
    r = requests.post(
        f"{DRIVE_BASE}/files",
        headers={**tools_gdrive._h(account), "Content-Type": "application/json"},
        json={"name": "LOGS", "mimeType": "application/vnd.google-apps.folder", "parents": [settings.allen_folder_id]},
        params={"fields": "id", "supportsAllDrives": "true"},
        timeout=30,
    )
    r.raise_for_status()
    new_id = r.json()["id"]
    db.set_config(_LOGS_FOLDER_KEY, new_id)
    return new_id


def _find(account: str, folder_id: str, name: str) -> Optional[str]:
    r = requests.get(
        f"{DRIVE_BASE}/files",
        headers=tools_gdrive._h(account),
        params={
            "q": f"'{folder_id}' in parents and name = '{name}' and trashed=false",
            "fields": "files(id)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=30,
    )
    r.raise_for_status()
    files = r.json().get("files", [])
    return files[0]["id"] if files else None


def _read_text(account: str, file_id: str) -> str:
    r = requests.get(
        f"{DRIVE_BASE}/files/{file_id}",
        headers=tools_gdrive._h(account),
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=30,
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def _line(e: dict) -> str:
    return json.dumps(
        {
            "at": str(e.get("created_at")),
            "severity": e.get("severity"),
            "source": e.get("source"),
            "summary": e.get("summary"),
            "detail": e.get("detail"),
        },
        default=str,
        ensure_ascii=False,
    )


def offload() -> dict:
    """Append not-yet-offloaded error rows to the rolling per-namespace Drive log file, then
    mark them offloaded. Returns a structured result (also cached in app_config)."""
    result: dict = {"ran_at": _now_iso(), "namespaces": {}, "ok": True}
    if not (db.db_ready() and tools_gdrive.ready()):
        result.update(ok=False, skipped="db or drive not configured")
        return result

    rows = db.list_errors(only_unoffloaded=True, limit=500)
    if not rows:
        result["offloaded"] = 0
        try:
            db.set_config(_LAST_RUN_KEY, json.dumps(result))
        except Exception:
            pass
        return result

    account = _account()
    try:
        folder_id = resolve_logs_folder(account, self_heal=True)
    except Exception as exc:
        result.update(ok=False, error=f"could not resolve LOGS folder: {str(exc)[:200]}")
        return result

    by_ns: dict[str, list] = {}
    for r in rows:
        by_ns.setdefault(r["namespace"], []).append(r)

    max_bytes = settings.memory_backup_max_bytes
    for ns, ers in by_ns.items():
        try:
            name = f"allen-errors-{ns}.jsonl"
            # rows come newest-first; append oldest-first so the file reads chronologically
            new_block = "\n".join(_line(e) for e in reversed(ers)) + "\n"
            fid = _find(account, folder_id, name)
            if fid:
                existing = _read_text(account, fid)
                content = (existing.rstrip("\n") + "\n" + new_block) if existing.strip() else new_block
                if len(content.encode("utf-8")) > max_bytes:
                    content = content.encode("utf-8")[-max_bytes:].decode("utf-8", "ignore")  # keep the tail
                tools_gdrive._update_file({"file_id": fid, "content": content, "account": account})
            else:
                tools_gdrive._create_file(
                    {"name": name, "content": new_block, "parent_id": folder_id,
                     "mime_type": "text/plain", "account": account}
                )
            db.mark_errors_offloaded([e["id"] for e in ers])
            result["namespaces"][ns] = {"offloaded": len(ers)}
        except Exception as exc:
            result["ok"] = False
            result["namespaces"][ns] = {"error": str(exc)[:200]}

    try:
        db.set_config(_LAST_RUN_KEY, json.dumps(result, default=str))
    except Exception as exc:
        logger.error("[logs] could not record last-run: %s", exc)
    return result


def last_run() -> Optional[dict]:
    try:
        raw = db.get_config(_LAST_RUN_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        return None
