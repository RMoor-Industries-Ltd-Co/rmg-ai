"""Refresh-token health check + stale-token guard.

Run: ``python -m allen.token_health`` (add ``--alert`` to WhatsApp Rahm on any failure).

## What actually goes stale (and what doesn't)

Google **refresh tokens do not expire on a clock.** They break only when: the user revokes
access, the token is unused for 6 months, the account password changes, or the OAuth app is
still in "testing" mode (7-day cap). What expires every hour is the **access token**, which
ALLEN already re-mints on demand (``google_auth.access_token_for``). So the real failure this
guard catches is a **revoked/invalid refresh token** silently breaking Calendar/Drive/Gmail —
exactly the class of gap behind a missing morning brief.

Because ``grant_type=refresh_token`` never returns a *new* refresh token, a broken one cannot
be auto-healed here — it needs a fresh consent (``/oauth/google/start?account=EMAIL``). This
tool therefore **detects and alerts loudly**; it does not silently paper over a revocation.

## Doppler write-back

ALLEN's own Google refresh tokens live in Postgres (``app_config``), not Doppler, so there is
nothing to write back for ALLEN. Write-back matters for the *other* PIAAR projects that store
a refresh token as a Doppler secret (e.g. MyTubeScript ``GDRIVE_REFRESH_TOKEN``). For those,
``--writeback`` mirrors the current-known-good value into Doppler so a redeploy never starts
with a stale copy. See ``allen.doppler`` for the token-scope caveat.
"""

from __future__ import annotations

import argparse
import logging
import sys

import requests

from . import db, doppler, google_auth
from .config import settings

logger = logging.getLogger(__name__)

# How the health of one credential is reported.
OK = "ok"
REVOKED = "revoked"       # refresh token rejected by Google — needs re-consent
MISSING = "missing"       # no refresh token stored for a known account
ERROR = "error"           # transient/network/other — not necessarily a token problem


def _probe_google(account: str) -> dict:
    """Try to mint an access token for one account. Classifies the outcome."""
    rt = google_auth.refresh_token_for(account)
    if not rt:
        return {"account": account, "status": MISSING, "detail": "no refresh token stored"}
    try:
        r = requests.post(
            google_auth.TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "refresh_token": rt,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
    except Exception as exc:  # network/transport — transient
        return {"account": account, "status": ERROR, "detail": f"request failed: {exc}"}

    if r.status_code == 200 and r.json().get("access_token"):
        return {"account": account, "status": OK, "detail": "access token minted"}

    # Google returns 400 invalid_grant for a revoked/expired refresh token.
    try:
        err = r.json().get("error", "")
    except Exception:
        err = r.text[:120]
    if r.status_code == 400 and err == "invalid_grant":
        return {"account": account, "status": REVOKED, "detail": "invalid_grant — re-consent required"}
    return {"account": account, "status": ERROR, "detail": f"HTTP {r.status_code}: {err}"}


def check_google() -> list[dict]:
    """Probe every known Google account that has a stored refresh token."""
    if not google_auth.oauth_ready():
        return [{"account": "(all)", "status": ERROR, "detail": "GOOGLE_OAUTH_CLIENT_ID/SECRET not set"}]
    accounts = google_auth.connected_accounts()
    if not accounts:
        return [{"account": "(none)", "status": MISSING, "detail": "no accounts have a stored refresh token"}]
    return [_probe_google(a) for a in accounts]


def run(alert: bool = False, writeback: bool = False) -> list[dict]:
    """Run all checks, print a report, optionally alert + write good tokens back to Doppler.

    Returns the list of result dicts. Exit code (via ``main``) is non-zero if anything is
    REVOKED — that is the actionable, human-in-the-loop failure.
    """
    if not db.db_ready():
        print("token_health: DATABASE_URL not set — cannot read stored refresh tokens.", file=sys.stderr)

    results = check_google()

    print("=== Google OAuth refresh-token health ===")
    for r in results:
        print(f"  [{r['status'].upper():7}] {r['account']:38} {r['detail']}")

    revoked = [r for r in results if r["status"] == REVOKED]
    missing = [r for r in results if r["status"] == MISSING]

    if writeback:
        _writeback_doppler(results)

    if alert and (revoked or missing):
        _alert(revoked, missing)

    if revoked:
        print(f"\n⚠️  {len(revoked)} token(s) need re-consent: "
              + ", ".join(r["account"] for r in revoked))
    else:
        print("\n✅ No revoked tokens.")
    return results


def _writeback_doppler(results: list[dict]) -> None:
    """Mirror the current known-good ALLEN Google refresh token into MyTubeScript's Doppler
    config so its container never redeploys with a stale ``GDRIVE_REFRESH_TOKEN``. Only runs
    for accounts that are OK (never pushes a broken token). No-op without a Doppler token."""
    if not doppler.available():
        print("  (writeback skipped — DOPPLER_TOKEN not set)")
        return
    # Only the drive-capable default account is mirrored downstream today. Extend this map as
    # more projects centralize their refresh tokens here.
    account = google_auth.default_account()
    status = next((r["status"] for r in results if r["account"] == account), None)
    if status != OK:
        print(f"  (writeback skipped — {account} is {status}, refusing to push a non-OK token)")
        return
    rt = google_auth.refresh_token_for(account)
    if not rt:
        return
    ok = doppler.set_secret(
        "GDRIVE_REFRESH_TOKEN", rt,
        project="mytubescript", config="prd",
    )
    print(f"  writeback GDRIVE_REFRESH_TOKEN → mytubescript/prd: {'ok' if ok else 'failed'}")


def _alert(revoked: list[dict], missing: list[dict]) -> None:
    try:
        from . import whatsapp
        lines = ["🔑 ALLEN token health alert"]
        for r in revoked:
            lines.append(f"REVOKED: {r['account']} — re-consent at /oauth/google/start?account={r['account']}")
        for r in missing:
            lines.append(f"MISSING: {r['account']}")
        whatsapp.send_message("\n".join(lines))
    except Exception as exc:
        logger.error("[token_health] alert failed: %s", exc)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Check ALLEN's OAuth refresh tokens.")
    ap.add_argument("--alert", action="store_true", help="WhatsApp Rahm if any token is revoked/missing")
    ap.add_argument("--writeback", action="store_true", help="Mirror known-good tokens into Doppler")
    args = ap.parse_args()
    results = run(alert=args.alert, writeback=args.writeback)
    return 1 if any(r["status"] == REVOKED for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
