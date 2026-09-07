"""
History tool — read, search, and export logged conversations.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from core.conversation_log import ConversationLogger
from core import atomic

_logger = ConversationLogger()


def _format_entry(entry: dict) -> str:
    ts = entry.get("timestamp", "")
    time_part = ts[11:16] if len(ts) >= 16 else "?"
    role = "Mo" if entry.get("role") == "user" else "El Fager"
    content = entry.get("content", "").strip()
    tools = entry.get("tools_used", [])
    line = f"[{time_part} {role}] {content}"
    if tools:
        line += f"  (tools: {', '.join(tools)})"
    return line


def read_conversation(date_str: str = "today") -> str:
    entries = _logger.read_day(date_str)
    if not entries:
        date_display = date_str if date_str != "today" else "today"
        return f"No conversation recorded for {date_display}."
    lines = [f"Conversation — {date_str} ({len(entries)} turns):"]
    for e in entries:
        lines.append(_format_entry(e))
    return "\n".join(lines)


def search_conversations(query: str, n: int = 10) -> str:
    results = _logger.search(query, max_results=n)
    if not results:
        return f"No matches for '{query}' in conversation history."
    lines = [f"{len(results)} result(s) for '{query}':"]
    for e in results:
        date = e.get("_file", "?")
        lines.append(f"[{date}] {_format_entry(e)}")
    return "\n".join(lines)


def conversation_stats() -> str:
    stats = _logger.stats()
    lines = [
        f"Conversation history:",
        f"  Days active: {stats['total_days']}",
        f"  Total turns: {stats['total_turns']}",
        f"  Avg turns/day: {stats['avg_turns_per_day']}",
    ]
    if stats["top_tools"]:
        lines.append("  Most-used tools:")
        for tool, count in stats["top_tools"]:
            lines.append(f"    • {tool}: {count}×")
    return "\n".join(lines)


def export_conversation(date_str: str = "today") -> str:
    entries = _logger.read_day(date_str)
    if not entries:
        return f"No conversation for {date_str} to export."
    out_dir = Path("data/conversations")
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = date_str.replace(" ", "_")
    out_path = out_dir / f"export_{date_tag}.txt"
    lines = [f"El Fager Conversation — {date_str}", "=" * 40]
    for e in entries:
        lines.append(_format_entry(e))
    atomic.write(out_path, "\n".join(lines), encoding="utf-8")
    try:
        os.startfile(str(out_path))
    except Exception:
        pass
    return f"Exported {len(entries)} turns to {out_path.name}."
