"""Notion tool client — ALLIE's (and ALLEN's) window into the 'bank of wisdom'. Read-only:
search the workspace and read a page's text."""

import requests

from .config import settings

BASE = "https://api.notion.com/v1"
_VERSION = "2022-06-28"

TOOLS = [
    {
        "name": "notion_search",
        "description": "Search Rahm's Notion workspace (the knowledge base / 'bank of wisdom') by keyword. "
                       "Returns matching page titles and ids. Use notion_get_page to read one.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "keywords to search for"}},
            "required": ["query"],
        },
    },
    {
        "name": "notion_get_page",
        "description": "Read the text content of a Notion page by id (from notion_search).",
        "input_schema": {
            "type": "object",
            "properties": {"page_id": {"type": "string", "description": "Notion page id"}},
            "required": ["page_id"],
        },
    },
]


def _h() -> dict:
    return {
        "Authorization": f"Bearer {settings.notion_api_key}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def _title_of(obj: dict) -> str:
    props = obj.get("properties", {})
    for v in props.values():
        if v.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in v.get("title", [])) or "(untitled)"
    # databases carry a top-level title array
    if obj.get("object") == "database":
        return "".join(t.get("plain_text", "") for t in obj.get("title", [])) or "(untitled db)"
    return "(untitled)"


def _search(query: str) -> str:
    r = requests.post(f"{BASE}/search", headers=_h(), json={"query": query, "page_size": 10}, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        return "No Notion pages matched."
    lines = []
    for o in results:
        lines.append(f"- {_title_of(o)} [{o.get('object')}] (id {o.get('id')})")
    return "\n".join(lines)


def _rich(block: dict) -> str:
    t = block.get("type", "")
    data = block.get(t, {})
    rt = data.get("rich_text", []) if isinstance(data, dict) else []
    text = "".join(x.get("plain_text", "") for x in rt)
    if t.startswith("heading"):
        return f"\n## {text}"
    if t in ("bulleted_list_item", "numbered_list_item", "to_do"):
        return f"- {text}"
    return text


def _blocks_text(block_id: str, depth: int = 0) -> list[str]:
    if depth > 2:
        return []
    r = requests.get(f"{BASE}/blocks/{block_id}/children", headers=_h(), params={"page_size": 100}, timeout=30)
    r.raise_for_status()
    out: list[str] = []
    for b in r.json().get("results", []):
        line = _rich(b)
        if line.strip():
            out.append(("  " * depth) + line)
        if b.get("has_children"):
            out.extend(_blocks_text(b["id"], depth + 1))
    return out


def _get_page(page_id: str) -> str:
    title = "(untitled)"
    try:
        pg = requests.get(f"{BASE}/pages/{page_id}", headers=_h(), timeout=30).json()
        title = _title_of(pg)
    except Exception:
        pass
    body = "\n".join(_blocks_text(page_id))[:9000]
    return f"# {title}\n\n{body or '(empty page)'}"


def handle(name: str, args: dict) -> str:
    if not settings.notion_ready:
        return "Notion is not configured."
    args = args or {}
    try:
        if name == "notion_search":
            return _search(args["query"])
        if name == "notion_get_page":
            return _get_page(args["page_id"])
    except requests.HTTPError as e:
        return f"Notion API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return f"Notion call failed: {e}"
    return f"(unknown Notion tool: {name})"
