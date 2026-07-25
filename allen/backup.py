"""Memory backup — durable snapshots of ALLEN's namespaced memory.

Writes each namespace's active memory to a local file AND to the ALLEN/MEMORY Google
Drive folder, keeping ONE rolling latest snapshot per namespace (``allen-<ns>.json``).
Runs hourly from ``scheduler.py``. This is the in-app, self-maintaining version of the
older out-of-repo daily cron that drops dated dumps into ALLEN-Backups — it complements
those archives rather than replacing them, and it self-heals the target folder if it
ever goes missing (recreating it under the ALLEN root and remembering the new id).

The snapshot shape matches the existing dated dumps: a JSON array of
``{id, content, lane, unit, silo, pinned, created_at}``.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from . import db, tools_gdrive
from .config import settings

logger = logging.getLogger(__name__)

DRIVE_BASE = tools_gdrive.DRIVE_BASE

_LAST_RUN_KEY = "memory_backup_last_run"     # app_config: JSON blob of the most recent run
_MEMORY_FOLDER_KEY = "memory_folder_id"      # app_config: resolved/self-healed MEMORY folder id


def _account() -> str:
    return settings.memory_backup_account or settings.atelier_drive_account


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def snapshot(namespace: str) -> str:
    """Full JSON snapshot of a namespace's active memories (same shape as the daily dumps)."""
    mems = db.list_memories(namespace)
    slim = [
        {
            "id": m.get("id"),
            "content": m.get("content"),
            "lane": m.get("lane"),
            "unit": m.get("unit"),
            "silo": m.get("silo"),
            "pinned": m.get("pinned"),
            "created_at": m.get("created_at"),
        }
        for m in mems
    ]
    return json.dumps(slim, default=_json_default, ensure_ascii=False)


# ---- local mirror ----

def _write_local(namespace: str, data: str) -> Optional[str]:
    try:
        os.makedirs(settings.memory_local_dir, exist_ok=True)
        path = os.path.join(settings.memory_local_dir, f"allen-{namespace}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data)
        return path
    except Exception as exc:
        logger.error("[backup] local write failed for %s: %s", namespace, exc)
        return None


# ---- Drive folder resolution + self-heal ----

def _folder_exists(account: str, folder_id: str) -> bool:
    r = requests.get(
        f"{DRIVE_BASE}/files/{folder_id}",
        headers=tools_gdrive._h(account),
        params={"fields": "id,name,trashed,mimeType", "supportsAllDrives": "true"},
        timeout=20,
    )
    if r.status_code == 200:
        d = r.json()
        return (not d.get("trashed")) and d.get("mimeType") == "application/vnd.google-apps.folder"
    return False


def resolve_memory_folder(account: Optional[str] = None, self_heal: bool = False) -> str:
    """Return the MEMORY folder id, preferring a self-healed id stored in app_config over
    the configured default. When self_heal=True and the folder is missing, recreate a
    'MEMORY' folder under the ALLEN root and persist the new id."""
    account = account or _account()
    try:
        fid = db.get_config(_MEMORY_FOLDER_KEY) or settings.allen_memory_folder_id
    except Exception:  # DB read blip — fall back to the configured default
        fid = settings.allen_memory_folder_id
    if not self_heal:
        return fid
    try:
        if _folder_exists(account, fid):
            return fid
    except Exception as exc:
        logger.error("[backup] could not verify MEMORY folder %s: %s", fid, exc)
        return fid  # don't recreate on a transient check failure
    # Missing — recreate under the ALLEN root and remember it.
    logger.warning("[backup] MEMORY folder %s missing — recreating under ALLEN root", fid)
    r = requests.post(
        f"{DRIVE_BASE}/files",
        headers={**tools_gdrive._h(account), "Content-Type": "application/json"},
        json={
            "name": "MEMORY",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [settings.allen_folder_id],
        },
        params={"fields": "id", "supportsAllDrives": "true"},
        timeout=30,
    )
    r.raise_for_status()
    new_id = r.json()["id"]
    db.set_config(_MEMORY_FOLDER_KEY, new_id)
    logger.info("[backup] recreated MEMORY folder as %s", new_id)
    return new_id


# ---- Drive upsert (rolling latest per namespace) ----

def _drive_find(account: str, folder_id: str, name: str) -> Optional[str]:
    q = f"'{folder_id}' in parents and name = '{name}' and trashed=false"
    r = requests.get(
        f"{DRIVE_BASE}/files",
        headers=tools_gdrive._h(account),
        params={
            "q": q,
            "fields": "files(id,name)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=30,
    )
    r.raise_for_status()
    files = r.json().get("files", [])
    return files[0]["id"] if files else None


def _drive_upsert(account: str, folder_id: str, name: str, data: str) -> None:
    existing = _drive_find(account, folder_id, name)
    if existing:
        tools_gdrive._update_file({"file_id": existing, "content": data, "account": account})
    else:
        tools_gdrive._create_file(
            {
                "name": name,
                "content": data,
                "parent_id": folder_id,
                "mime_type": "application/json",
                "account": account,
            }
        )


# ---- top-level run ----

def run_all() -> dict:
    """Snapshot every namespace to local disk + the ALLEN/MEMORY Drive folder.
    Returns a structured result (also cached in app_config for /health)."""
    result: dict = {"ran_at": _now_iso(), "namespaces": {}, "ok": True}

    if not (settings.memory_backup_enabled and db.db_ready()):
        result.update(ok=False, skipped="memory backup disabled or DB not configured")
        return result
    drive_up = tools_gdrive.ready()
    account = _account()

    folder_id = resolve_memory_folder(account, self_heal=drive_up) if drive_up else settings.allen_memory_folder_id
    result["folder_id"] = folder_id

    for ns in db.distinct_memory_namespaces():
        entry: dict = {}
        try:
            data = snapshot(ns)
            entry["count"] = len(json.loads(data))
            entry["local"] = bool(_write_local(ns, data))
            if drive_up:
                try:
                    _drive_upsert(account, folder_id, f"allen-{ns}.json", data)
                    entry["drive"] = True
                except Exception as exc:
                    entry["drive"] = False
                    entry["error"] = str(exc)[:200]
                    result["ok"] = False
            else:
                entry["drive"] = False
                entry["error"] = "drive not configured"
        except Exception as exc:
            entry["error"] = str(exc)[:200]
            result["ok"] = False
        result["namespaces"][ns] = entry

    try:
        db.set_config(_LAST_RUN_KEY, json.dumps(result))
    except Exception as exc:
        logger.error("[backup] could not record last-run status: %s", exc)
    return result


def last_run() -> Optional[dict]:
    try:
        raw = db.get_config(_LAST_RUN_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---- directory report (for /health) ----

def _folders() -> list[tuple]:
    return [
        ("allen_root", settings.allen_folder_id, "ALLEN"),
        ("memory", resolve_memory_folder(), "ALLEN/MEMORY"),
        ("backups", settings.allen_backups_folder_id, "ALLEN-Backups"),
    ]


def directory_report(live: bool = False) -> dict:
    """Report ALLEN's Drive directory targets. With live=True, actually probe each folder
    (reachable / missing) — otherwise just echo the configured ids without a Drive call."""
    account = _account()
    can_probe = live and tools_gdrive.ready()
    out: dict = {}
    for key, fid, label in _folders():
        entry = {"id": fid, "label": label}
        if can_probe:
            try:
                r = requests.get(
                    f"{DRIVE_BASE}/files/{fid}",
                    headers=tools_gdrive._h(account),
                    params={"fields": "id,name,trashed", "supportsAllDrives": "true"},
                    timeout=15,
                )
                if r.status_code == 200 and not r.json().get("trashed"):
                    entry["status"] = "ok"
                    entry["name"] = r.json().get("name")
                elif r.status_code in (403, 404):
                    entry["status"] = "missing"
                else:
                    entry["status"] = f"http {r.status_code}"
            except Exception as exc:
                entry["status"] = "error"
                entry["error"] = str(exc)[:120]
        else:
            entry["status"] = "configured"
        out[key] = entry
    return out
