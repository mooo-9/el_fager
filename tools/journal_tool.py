"""
Voice journal — Phase 6F.

Saves timestamped Markdown entries to data/journal/YYYY-MM-DD.md.
No external dependencies — stdlib only.

Functions:
  Core CRUD: save_journal_entry, read_journal, delete_journal_entry,
             edit_journal_entry, append_to_entry, rename_entry_title
  Browse:    list_journal_entries, read_journal_range, weekly_summary,
             most_recent_entry, random_memory
  Search:    search_journal, search_by_tag
  Tags/Mood: list_tags, mood_summary
  Pins:      pin_entry, list_pinned_entries
  Stats:     get_journal_stats, journal_streak
  Export:    export_journal, copy_journal_to_clipboard
"""

import json
import os
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from core import atomic

_JOURNAL_DIR = Path("data/journal")
_PINS_FILE   = _JOURNAL_DIR / "pins.json"

_WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]
_MOOD_RE = re.compile(r"\*Mood:\s*([^|*\n]+)", re.IGNORECASE)
_TAG_RE  = re.compile(r"#(\w+)")


# ── Date helpers ──────────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().isoformat()


def _journal_path(date_str: str = None) -> Path:
    d = date_str or _today()
    return _JOURNAL_DIR / f"{d}.md"


def _parse_date(date_str: str) -> str | None:
    """
    Accept: YYYY-MM-DD | today | yesterday | N days ago | weekday name
    Returns ISO date string or None if unparsable.
    """
    if not date_str or date_str.lower() == "today":
        return _today()

    s = date_str.lower().strip()

    if s == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()

    m = re.match(r"^(\d+)\s+days?\s+ago$", s)
    if m:
        return (date.today() - timedelta(days=int(m.group(1)))).isoformat()

    for i, name in enumerate(_WEEKDAY_NAMES):
        if s in (name, f"last {name}", f"this {name}"):
            today_dow = date.today().weekday()
            diff = (today_dow - i) % 7
            if diff == 0:
                diff = 7
            return (date.today() - timedelta(days=diff)).isoformat()

    try:
        date.fromisoformat(date_str)
        return date_str
    except ValueError:
        return None


def _date_label(date_str: str) -> str:
    """Convert ISO date string to readable label."""
    try:
        return date.fromisoformat(date_str).strftime("%A, %b %d %Y")
    except Exception:
        return date_str


# ── Entry parsing helpers ─────────────────────────────────────────────────────

def _split_entries(content: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Split file content into (file_header, [(heading_line, body_text), ...]).
    Heading lines match '^## '.
    """
    parts = re.split(r"(^## .+$)", content, flags=re.MULTILINE)
    file_header = parts[0]
    entries = []
    for i in range(1, len(parts), 2):
        heading = parts[i]
        body    = parts[i + 1] if i + 1 < len(parts) else ""
        entries.append((heading, body))
    return file_header, entries


def _rebuild_file(file_header: str, entries: list[tuple[str, str]]) -> str:
    result = file_header
    for heading, body in entries:
        result += heading + body
    return result


def _count_words(text: str) -> int:
    return len(text.split())


def _resolve_entry(entry_number: int, date_str: str = None):
    """Load file and return (path, file_header, entries, entry_index) or error string."""
    d = _parse_date(date_str) if date_str else _today()
    if d is None:
        return f"Invalid date '{date_str}'."

    path = _journal_path(d)
    if not path.exists():
        return f"No journal for {d}."

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Journal error: {e}]"

    file_header, entries = _split_entries(content)
    if not entries:
        return f"No entries in journal for {d}."

    n = int(entry_number)
    if n < 1 or n > len(entries):
        e_word = "entry" if len(entries) == 1 else "entries"
        return f"Entry {n} not found — journal for {d} has {len(entries)} {e_word}."

    return path, file_header, entries, n - 1, d


# ── Pin helpers ───────────────────────────────────────────────────────────────

def _load_pins() -> list[dict]:
    try:
        if _PINS_FILE.exists():
            return json.loads(_PINS_FILE.read_text(encoding="utf-8"))
        return []
    except Exception:
        return []


def _save_pins(pins: list[dict]) -> None:
    _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    atomic.write(_PINS_FILE, json.dumps(pins, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Core CRUD ─────────────────────────────────────────────────────────────────

def save_journal_entry(
    text: str,
    title: str = None,
    mood: str = None,
    tags: list = None,
) -> str:
    """
    Append a timestamped entry to today's journal file.

    title — optional heading (e.g. 'Study notes', 'Random thought')
    mood  — optional mood word (e.g. 'happy', 'stressed', 'focused', 'tired')
    tags  — optional list of topic tags (e.g. ['study', 'uni', 'important'])
    """
    try:
        _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        path     = _journal_path()
        now      = datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%Y-%m-%d")

        heading = f"## {time_str}"
        if title:
            heading += f" — {title.strip()}"

        body = text.strip()

        meta_parts = []
        if mood:
            meta_parts.append(f"Mood: {mood.strip().lower()}")
        if tags:
            tag_str = " ".join(f"#{t.strip().lstrip('#')}" for t in tags)
            meta_parts.append(tag_str)
        if meta_parts:
            body += f"\n*{' | '.join(meta_parts)}*"

        entry = f"{heading}\n{body}\n\n"

        if not path.exists():
            date_header = f"# Journal — {now.strftime('%A, %B %d %Y')}\n\n"
            entry = date_header + entry

        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)

        return f"Saved to journal [{date_str} {time_str}]"
    except Exception as e:
        return f"[Journal error: {e}]"


def read_journal(date_str: str = None) -> str:
    """
    Read a journal file.
    date_str — 'today', 'yesterday', 'N days ago', weekday name, or 'YYYY-MM-DD'.
    Defaults to today.
    """
    d = _parse_date(date_str) if date_str else _today()
    if d is None:
        return f"Invalid date '{date_str}' — try 'today', 'yesterday', '3 days ago', or YYYY-MM-DD."

    path = _journal_path(d)
    if not path.exists():
        return f"No journal entry for {d}."

    try:
        content = path.read_text(encoding="utf-8").strip()
        return content if content else f"Journal for {d} is empty."
    except Exception as e:
        return f"[Journal error: {e}]"


def delete_journal_entry(entry_number: int, date_str: str = None) -> str:
    """
    Delete a specific entry from a day's journal (1 = first entry of that day).
    Removes the file entirely if it was the only entry.
    """
    result = _resolve_entry(entry_number, date_str)
    if isinstance(result, str):
        return result
    path, file_header, entries, idx, d = result

    deleted_heading = entries[idx][0].lstrip("#").strip()
    entries.pop(idx)

    if not entries:
        path.unlink()
        return f"Deleted the only entry from {d} — journal file removed."

    atomic.write(path, _rebuild_file(file_header, entries), encoding="utf-8")
    return f"Deleted entry {entry_number} from {d}: {deleted_heading}"


def edit_journal_entry(entry_number: int, new_text: str, date_str: str = None) -> str:
    """
    Replace the body of a specific entry with new text.
    Preserves the original timestamp and heading.
    """
    result = _resolve_entry(entry_number, date_str)
    if isinstance(result, str):
        return result
    path, file_header, entries, idx, d = result

    heading = entries[idx][0]
    entries[idx] = (heading, f"\n{new_text.strip()}\n\n")
    atomic.write(path, _rebuild_file(file_header, entries), encoding="utf-8")
    return f"Updated entry {entry_number} from {d}: {heading.lstrip('#').strip()}"


def append_to_entry(entry_number: int, additional_text: str, date_str: str = None) -> str:
    """
    Add more text to an existing entry without creating a new timestamp.
    """
    result = _resolve_entry(entry_number, date_str)
    if isinstance(result, str):
        return result
    path, file_header, entries, idx, d = result

    heading, old_body = entries[idx]
    new_body = f"{old_body.rstrip()}\n{additional_text.strip()}\n\n"
    entries[idx] = (heading, new_body)
    atomic.write(path, _rebuild_file(file_header, entries), encoding="utf-8")
    return f"Appended to entry {entry_number} from {d}."


def rename_entry_title(entry_number: int, new_title: str, date_str: str = None) -> str:
    """Rename the title of a specific journal entry (keeps the original time)."""
    result = _resolve_entry(entry_number, date_str)
    if isinstance(result, str):
        return result
    path, file_header, entries, idx, d = result

    heading, body = entries[idx]
    time_m    = re.match(r"^(## \d{2}:\d{2})", heading)
    time_part = time_m.group(1) if time_m else heading.split("—")[0].rstrip()
    new_heading = f"{time_part} — {new_title.strip()}"
    entries[idx] = (new_heading, body)
    atomic.write(path, _rebuild_file(file_header, entries), encoding="utf-8")
    return f"Renamed entry {entry_number} from {d} to: {new_title.strip()}"


# ── Browse ────────────────────────────────────────────────────────────────────

def list_journal_entries(n: int = 7) -> str:
    """List the last N days that have journal entries, with counts and word totals."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries yet. Say 'take a note: [text]' to start."

    files = [f for f in sorted(_JOURNAL_DIR.glob("*.md"), reverse=True)
             if not f.stem.startswith("export") and f.stem != "pins"]
    if not files:
        return "No journal entries yet."

    lines = ["Recent journal entries:\n"]
    for path in files[:n]:
        try:
            d_obj   = date.fromisoformat(path.stem)
            label   = d_obj.strftime("%b %d, %Y  (%A)")
            content = path.read_text(encoding="utf-8")
            count   = len(re.findall(r"^## ", content, re.MULTILINE))
            words   = _count_words(content)
            e_word  = "entry" if count == 1 else "entries"
            lines.append(f"  {label} — {count} {e_word}, ~{words} words")
        except Exception:
            lines.append(f"  {path.stem}")

    total_files = len(files)
    if total_files > n:
        lines.append(f"\n({total_files} total days with entries)")

    return "\n".join(lines)


def most_recent_entry() -> str:
    """Return the single most recent journal entry across all days."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries yet."

    files = [f for f in sorted(_JOURNAL_DIR.glob("*.md"), reverse=True)
             if not f.stem.startswith("export")]
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
            _, entries = _split_entries(content)
            if entries:
                heading, body = entries[-1]  # last = most recently appended
                return (
                    f"Most recent entry ({_date_label(path.stem)}):\n\n"
                    f"{heading}\n{body.strip()}"
                )
        except Exception:
            continue
    return "No journal entries found."


def random_memory() -> str:
    """Return a random past journal entry for reflection."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries yet."

    files = [f for f in list(_JOURNAL_DIR.glob("*.md"))
             if not f.stem.startswith("export")]
    if not files:
        return "No journal entries yet."

    for _ in range(5):  # up to 5 attempts if file has no entries
        path = random.choice(files)
        try:
            content = path.read_text(encoding="utf-8")
            _, entries = _split_entries(content)
            if entries:
                heading, body = random.choice(entries)
                snippet = body.strip()[:300] + ("..." if len(body.strip()) > 300 else "")
                return (
                    f"Random memory from {_date_label(path.stem)}:\n\n"
                    f"{heading}\n{snippet}"
                )
        except Exception:
            continue

    return "Could not load a random memory — try again."


def read_journal_range(start_date: str, end_date: str = None) -> str:
    """
    Read journal entries across a range of dates (max 14 days).
    start_date / end_date accept the same formats as read_journal.
    """
    start_d = _parse_date(start_date)
    if start_d is None:
        return f"Invalid start date '{start_date}'."

    end_d = _parse_date(end_date) if end_date else _today()
    if end_d is None:
        return f"Invalid end date '{end_date}'."

    start_obj = date.fromisoformat(start_d)
    end_obj   = date.fromisoformat(end_d)
    if start_obj > end_obj:
        start_obj, end_obj = end_obj, start_obj

    span = (end_obj - start_obj).days
    if span > 14:
        return f"Date range is {span} days — limit to 14 days max to keep responses manageable."

    sections = []
    current  = start_obj
    while current <= end_obj:
        d    = current.isoformat()
        path = _journal_path(d)
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    sections.append(f"=== {current.strftime('%A, %b %d')} ===\n{content}")
            except Exception:
                pass
        current += timedelta(days=1)

    if not sections:
        return f"No journal entries between {start_d} and {end_d}."

    return f"Journal from {start_d} to {end_d}:\n\n" + "\n\n".join(sections)


def weekly_summary(weeks_ago: int = 0) -> str:
    """
    Return all journal entries from the past 7 days (or N weeks back).
    The brain model should summarise this for Mo.
    weeks_ago=0 = this past week, weeks_ago=1 = the week before, etc.
    """
    end_date   = date.today() - timedelta(days=7 * weeks_ago)
    start_date = end_date - timedelta(days=6)

    sections = []
    current  = start_date
    while current <= end_date:
        d    = current.isoformat()
        path = _journal_path(d)
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    sections.append(f"=== {current.strftime('%A, %b %d')} ===\n{content}")
            except Exception:
                pass
        current += timedelta(days=1)

    if not sections:
        label = "this past week" if weeks_ago == 0 else f"{weeks_ago} week(s) ago"
        return f"No journal entries for {label} ({start_date} to {end_date})."

    label = "This past week" if weeks_ago == 0 else f"{weeks_ago} week(s) ago"
    return (
        f"{label}'s journal ({start_date} to {end_date}):\n\n"
        + "\n\n".join(sections)
    )


# ── Search ────────────────────────────────────────────────────────────────────

def search_journal(query: str) -> str:
    """Search all journal entries for a keyword, phrase, mood, or #tag."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries to search."

    query_lower = query.lower().strip()
    pattern = re.compile(r"\b" + re.escape(query_lower) + r"\b", re.IGNORECASE)
    matches = []

    for path in sorted(_JOURNAL_DIR.glob("*.md"), reverse=True):
        if path.stem.startswith("export"):
            continue
        try:
            d_label = _date_label(path.stem)
            file_lines = path.read_text(encoding="utf-8").splitlines()
            current_heading = ""
            for line in file_lines:
                if re.match(r"^## ", line):
                    current_heading = line.lstrip("#").strip()
                elif pattern.search(line) and line.strip():
                    snippet = line.strip()
                    if len(snippet) > 100:
                        idx   = snippet.lower().find(query_lower)
                        start = max(0, idx - 30)
                        snippet = ("..." if start > 0 else "") + snippet[start:start + 100] + "..."
                    matches.append(f"{d_label}  {current_heading} — {snippet}")
                    if len(matches) >= 15:
                        break
        except Exception:
            continue
        if len(matches) >= 15:
            break

    if not matches:
        return f"No journal entries found containing '{query}'."
    return f"Journal search for '{query}':\n\n" + "\n".join(matches)


def search_by_tag(tag: str) -> str:
    """Search all journals for a specific tag (with or without the # prefix)."""
    clean_tag = tag.lstrip("#").strip().lower()
    target    = f"#{clean_tag}"

    if not _JOURNAL_DIR.exists():
        return "No journal entries to search."

    matches = []
    for path in sorted(_JOURNAL_DIR.glob("*.md"), reverse=True):
        if path.stem.startswith("export"):
            continue
        try:
            d_label    = _date_label(path.stem)
            file_lines = path.read_text(encoding="utf-8").splitlines()
            cur_heading = ""
            for line in file_lines:
                if re.match(r"^## ", line):
                    cur_heading = line.lstrip("#").strip()
                elif target in line.lower() and line.strip():
                    matches.append(f"{d_label}  {cur_heading} — {line.strip()[:100]}")
                    if len(matches) >= 15:
                        break
        except Exception:
            continue
        if len(matches) >= 15:
            break

    if not matches:
        return f"No journal entries found with tag '{tag}'."
    return f"Journal entries tagged {target}:\n\n" + "\n".join(matches)


# ── Tags & Mood ───────────────────────────────────────────────────────────────

def list_tags() -> str:
    """List all unique #tags used across all journal entries, sorted by frequency."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries yet."

    tag_counts: dict[str, int] = {}
    for path in _JOURNAL_DIR.glob("*.md"):
        if path.stem.startswith("export"):
            continue
        try:
            content = path.read_text(encoding="utf-8")
            for m in _TAG_RE.finditer(content):
                tag = m.group(1).lower()
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        except Exception:
            continue

    if not tag_counts:
        return "No tags found. Add tags when saving: say 'take a note about study... tags: study, uni'."

    sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
    lines = [f"Journal tags ({len(sorted_tags)} unique):\n"]
    for tag, count in sorted_tags:
        times = "time" if count == 1 else "times"
        lines.append(f"  #{tag} — {count} {times}")

    return "\n".join(lines)


def mood_summary(days: int = 7) -> str:
    """Show all mood entries from the past N days."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries yet."

    files = [f for f in sorted(_JOURNAL_DIR.glob("*.md"), reverse=True)
             if not f.stem.startswith("export")][:days]
    if not files:
        return "No journal entries yet."

    mood_entries = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
            for m in _MOOD_RE.finditer(content):
                d_label = _date_label(path.stem)
                mood_entries.append(f"  {d_label}: {m.group(1).strip()}")
        except Exception:
            continue

    if not mood_entries:
        return (
            f"No mood entries in the past {days} days. "
            "Add mood when saving: say 'take a note... mood: happy'."
        )

    # Tally unique moods
    all_moods = [e.split(":")[-1].strip() for e in mood_entries]
    counts: dict[str, int] = {}
    for mood in all_moods:
        counts[mood] = counts.get(mood, 0) + 1

    lines = [f"Mood log (past {days} days):\n"]
    lines += mood_entries
    if len(set(all_moods)) > 1:
        tally = ", ".join(f"{m} x{c}" for m, c in sorted(counts.items(), key=lambda x: -x[1]))
        lines.append(f"\nTally: {tally}")

    return "\n".join(lines)


# ── Pins ──────────────────────────────────────────────────────────────────────

def pin_entry(entry_number: int, date_str: str = None) -> str:
    """
    Pin an important journal entry for quick access. Calling again unpins it.
    """
    result = _resolve_entry(entry_number, date_str)
    if isinstance(result, str):
        return result
    path, file_header, entries, idx, d = result

    heading, body = entries[idx]
    snippet = body.strip()[:80]

    pins = _load_pins()
    for i, pin in enumerate(pins):
        if pin["date"] == d and pin["entry_number"] == int(entry_number):
            pins.pop(i)
            _save_pins(pins)
            return f"Unpinned entry {entry_number} from {d}."

    pins.insert(0, {
        "date":         d,
        "entry_number": int(entry_number),
        "heading":      heading.lstrip("#").strip(),
        "snippet":      snippet,
    })
    _save_pins(pins)
    return f"Pinned entry {entry_number} from {d}: {heading.lstrip('#').strip()}"


def list_pinned_entries() -> str:
    """List all pinned journal entries."""
    pins = _load_pins()
    if not pins:
        return "No pinned entries. Say 'pin entry 2' to mark an important note."

    lines = [f"Pinned entries ({len(pins)}):\n"]
    for pin in pins:
        d_label  = _date_label(pin.get("date", "?"))
        heading  = pin.get("heading", "")
        snippet  = pin.get("snippet", "")[:60]
        n        = pin.get("entry_number", "?")
        lines.append(f"  {d_label} #{n} — {heading}")
        if snippet:
            lines.append(f"    {snippet}...")

    return "\n".join(lines)


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_journal_stats() -> str:
    """Return overall journal statistics: days, entries, words, date range, most active day."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries yet."

    files = [f for f in sorted(_JOURNAL_DIR.glob("*.md"))
             if not f.stem.startswith("export")]
    if not files:
        return "No journal entries yet."

    total_entries = 0
    total_words   = 0
    max_entries   = 0
    max_day       = ""

    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
            count   = len(re.findall(r"^## ", content, re.MULTILINE))
            words   = _count_words(content)
            total_entries += count
            total_words   += words
            if count > max_entries:
                max_entries = count
                max_day     = path.stem
        except Exception:
            continue

    days = len(files)
    avg  = round(total_entries / days, 1) if days else 0

    first_label = _date_label(files[0].stem)
    last_label  = _date_label(files[-1].stem)

    lines = [
        "Journal stats:",
        f"  {days} day(s) with entries",
        f"  {total_entries} total entries",
        f"  ~{total_words:,} words written",
        f"  Avg {avg} entries/day",
        f"  First entry: {first_label}",
        f"  Latest:      {last_label}",
    ]
    if max_day:
        lines.append(f"  Most active day: {_date_label(max_day)} ({max_entries} entries)")

    return "\n".join(lines)


def journal_streak() -> str:
    """Count consecutive days with journal entries, ending today or yesterday."""
    if not _JOURNAL_DIR.exists():
        return "No journal entries yet."

    # Count from today backwards
    streak   = 0
    current  = date.today()
    while _journal_path(current.isoformat()).exists():
        streak  += 1
        current -= timedelta(days=1)

    if streak > 0:
        suffix = "day" if streak == 1 else "days"
        return f"Current streak: {streak} {suffix} in a row. Keep it going!"

    # No entry today — check from yesterday
    streak   = 0
    current  = date.today() - timedelta(days=1)
    while _journal_path(current.isoformat()).exists():
        streak  += 1
        current -= timedelta(days=1)

    if streak > 0:
        suffix = "day" if streak == 1 else "days"
        return f"Streak ended yesterday — {streak} {suffix}. Journal today to restart!"

    return "No active streak — start journaling today to begin one."


# ── Export ────────────────────────────────────────────────────────────────────

def export_journal(start_date: str = None, end_date: str = None) -> str:
    """
    Export journal entries to a single combined Markdown file.
    Omit start_date to export everything.
    """
    start_d = _parse_date(start_date) if start_date else None
    end_d   = _parse_date(end_date)   if end_date   else _today()

    if start_d and end_d and start_d > end_d:
        start_d, end_d = end_d, start_d

    files = sorted(
        [f for f in _JOURNAL_DIR.glob("*.md") if not f.stem.startswith("export")]
    )

    selected = []
    for path in files:
        stem = path.stem
        if start_d and stem < start_d:
            continue
        if stem > end_d:
            continue
        selected.append(path)

    if not selected:
        label = f"{start_d or 'beginning'} to {end_d}"
        return f"No journal entries found for {label}."

    combined  = f"# Journal Export\n"
    combined += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    if start_d:
        combined += f"Range: {start_d} to {end_d}\n"
    combined += "\n---\n\n"

    for path in selected:
        try:
            combined += path.read_text(encoding="utf-8").strip() + "\n\n---\n\n"
        except Exception:
            continue

    range_label = f"{(start_d or selected[0].stem)}_{end_d}"
    export_path = _JOURNAL_DIR / f"export_{range_label}.md"
    atomic.write(export_path, combined, encoding="utf-8")

    try:
        os.startfile(str(export_path))
    except Exception:
        pass

    return f"Exported {len(selected)} day(s) to {export_path.name} and opened."


def copy_journal_to_clipboard(date_str: str = None) -> str:
    """Copy a day's entire journal to the clipboard."""
    d = _parse_date(date_str) if date_str else _today()
    if d is None:
        return f"Invalid date '{date_str}'."

    path = _journal_path(d)
    if not path.exists():
        return f"No journal for {d}."

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Journal error: {e}]"

    copied = False
    try:
        import pyperclip
        pyperclip.copy(content)
        copied = True
    except Exception:
        pass

    if not copied:
        try:
            import subprocess
            proc = subprocess.run(
                ["clip"],
                input=content.encode("utf-16le"),
                capture_output=True,
            )
            copied = proc.returncode == 0
        except Exception:
            pass

    if not copied:
        # Last resort: write to a temp file and tell Mo where it is
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f"journal_{d}.md"
        atomic.write(tmp, content, encoding="utf-8")
        return f"Clipboard unavailable — journal saved to {tmp} instead."

    return f"Copied journal for {_date_label(d)} to clipboard."
