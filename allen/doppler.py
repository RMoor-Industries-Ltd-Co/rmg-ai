"""Doppler read/write helper — used by the token-health check to centralize refresh-token
status and, where applicable, write a rotated credential back to a project's Doppler config
so a running container has no gap after a refresh.

A single Doppler **service token** (env ``DOPPLER_TOKEN``) authenticates the API. A service
token is normally scoped to ONE project+config, so cross-project write-back needs either a
personal/service-account token with wider scope or one token per project (pass ``token``
explicitly). Read the Doppler API docs before widening a token's scope.

Nothing here raises on a missing token — callers get ``None``/``False`` and can degrade to a
report-only run. Never log secret values.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.doppler.com/v3"


def _token(token: Optional[str]) -> Optional[str]:
    return token or os.environ.get("DOPPLER_TOKEN") or None


def available(token: Optional[str] = None) -> bool:
    return bool(_token(token))


def get_secret(
    name: str,
    project: Optional[str] = None,
    config: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """Read one secret's raw value. ``project``/``config`` are optional when the service
    token is already scoped to a single config. Returns ``None`` on any failure."""
    tok = _token(token)
    if not tok:
        return None
    params = {"name": name}
    if project:
        params["project"] = project
    if config:
        params["config"] = config
    try:
        r = requests.get(
            f"{API_BASE}/configs/config/secret",
            params=params,
            auth=(tok, ""),
            timeout=30,
        )
        r.raise_for_status()
        return (r.json().get("value") or {}).get("raw")
    except Exception as exc:
        logger.error("[doppler] read %s failed: %s", name, exc)
        return None


def set_secret(
    name: str,
    value: str,
    project: Optional[str] = None,
    config: Optional[str] = None,
    token: Optional[str] = None,
) -> bool:
    """Write (upsert) one secret. Returns True on success. The value is never logged."""
    tok = _token(token)
    if not tok:
        logger.warning("[doppler] no token — cannot write %s", name)
        return False
    body: dict = {"secrets": {name: value}}
    if project:
        body["project"] = project
    if config:
        body["config"] = config
    try:
        r = requests.post(
            f"{API_BASE}/configs/config/secrets",
            json=body,
            auth=(tok, ""),
            timeout=30,
        )
        r.raise_for_status()
        logger.info("[doppler] wrote %s to %s/%s", name, project or "(scoped)", config or "(scoped)")
        return True
    except Exception as exc:
        logger.error("[doppler] write %s failed: %s", name, exc)
        return False
