"""Shared Google OAuth helper — mints access tokens from stored refresh tokens.

Tokens are keyed by account email in app_config:
    google_refresh_token:{email}  →  refresh token string

The same OAuth client (GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET) covers
all accounts; Rahm authorizes each via /oauth/google/start?account=EMAIL.

Legacy single-account tokens stored under "google_calendar_refresh_token" are still
honored for the default account so existing authorizations keep working.
"""

import requests

from . import db
from .config import settings

TOKEN_URL = "https://oauth2.googleapis.com/token"

DEFAULT_ACCOUNT = "rahmind.consulting@rmoorind.com"

KNOWN_ACCOUNTS = [
    "rmoorind@rmoorind.com",
    "rahmind.consulting@rmoorind.com",
    "rmoorindustries@gmail.com",
    "amg@apex-meridian-group.com",
    "rahm@rmasters.group",
    "kingrahjah@gmail.com",
    "rmooreking@gmail.com",
]

# Combined scope for calendar + gmail + drive in one authorization
UNIFIED_SCOPES = " ".join([
    "https://www.googleapis.com/auth/calendar",
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/drive",
])


def oauth_ready() -> bool:
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


def default_account() -> str:
    return settings.default_google_account or DEFAULT_ACCOUNT


def resolve_account(account: str | None) -> str:
    return (account or "").strip() or default_account()


def refresh_token_for(account: str) -> str | None:
    token = db.get_config(f"google_refresh_token:{account}")
    if token:
        return token
    # Legacy fallback: the old single-account key for the default account
    if account == DEFAULT_ACCOUNT:
        return (
            db.get_config("google_calendar_refresh_token")
            or settings.google_calendar_refresh_token
            or None
        )
    return None


def store_refresh_token(account: str, refresh_token: str) -> None:
    db.set_config(f"google_refresh_token:{account}", refresh_token)


def access_token_for(account: str) -> str:
    rt = refresh_token_for(account)
    if not rt:
        raise RuntimeError(
            f"No refresh token for {account}. "
            f"Authorize via /oauth/google/start?account={account}"
        )
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "refresh_token": rt,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def auth_headers(account: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token_for(account)}",
        "Content-Type": "application/json",
    }


def connected_accounts() -> list[str]:
    """Accounts with a stored refresh token."""
    return [a for a in KNOWN_ACCOUNTS if refresh_token_for(a)]
