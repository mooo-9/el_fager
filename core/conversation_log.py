"""
ConversationLogger — appends every conversation turn to a daily JSONL file.

Each entry: {timestamp, role, content, tools_used}
Files live at data/conversations/YYYY-MM-DD.jsonl
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


class ConversationLogger:
    LOG_DIR = Path("data/conversations")

    def __init__(self):
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _today_file(self) -> Path:
        return self.LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"

    def _file_for(self, date_str: str) -> Path | None:
        d = self._parse_date(date_str)
        if d is None:
            return None
        return self.LOG_DIR / f"{d.strftime('%Y-%m-%d')}.jsonl"

    def _parse_date(self, date_str: str) -> datetime | None:
        date_str = date_str.strip().lower()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if date_str in ("today", ""):
            return today
        if date_str == "yesterday":
            return today - timedelta(days=1)
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if date_str in weekdays:
            target_dow = weekdays.index(date_str)
            current_dow = today.weekday()
            days_back = (current_dow - target_dow) % 7
            if days_back == 0:
                days_back = 7
            return today - timedelta(days=days_back)
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

    def log(self, role: str, content: str, tools_used: list[str] | None = None) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content[:4000],
            "tools_used": tools_used or [],
        }
        try:
            with self._today_file().open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def read_day(self, date_str: str = "today") -> list[dict]:
        fpath = self._file_for(date_str)
        if fpath is None or not fpath.exists():
            return []
        entries = []
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        return entries

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        query_lower = query.lower()
        results = []
        for fpath in sorted(self.LOG_DIR.glob("*.jsonl"), reverse=True):
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if query_lower in entry.get("content", "").lower():
                        entry["_file"] = fpath.stem
                        results.append(entry)
                        if len(results) >= max_results:
                            return results
                except Exception:
                    pass
        return results

    def stats(self) -> dict:
        files = sorted(self.LOG_DIR.glob("*.jsonl"))
        total_turns = 0
        total_days = len(files)
        tool_counts: dict[str, int] = {}
        for fpath in files:
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    total_turns += 1
                    for t in entry.get("tools_used", []):
                        tool_counts[t] = tool_counts.get(t, 0) + 1
                except Exception:
                    pass
        top_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
        return {
            "total_turns": total_turns,
            "total_days": total_days,
            "avg_turns_per_day": round(total_turns / max(total_days, 1), 1),
            "top_tools": top_tools,
        }
