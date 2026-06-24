"""Gmail tool suite for ALLEN and ALLIE — search, read, send, reply, archive.

Each tool accepts an optional `account` param (default: rahmind.consulting@rmoorind.com).
Required OAuth scope: https://mail.google.com/
"""

import base64
import email as email_lib
import email.mime.text
from typing import Optional

import requests

from . import google_auth

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
_ME = "me"

TOOLS = [
    {
        "name": "gmail_search",
        "description": (
            "Search one of Rahm's Gmail inboxes by query. "
            "Returns message summaries (id, from, date, subject). "
            "Specify account to target a particular inbox (default: rahmind.consulting@rmoorind.com)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail query, e.g. 'from:bob@example.com subject:invoice is:unread'",
                },
                "max_results": {"type": "integer", "description": "max messages to return (default 10)"},
                "account": {"type": "string", "description": "Rahm's Google account email to search"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "gmail_read",
        "description": "Read the full body of an email by message_id. Returns from, to, date, subject, and body.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "gmail_send",
        "description": "Send a new email from one of Rahm's accounts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "recipient email(s), comma-separated"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "plain-text email body"},
                "account": {"type": "string", "description": "which of Rahm's accounts to send FROM"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_reply",
        "description": "Reply to an existing email thread by message_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "id of the message to reply to"},
                "body": {"type": "string", "description": "reply body (plain text)"},
                "account": {"type": "string"},
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "gmail_archive",
        "description": "Archive (remove from inbox) an email by message_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
                "account": {"type": "string"},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "gmail_list_accounts",
        "description": "List all of Rahm's Google accounts that have Gmail connected.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

WRITE_NAMES = {"gmail_send", "gmail_reply", "gmail_archive"}


def _h(account: str) -> dict:
    return google_auth.auth_headers(account)


def _search(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    q = args.get("query", "")
    max_r = min(int(args.get("max_results") or 10), 50)
    r = requests.get(
        f"{GMAIL_BASE}/users/{_ME}/messages",
        headers=_h(account),
        params={"q": q, "maxResults": max_r},
        timeout=30,
    )
    r.raise_for_status()
    msgs = r.json().get("messages", [])
    if not msgs:
        return f"No messages found for '{q}' in {account}."
    lines = [f"Found {len(msgs)} message(s) in {account} matching '{q}':"]
    for m in msgs:
        mid = m["id"]
        detail = requests.get(
            f"{GMAIL_BASE}/users/{_ME}/messages/{mid}",
            headers=_h(account),
            params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
            timeout=30,
        ).json()
        hdrs = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        lines.append(
            f"- [{mid}] {hdrs.get('Date', '')[:16]} | "
            f"From: {hdrs.get('From', '?')} | "
            f"Subject: {hdrs.get('Subject', '(no subject)')}"
        )
    return "\n".join(lines)


def _read(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    mid = args["message_id"]
    r = requests.get(
        f"{GMAIL_BASE}/users/{_ME}/messages/{mid}",
        headers=_h(account),
        params={"format": "full"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    hdrs = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    body = _extract_body(data.get("payload", {}))
    return (
        f"From: {hdrs.get('From', '?')}\n"
        f"To: {hdrs.get('To', '?')}\n"
        f"Date: {hdrs.get('Date', '?')}\n"
        f"Subject: {hdrs.get('Subject', '?')}\n\n"
        + body[:4000]
    )


def _extract_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result
    return "(no readable body)"


def _make_raw(
    to: str,
    subject: str,
    body: str,
    sender: str,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> str:
    msg = email.mime.text.MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def _send(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    raw = _make_raw(args["to"], args["subject"], args["body"], sender=account)
    r = requests.post(
        f"{GMAIL_BASE}/users/{_ME}/messages/send",
        headers=_h(account),
        json={"raw": raw},
        timeout=30,
    )
    r.raise_for_status()
    return f"Email sent from {account} to {args['to']} (id: {r.json().get('id')})."


def _reply(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    mid = args["message_id"]
    orig = requests.get(
        f"{GMAIL_BASE}/users/{_ME}/messages/{mid}",
        headers=_h(account),
        params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Message-ID", "References"]},
        timeout=30,
    ).json()
    hdrs = {h["name"]: h["value"] for h in orig.get("payload", {}).get("headers", [])}
    thread_id = orig.get("threadId")
    subject = hdrs.get("Subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    refs = (hdrs.get("References") or "") + " " + (hdrs.get("Message-ID") or "")
    raw = _make_raw(
        to=hdrs.get("From", ""),
        subject=subject,
        body=args["body"],
        sender=account,
        in_reply_to=hdrs.get("Message-ID"),
        references=refs.strip(),
    )
    payload: dict = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    r = requests.post(
        f"{GMAIL_BASE}/users/{_ME}/messages/send",
        headers=_h(account),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return f"Reply sent from {account} (id: {r.json().get('id')})."


def _archive(args: dict) -> str:
    account = google_auth.resolve_account(args.get("account"))
    mid = args["message_id"]
    r = requests.post(
        f"{GMAIL_BASE}/users/{_ME}/messages/{mid}/modify",
        headers=_h(account),
        json={"removeLabelIds": ["INBOX"]},
        timeout=30,
    )
    r.raise_for_status()
    return f"Archived message {mid} in {account}."


def _list_accounts(_args: dict) -> str:
    connected = google_auth.connected_accounts()
    if not connected:
        return (
            "No Google accounts connected yet. "
            "Authorize each via /oauth/google/start?account=EMAIL."
        )
    lines = ["Connected Google accounts (Gmail + Calendar + Drive):"]
    for a in connected:
        lines.append(f"  • {a}")
    return "\n".join(lines)


def handle(name: str, args: dict) -> str:
    if not google_auth.oauth_ready():
        return "Google OAuth not configured (needs GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET)."
    args = args or {}
    try:
        if name == "gmail_search":
            return _search(args)
        if name == "gmail_read":
            return _read(args)
        if name == "gmail_send":
            return _send(args)
        if name == "gmail_reply":
            return _reply(args)
        if name == "gmail_archive":
            return _archive(args)
        if name == "gmail_list_accounts":
            return _list_accounts(args)
    except RuntimeError as e:
        return str(e)
    except requests.HTTPError as e:
        return f"Gmail API error ({args.get('account', '?')}): {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"Gmail call failed: {e}"
    return f"(unknown gmail tool: {name})"
