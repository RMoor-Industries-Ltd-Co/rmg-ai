"""GitHub tool client — ALLEN's own bot identity (allen-piaar-control-bot) across the
RMoor-Industries-Ltd-Co org. Authenticates as a GitHub App (private key -> signed JWT ->
short-lived installation token, minted on demand and cached until it expires).

Scope, enforced here (not just by the App's granted permissions): ALLEN reads issues,
PRs, and file contents on any repo the App is installed on, and writes issues/comments
anywhere — but file-contents writes are allowed ONLY on rmg-piaar-system (the initiative
registry), never on a code repo. Claude Code remains the only actor that writes code."""

import base64
import time

import jwt
import requests

from .config import settings

API = "https://api.github.com"
ORG = "RMoor-Industries-Ltd-Co"

# Only rmg-piaar-system may receive file-contents writes (the initiative registry).
# Every other installed repo is issues-only for ALLEN; Claude Code owns their contents.
CONTENTS_WRITE_REPOS = {"rmg-piaar-system"}

TOOLS = [
    {
        "name": "github_list_issues",
        "description": "List issues in a repo (org: RMoor-Industries-Ltd-Co). Provide repo (e.g. 'rmg-creator-os'); "
                       "optionally state (open|closed|all, default open).",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "state": {"type": "string"}},
            "required": ["repo"],
        },
    },
    {
        "name": "github_get_issue",
        "description": "Get one issue in full — title, body, state, labels. Provide repo and issue_number.",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "issue_number": {"type": "integer"}},
            "required": ["repo", "issue_number"],
        },
    },
    {
        "name": "github_list_pull_requests",
        "description": "List pull requests in a repo. Provide repo; optionally state (open|closed|all, default open).",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "state": {"type": "string"}},
            "required": ["repo"],
        },
    },
    {
        "name": "github_get_pull_request",
        "description": "Get one pull request in full — title, body, state, branch, mergeable status. "
                       "Provide repo and pr_number.",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "pr_number": {"type": "integer"}},
            "required": ["repo", "pr_number"],
        },
    },
    {
        "name": "github_read_file",
        "description": "Read a file's contents from a repo. Provide repo and path (e.g. 'docs/INITIATIVES.md'); "
                       "optionally ref (branch/sha, default the repo's default branch).",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "path": {"type": "string"}, "ref": {"type": "string"}},
            "required": ["repo", "path"],
        },
    },
]

WRITE_TOOLS = [
    {
        "name": "github_create_issue",
        "description": "Open a new issue in a repo — e.g. to flag work for Claude Code to pick up next session. "
                       "Provide repo, title; optionally body.",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}},
            "required": ["repo", "title"],
        },
    },
    {
        "name": "github_comment_issue",
        "description": "Add a comment to an existing issue or pull request. Provide repo, issue_number (PRs share "
                       "the issue numbering), and comment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"}, "issue_number": {"type": "integer"}, "comment": {"type": "string"},
            },
            "required": ["repo", "issue_number", "comment"],
        },
    },
    {
        "name": "github_update_file",
        "description": "Update a file's contents. ONLY permitted in rmg-piaar-system (the initiative registry) — "
                       "ALLEN never writes code. Provide repo ('rmg-piaar-system'), path, content (full new file "
                       "text), and message (commit message).",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"}, "path": {"type": "string"},
                "content": {"type": "string"}, "message": {"type": "string"},
            },
            "required": ["repo", "path", "content", "message"],
        },
    },
]

WRITE_NAMES = {t["name"] for t in WRITE_TOOLS}  # mutating tools — recorded in the audit log

_token_cache: dict = {"token": None, "expires_at": 0.0}


def _app_jwt() -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": settings.github_app_id}
    key = settings.github_app_private_key.replace("\\n", "\n")
    return jwt.encode(payload, key, algorithm="RS256")


def _installation_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    r = requests.post(
        f"{API}/app/installations/{settings.github_app_installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {_app_jwt()}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _token_cache["token"] = data["token"]
    # expires_at is ISO 8601; parse loosely to a monotonic-ish deadline via time.time() + ~55min fallback.
    from datetime import datetime, timezone as tz
    try:
        exp = datetime.strptime(data["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.utc).timestamp()
    except (KeyError, ValueError):
        exp = time.time() + 55 * 60
    _token_cache["expires_at"] = exp
    return _token_cache["token"]


def _h() -> dict:
    return {"Authorization": f"Bearer {_installation_token()}", "Accept": "application/vnd.github+json"}


def _get(path: str, params: dict | None = None) -> dict | list:
    r = requests.get(f"{API}{path}", headers=_h(), params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _send(method: str, path: str, body: dict) -> dict:
    r = requests.request(method, f"{API}{path}", headers=_h(), json=body, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}


def _list_issues(repo: str, state: str) -> str:
    issues = _get(f"/repos/{ORG}/{repo}/issues", {"state": state or "open", "per_page": 30})
    issues = [i for i in issues if "pull_request" not in i]  # GitHub's issues endpoint includes PRs
    if not issues:
        return f"No {state or 'open'} issues in {repo}."
    return "\n".join(f"- #{i['number']} {i['title']} [{i['state']}]" for i in issues)


def _get_issue(repo: str, number: int) -> str:
    i = _get(f"/repos/{ORG}/{repo}/issues/{number}")
    body = (i.get("body") or "").strip() or "(no body)"
    labels = ", ".join(l["name"] for l in i.get("labels", [])) or "none"
    return f"#{i['number']} {i['title']} [{i['state']}]\nLabels: {labels}\n\n{body[:4000]}"


def _list_pulls(repo: str, state: str) -> str:
    prs = _get(f"/repos/{ORG}/{repo}/pulls", {"state": state or "open", "per_page": 30})
    if not prs:
        return f"No {state or 'open'} pull requests in {repo}."
    return "\n".join(f"- #{p['number']} {p['title']} [{p['state']}] {p['head']['ref']} -> {p['base']['ref']}" for p in prs)


def _get_pull(repo: str, number: int) -> str:
    p = _get(f"/repos/{ORG}/{repo}/pulls/{number}")
    body = (p.get("body") or "").strip() or "(no body)"
    return (
        f"#{p['number']} {p['title']} [{p['state']}]\n"
        f"{p['head']['ref']} -> {p['base']['ref']} | mergeable: {p.get('mergeable')}\n\n{body[:4000]}"
    )


def read_file_full(repo: str, path: str, ref: str | None = None) -> str | None:
    """Full, untruncated file contents — for read-modify-write callers (e.g. forms.py's
    github_initiative dispatch). Returns None for a directory listing."""
    params = {"ref": ref} if ref else {}
    data = _get(f"/repos/{ORG}/{repo}/contents/{path}", params)
    if isinstance(data, list):
        return None
    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


def _read_file(repo: str, path: str, ref: str | None) -> str:
    params = {"ref": ref} if ref else {}
    data = _get(f"/repos/{ORG}/{repo}/contents/{path}", params)
    if isinstance(data, list):
        return f"{path} is a directory: " + ", ".join(e["name"] for e in data)
    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return content[:8000]  # display-facing tool result — conversational, truncation is fine here


def _create_issue(args: dict) -> str:
    body = {"title": args["title"]}
    if args.get("body"):
        body["body"] = args["body"]
    i = _send("POST", f"/repos/{ORG}/{args['repo']}/issues", body)
    return f"Opened issue #{i['number']} in {args['repo']}: {i['html_url']}"


def _comment_issue(args: dict) -> str:
    _send("POST", f"/repos/{ORG}/{args['repo']}/issues/{args['issue_number']}/comments", {"body": args["comment"]})
    return f"Commented on {args['repo']}#{args['issue_number']}."


def _update_file(args: dict) -> str:
    repo = args["repo"]
    if repo not in CONTENTS_WRITE_REPOS:
        return f"Not permitted: ALLEN can only write file contents in {', '.join(CONTENTS_WRITE_REPOS)}, not {repo}."
    path = args["path"]
    existing = _get(f"/repos/{ORG}/{repo}/contents/{path}")
    sha = existing["sha"] if isinstance(existing, dict) else None
    payload = {
        "message": args["message"],
        "content": base64.b64encode(args["content"].encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    result = _send("PUT", f"/repos/{ORG}/{repo}/contents/{path}", payload)
    return f"Updated {repo}/{path}: {result.get('commit', {}).get('html_url', 'done')}"


def handle(name: str, args: dict) -> str:
    if not settings.github_ready:
        return "GitHub is not configured (allen-piaar-control-bot App credentials missing)."
    args = args or {}
    try:
        if name == "github_list_issues":
            return _list_issues(args["repo"], args.get("state"))
        if name == "github_get_issue":
            return _get_issue(args["repo"], args["issue_number"])
        if name == "github_list_pull_requests":
            return _list_pulls(args["repo"], args.get("state"))
        if name == "github_get_pull_request":
            return _get_pull(args["repo"], args["pr_number"])
        if name == "github_read_file":
            return _read_file(args["repo"], args["path"], args.get("ref"))
        # writes
        if name == "github_create_issue":
            return _create_issue(args)
        if name == "github_comment_issue":
            return _comment_issue(args)
        if name == "github_update_file":
            return _update_file(args)
    except requests.HTTPError as e:
        return f"GitHub API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"GitHub call failed: {e}"
    return f"(unknown GitHub tool: {name})"
