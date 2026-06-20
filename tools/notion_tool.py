"""
Notion tool — Phase 4B.

Requires NOTION_TOKEN in .env.
Setup:
  1. Go to notion.so/profile/integrations → Create integration → copy secret
  2. Add NOTION_TOKEN=secret_xxx to .env
  3. Open each Notion page you want El Fager to access →
     "..." menu → Add connections → select your integration

page_id can be:
  - A bare UUID:  "abc123def456..."
  - A Notion URL: "https://www.notion.so/Page-Title-abc123def456"
  (the last hyphenated segment is the ID)
"""

import os
import re

from dotenv import load_dotenv
load_dotenv()

NOTION_AVAILABLE = bool(os.getenv("NOTION_TOKEN"))
_NOT_SET_UP = (
    "[Notion not set up — add NOTION_TOKEN to .env. "
    "Get it from notion.so/profile/integrations → Create integration.]"
)


def _get_client():
    if not NOTION_AVAILABLE:
        return None
    try:
        from notion_client import Client
        return Client(auth=os.getenv("NOTION_TOKEN"))
    except Exception as e:
        print(f"[El Fager] Notion auth failed: {e}")
        return None


def _extract_page_id(page_id_or_url: str) -> str:
    """Extract bare UUID from a Notion URL or return the string as-is."""
    page_id_or_url = page_id_or_url.strip()
    # Full URL: last path segment after last hyphen or slash contains the 32-char hex ID
    m = re.search(r"([0-9a-f]{32})$", page_id_or_url.replace("-", ""))
    if m:
        raw = m.group(1)
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return page_id_or_url


def _blocks_to_text(blocks: list, max_chars: int = 6000) -> str:
    """Convert Notion block list to plain text."""
    lines = []
    total = 0

    for block in blocks:
        btype = block.get("type", "")
        rich = block.get(btype, {}).get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich)

        if btype.startswith("heading_"):
            level = int(btype[-1])
            text = "#" * level + " " + text
        elif btype == "bulleted_list_item":
            text = "• " + text
        elif btype == "numbered_list_item":
            text = "- " + text
        elif btype == "to_do":
            done = block.get("to_do", {}).get("checked", False)
            text = ("[x] " if done else "[ ] ") + text
        elif btype == "divider":
            text = "---"
        elif btype not in ("paragraph", "code", "quote", "callout"):
            continue

        if not text.strip():
            continue

        lines.append(text)
        total += len(text)
        if total >= max_chars:
            lines.append("[... truncated]")
            break

    return "\n".join(lines)


# ── Public functions ──────────────────────────────────────────────────────────

def search_notion(query: str, n: int = 5) -> str:
    """Search Notion pages by title or content."""
    if not NOTION_AVAILABLE:
        return _NOT_SET_UP
    client = _get_client()
    if client is None:
        return "[Notion auth failed — check NOTION_TOKEN in .env]"
    try:
        results = client.search(
            query=query,
            filter={"property": "object", "value": "page"},
            page_size=n,
        )
        pages = results.get("results", [])
        if not pages:
            return f"No Notion pages found matching '{query}'"

        lines = []
        for i, page in enumerate(pages, 1):
            props = page.get("properties", {})
            title_prop = props.get("title") or props.get("Name") or {}
            title_parts = title_prop.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts) or "(untitled)"
            page_id = page["id"]
            lines.append(f"{i}. {title}\n   ID: {page_id}")

        return "Notion pages found:\n" + "\n".join(lines)
    except Exception as e:
        return f"[Notion error: {e}]"


def read_notion_page(page_id: str) -> str:
    """Read the full text content of a Notion page."""
    if not NOTION_AVAILABLE:
        return _NOT_SET_UP
    client = _get_client()
    if client is None:
        return "[Notion auth failed]"
    try:
        pid = _extract_page_id(page_id)
        # Get page title
        page = client.pages.retrieve(page_id=pid)
        props = page.get("properties", {})
        title_prop = props.get("title") or props.get("Name") or {}
        title_parts = title_prop.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts) or "(untitled)"

        # Get all blocks
        all_blocks = []
        cursor = None
        while True:
            kwargs = {"block_id": pid, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = client.blocks.children.list(**kwargs)
            all_blocks.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        body = _blocks_to_text(all_blocks)
        if not body:
            return f"# {title}\n\n(Page is empty)"
        return f"# {title}\n\n{body}"
    except Exception as e:
        return f"[Notion error: {e}]"


def append_to_notion(page_id: str, text: str) -> str:
    """Append a paragraph block to a Notion page."""
    if not NOTION_AVAILABLE:
        return _NOT_SET_UP
    client = _get_client()
    if client is None:
        return "[Notion auth failed]"
    try:
        pid = _extract_page_id(page_id)
        client.blocks.children.append(
            block_id=pid,
            children=[{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            }],
        )
        return f"Added to Notion page"
    except Exception as e:
        return f"[Notion error: {e}]"


def create_notion_page(title: str, content: str = "", parent_page_id: str = None) -> str:
    """Create a new Notion page, optionally nested under a parent."""
    if not NOTION_AVAILABLE:
        return _NOT_SET_UP
    client = _get_client()
    if client is None:
        return "[Notion auth failed]"
    try:
        if parent_page_id:
            parent = {"page_id": _extract_page_id(parent_page_id)}
        else:
            parent = {"workspace": True}

        children = []
        if content:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                },
            })

        page = client.pages.create(
            parent=parent,
            properties={
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            },
            children=children,
        )
        page_id = page["id"]
        return f"Created Notion page '{title}' — ID: {page_id}"
    except Exception as e:
        return f"[Notion error: {e}]"
