"""
Analytics tool — insights from expenses, journal, and conversation history.
"""

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

_EXPENSE_FILE = Path("data/expenses.csv")
_JOURNAL_DIR  = Path("data/journal")
_CONV_DIR     = Path("data/conversations")


# ── Date range helpers ────────────────────────────────────────────────────────

def _week_range():
    today = datetime.now().date()
    return today - timedelta(days=today.weekday()), today

def _month_range():
    today = datetime.now().date()
    return today.replace(day=1), today

def _year_range():
    today = datetime.now().date()
    return today.replace(month=1, day=1), today

def _get_range(period: str):
    p = period.lower()
    if p == "week":  return _week_range()
    if p == "year":  return _year_range()
    return _month_range()

def _prev_range(period: str):
    start, end = _get_range(period)
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)


# ── Journal parsing ───────────────────────────────────────────────────────────

def _parse_journal_files(start, end) -> list[dict]:
    """
    Parse journal .md files in [start, end].
    Each file = one day. Extracts moods + tags from *italic* metadata lines.
    """
    if not _JOURNAL_DIR.exists():
        return []
    entries = []
    for f in _JOURNAL_DIR.glob("*.md"):
        stem = f.stem[:10]
        try:
            date = datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (start <= date <= end):
            continue
        content = f.read_text(encoding="utf-8")
        moods, tags = [], []
        for line in content.splitlines():
            s = line.strip()
            # Metadata lines are italic: *Mood: X | #tag* or *#tag1 #tag2*
            if s.startswith("*") and s.endswith("*"):
                mood_m = re.search(r"Mood:\s*([^|*\n#]+)", s, re.IGNORECASE)
                if mood_m:
                    moods.append(mood_m.group(1).strip().lower())
                tags.extend(re.findall(r"#(\w+)", s))
        word_count = len(content.split())
        entries.append({
            "date":   date,
            "moods":  moods,
            "mood":   moods[0] if moods else "",
            "tags":   tags,
            "words":  word_count,
            "dow":    date.weekday(),
        })
    return entries


def _all_journal_dates() -> list:
    """Return all dated journal file dates, sorted ascending."""
    if not _JOURNAL_DIR.exists():
        return []
    dates = []
    for f in _JOURNAL_DIR.glob("*.md"):
        try:
            dates.append(datetime.strptime(f.stem[:10], "%Y-%m-%d").date())
        except ValueError:
            continue
    return sorted(dates)


def _compute_streaks(all_dates: list) -> tuple[int, int]:
    """Returns (current_streak, longest_streak)."""
    if not all_dates:
        return 0, 0
    today = datetime.now().date()
    dates = sorted(set(all_dates), reverse=True)
    # Current streak
    current = 0
    prev = today
    for d in dates:
        if (prev - d).days <= 1:
            current += 1
            prev = d
        else:
            break
    # Longest streak
    longest = 1
    run = 1
    for i in range(1, len(dates)):
        if (dates[i - 1] - dates[i]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1
    return current, longest


# ── Spending ──────────────────────────────────────────────────────────────────

def spending_insights(period: str = "month") -> str:
    if not _EXPENSE_FILE.exists():
        return "No expense data found. Log some expenses first with 'log expense'."

    start, end = _get_range(period)
    prev_start, prev_end = _prev_range(period)
    rows, prev_rows = [], []

    for line in _EXPENSE_FILE.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        try:
            date_str, amount_str, *rest = parts
            # Date may include time: "2026-06-16 18:13" — take first 10 chars
            date = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
            amount   = float(amount_str.strip())
            currency = rest[0].strip() if rest else "EGP"
            category = rest[1].strip() if len(rest) > 1 else "other"
            if start <= date <= end:
                rows.append((date, amount, currency, category))
            elif prev_start <= date <= prev_end:
                prev_rows.append((date, amount, currency, category))
        except Exception:
            continue

    if not rows:
        return f"No expenses recorded for this {period}."

    total      = sum(r[1] for r in rows)
    prev_total = sum(r[1] for r in prev_rows)
    days       = max((end - start).days, 1)
    currencies = Counter(r[2] for r in rows)
    main_curr  = currencies.most_common(1)[0][0]

    cat_totals: dict[str, float] = {}
    for _, amt, _, cat in rows:
        cat_totals[cat] = cat_totals.get(cat, 0) + amt
    top = sorted(cat_totals.items(), key=lambda x: -x[1])[:3]

    lines = [f"Spending — this {period}:"]
    if prev_total > 0:
        change = ((total - prev_total) / prev_total) * 100
        sign   = "+" if change >= 0 else ""
        lines.append(f"  Total: {total:,.0f} {main_curr}  ({sign}{change:.0f}% vs last {period})")
    else:
        lines.append(f"  Total: {total:,.0f} {main_curr}")
    lines.append(f"  Daily avg: {total / days:,.0f} {main_curr}")
    if top:
        lines.append("  Top categories:")
        for cat, amt in top:
            lines.append(f"    {cat}: {amt:,.0f} {main_curr}  ({amt/total*100:.0f}%)")
    return "\n".join(lines)


# ── Journal ───────────────────────────────────────────────────────────────────

def journal_insights(period: str = "month") -> str:
    start, end = _get_range(period)
    entries = _parse_journal_files(start, end)
    if not entries:
        return f"No journal entries for this {period}."

    days_journaled = len(entries)
    total_words    = sum(e["words"] for e in entries)
    all_moods      = [m for e in entries for m in e["moods"]]
    mood_counts    = Counter(all_moods)
    all_tags       = [t for e in entries for t in e["tags"]]
    top_tags       = Counter(all_tags).most_common(5)
    dow_counts     = Counter(e["dow"] for e in entries)
    dow_names      = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    busiest_dow    = dow_names[dow_counts.most_common(1)[0][0]] if dow_counts else "?"

    all_dates           = _all_journal_dates()
    current_streak, longest_streak = _compute_streaks(all_dates)

    lines = [f"Journal — this {period}:"]
    lines.append(f"  Days journaled: {days_journaled}")
    lines.append(f"  Words written:  {total_words:,}")
    lines.append(f"  Current streak: {current_streak} day(s)  (longest: {longest_streak})")
    lines.append(f"  Most active day: {busiest_dow}")
    if mood_counts:
        top_mood = mood_counts.most_common(1)[0][0]
        mood_str = ", ".join(f"{m} ({c}x)" for m, c in mood_counts.most_common(4))
        lines.append(f"  Moods: {mood_str}")
    if top_tags:
        lines.append(f"  Top tags: {', '.join(t for t, _ in top_tags)}")
    return "\n".join(lines)


# ── Productivity ──────────────────────────────────────────────────────────────

def productivity_insights(period: str = "week") -> str:
    start, end = _get_range(period)
    total_turns = 0
    tool_counts: Counter = Counter()
    user_turns  = 0

    if _CONV_DIR.exists():
        for fpath in _CONV_DIR.glob("*.jsonl"):
            try:
                date = datetime.strptime(fpath.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if not (start <= date <= end):
                continue
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    total_turns += 1
                    if entry.get("role") == "user":
                        user_turns += 1
                    for t in entry.get("tools_used", []):
                        tool_counts[t] += 1
                except Exception:
                    pass

    # Count focus/pomodoro sessions from tool usage
    focus_sessions    = tool_counts.get("enable_focus_mode", 0)
    pomodoro_sessions = tool_counts.get("start_pomodoro", 0)

    top = tool_counts.most_common(7)
    # Filter out meta-tools that aren't interesting to report
    _skip = {"enable_focus_mode", "disable_focus_mode", "start_pomodoro", "stop_pomodoro"}
    top_filtered = [(t, c) for t, c in top if t not in _skip][:5]

    lines = [f"Productivity — this {period}:"]
    lines.append(f"  El Fager interactions: {user_turns}")
    if focus_sessions:
        lines.append(f"  Focus sessions: {focus_sessions}")
    if pomodoro_sessions:
        lines.append(f"  Pomodoro sessions: {pomodoro_sessions}")
    if top_filtered:
        lines.append("  Most-used tools:")
        for t, c in top_filtered:
            lines.append(f"    {t}: {c}x")
    return "\n".join(lines)


# ── Weekly report ─────────────────────────────────────────────────────────────

def weekly_report() -> str:
    spending     = spending_insights("week")
    journal      = journal_insights("week")
    productivity = productivity_insights("week")

    parts = []
    for section in [spending, journal, productivity]:
        if not (section.startswith("No ") or section.startswith("Not enough")):
            parts.append(section)

    if not parts:
        return "Not enough data for a weekly report yet. Start logging expenses and journal entries."
    return "\n\n".join(parts)


# ── Mood trend ────────────────────────────────────────────────────────────────

def mood_trend(days: int = 14) -> str:
    end   = datetime.now().date()
    start = end - timedelta(days=days - 1)
    entries = _parse_journal_files(start, end)

    day_moods = {}
    for e in entries:
        if e["moods"]:
            day_moods[e["date"]] = e["moods"]

    if not day_moods:
        return f"No mood data in the last {days} days. Try logging your mood when journaling."

    all_moods   = [m for moods in day_moods.values() for m in moods]
    mood_counts = Counter(all_moods)
    total       = sum(mood_counts.values())
    top_mood    = mood_counts.most_common(1)[0][0]

    lines = [f"Mood trend — last {days} days:"]
    lines.append(f"  Most common: {top_mood}")
    lines.append("  Distribution:")
    for mood, count in mood_counts.most_common():
        lines.append(f"    {mood}: {count}x  ({count/total*100:.0f}%)")
    lines.append("  Day-by-day:")
    for date in sorted(day_moods):
        moods_str = ", ".join(day_moods[date])
        lines.append(f"    {date.strftime('%a %b %d')}: {moods_str}")
    return "\n".join(lines)


# ── Top tools ─────────────────────────────────────────────────────────────────

def top_tools(n: int = 10) -> str:
    if not _CONV_DIR.exists():
        return "No conversation history yet."
    tool_counts: Counter = Counter()
    for fpath in _CONV_DIR.glob("*.jsonl"):
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                for t in entry.get("tools_used", []):
                    tool_counts[t] += 1
            except Exception:
                pass
    if not tool_counts:
        return "No tool usage recorded yet."
    lines = [f"Top {n} tools (all time):"]
    for t, c in tool_counts.most_common(n):
        lines.append(f"  {c:>4}x  {t}")
    return "\n".join(lines)


# ── Daily activity ────────────────────────────────────────────────────────────

def daily_activity(date: str = "") -> str:
    """What happened on a specific day — expenses, journal, conversations."""
    if date:
        try:
            day = datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return f"Invalid date format: '{date}'. Use YYYY-MM-DD."
    else:
        day = datetime.now().date()

    lines = [f"Activity — {day.strftime('%A, %B %d %Y')}:"]

    # Expenses that day
    if _EXPENSE_FILE.exists():
        day_expenses = []
        for line in _EXPENSE_FILE.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            try:
                d = datetime.strptime(parts[0].strip()[:10], "%Y-%m-%d").date()
                if d == day:
                    amt      = float(parts[1].strip())
                    currency = parts[2].strip() if len(parts) > 2 else "EGP"
                    category = parts[3].strip() if len(parts) > 3 else "other"
                    desc     = parts[4].strip() if len(parts) > 4 else ""
                    day_expenses.append((amt, currency, category, desc))
            except Exception:
                continue
        if day_expenses:
            total = sum(e[0] for e in day_expenses)
            curr  = day_expenses[0][1]
            lines.append(f"  Spent: {total:,.0f} {curr}  ({len(day_expenses)} transaction(s))")
            for amt, cur, cat, desc in day_expenses:
                desc_str = f" — {desc}" if desc else ""
                lines.append(f"    {cat}: {amt:,.0f}{desc_str}")
        else:
            lines.append("  Expenses: none logged")

    # Journal
    jfile = _JOURNAL_DIR / f"{day}.md"
    if jfile.exists():
        content = jfile.read_text(encoding="utf-8")
        word_count = len(content.split())
        moods = []
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("*") and s.endswith("*"):
                mood_m = re.search(r"Mood:\s*([^|*\n#]+)", s, re.IGNORECASE)
                if mood_m:
                    moods.append(mood_m.group(1).strip().lower())
        entry_count = len(re.findall(r"^## ", content, re.MULTILINE))
        mood_str    = f"  mood: {', '.join(moods)}" if moods else ""
        lines.append(f"  Journal: {entry_count} entry/entries, {word_count} words{mood_str}")
    else:
        lines.append("  Journal: no entry that day")

    # Conversations
    conv_file = _CONV_DIR / f"{day}.jsonl"
    if conv_file.exists():
        turns, tools_used = 0, Counter()
        for line in conv_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("role") == "user":
                    turns += 1
                for t in entry.get("tools_used", []):
                    tools_used[t] += 1
            except Exception:
                pass
        top = tools_used.most_common(3)
        top_str = f"  tools: {', '.join(t for t, _ in top)}" if top else ""
        lines.append(f"  El Fager: {turns} conversation(s){top_str}")
    else:
        lines.append("  El Fager: not used that day")

    return "\n".join(lines)


# ── Streak stats ──────────────────────────────────────────────────────────────

def streak_stats() -> str:
    """All-time journaling streak stats."""
    all_dates = _all_journal_dates()
    if not all_dates:
        return "No journal entries found. Start journaling to track your streak!"

    current, longest = _compute_streaks(all_dates)
    total_days  = len(set(all_dates))
    first_entry = min(all_dates)
    days_since  = (datetime.now().date() - first_entry).days + 1
    consistency = total_days / max(days_since, 1) * 100

    lines = ["Journal streak stats:"]
    lines.append(f"  Current streak:  {current} day(s)")
    lines.append(f"  Longest streak:  {longest} day(s)")
    lines.append(f"  Total days:      {total_days} entries")
    lines.append(f"  Since:           {first_entry.strftime('%b %d, %Y')}")
    lines.append(f"  Consistency:     {consistency:.0f}% of days")
    return "\n".join(lines)


# ── Phase 8 — Finance analytics ───────────────────────────────────────────────

_INCOME_FILE = Path("data/income.csv")


def _parse_income(start, end) -> list[tuple]:
    """Returns list of (date, amount, currency, category, source) tuples."""
    if not _INCOME_FILE.exists():
        return []
    rows = []
    for line in _INCOME_FILE.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        try:
            date     = datetime.strptime(parts[0].strip()[:10], "%Y-%m-%d").date()
            amount   = float(parts[1].strip())
            currency = parts[2].strip() if len(parts) > 2 else "EGP"
            category = parts[3].strip() if len(parts) > 3 else "other"
            source   = parts[4].strip() if len(parts) > 4 else ""
            if start <= date <= end:
                rows.append((date, amount, currency, category, source))
        except Exception:
            continue
    return rows


def _parse_expenses(start, end) -> list[tuple]:
    """Returns list of (date, amount, currency, category) tuples."""
    if not _EXPENSE_FILE.exists():
        return []
    rows = []
    for line in _EXPENSE_FILE.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            date     = datetime.strptime(parts[0].strip()[:10], "%Y-%m-%d").date()
            amount   = float(parts[1].strip())
            currency = parts[2].strip() if len(parts) > 2 else "EGP"
            category = parts[3].strip() if len(parts) > 3 else "other"
            if start <= date <= end:
                rows.append((date, amount, currency, category))
        except Exception:
            continue
    return rows


def cash_flow_summary(period: str = "month") -> str:
    start, end = _get_range(period)
    income_rows  = _parse_income(start, end)
    expense_rows = _parse_expenses(start, end)

    total_income  = sum(r[1] for r in income_rows)
    total_expense = sum(r[1] for r in expense_rows)
    net = total_income - total_expense

    currency = (income_rows or expense_rows or [("", 0, "EGP")])[0][2]

    lines = [f"Cash flow — this {period}:"]
    lines.append(f"  Income:   {total_income:>12,.0f} {currency}")
    lines.append(f"  Expenses: {total_expense:>12,.0f} {currency}")
    lines.append(f"  {'-' * 28}")
    sign = "+" if net >= 0 else ""
    label = "Surplus" if net >= 0 else "Deficit"
    lines.append(f"  {label}:  {sign}{net:>12,.0f} {currency}")
    if total_income > 0:
        savings_rate = (net / total_income) * 100
        lines.append(f"  Savings rate: {savings_rate:.0f}%")
    return "\n".join(lines)


def revenue_insights(period: str = "month") -> str:
    start, end  = _get_range(period)
    income_rows = _parse_income(start, end)

    if not income_rows:
        return f"No income recorded this {period}."

    total    = sum(r[1] for r in income_rows)
    currency = income_rows[0][2]
    days     = max((end - start).days, 1)

    cat_totals: dict[str, float] = {}
    src_totals: dict[str, float] = {}
    for _, amt, _, cat, src in income_rows:
        cat_totals[cat] = cat_totals.get(cat, 0) + amt
        if src:
            src_totals[src] = src_totals.get(src, 0) + amt

    lines = [f"Revenue — this {period}:"]
    lines.append(f"  Total:     {total:,.0f} {currency}")
    lines.append(f"  Daily avg: {total / days:,.0f} {currency}")
    lines.append(f"  Entries:   {len(income_rows)}")
    lines.append("  By category:")
    for cat, amt in sorted(cat_totals.items(), key=lambda x: -x[1]):
        lines.append(f"    {cat:<15} {amt:>10,.0f}  ({amt/total*100:.0f}%)")
    if src_totals:
        top_src = sorted(src_totals.items(), key=lambda x: -x[1])[:5]
        lines.append("  Top sources:")
        for src, amt in top_src:
            lines.append(f"    {src:<20} {amt:>10,.0f}")
    return "\n".join(lines)


def profit_loss_report(period: str = "month") -> str:
    revenue  = revenue_insights(period)
    cashflow = cash_flow_summary(period)
    start, end = _get_range(period)
    expense_rows = _parse_expenses(start, end)

    cat_totals: dict[str, float] = {}
    for _, amt, _, cat in expense_rows:
        cat_totals[cat] = cat_totals.get(cat, 0) + amt
    currency = (expense_rows or [("", 0, "EGP")])[0][2] if expense_rows else "EGP"

    lines = [f"P&L Report — this {period}:", ""]
    lines.append(revenue)
    lines.append("")
    if cat_totals:
        lines.append("Expense breakdown:")
        for cat, amt in sorted(cat_totals.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat:<15} {amt:>10,.0f} {currency}")
        lines.append("")
    lines.append(cashflow)
    return "\n".join(lines)
