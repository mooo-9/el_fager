"""
ProactiveEngine — background thread that watches conditions and acts without Mo asking.

Checks every 60 seconds (during waking hours only).
Each check has a cooldown stored in data/proactive_state.json to avoid spam.

Checks implemented:
  • Battery low / critical
  • Prayer time in ~10 minutes
  • Calendar event starting soon
  • Deadline from memory is today or tomorrow
  • Morning weather alert (rain / sandstorm)
  • Evening journal nudge (no entry today)
  • Evening expense nudge (nothing logged today)
  • Weekly review prompt (Friday / Saturday evening)
"""

import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

_STATE_FILE = Path("data/proactive_state.json")


def _fmt12(hhmm: str) -> str:
    """Convert 'HH:MM' (24h) to '12:30 PM' format."""
    try:
        h, m = map(int, hhmm.split(":"))
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"
    except Exception:
        return hhmm


class ProactiveEngine:
    CHECK_INTERVAL = 60  # seconds between check cycles

    def __init__(self, speak_fn: Callable[[str], None], memory=None, brain_fn=None):
        self._speak_fn  = speak_fn
        self._memory    = memory
        self._brain_fn  = brain_fn   # brain.chat callable for autonomous task execution
        self._running   = False
        self._thread: threading.Thread | None = None
        self._state: dict = self._load_state()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="ProactiveEngine"
        )
        self._thread.start()
        print("[Proactive] Engine started.")

    def stop(self) -> None:
        self._running = False

    # ── State persistence ──────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if _STATE_FILE.exists():
            try:
                return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_state(self) -> None:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _cooldown(self, key: str, hours: float) -> bool:
        """
        Returns True  → still in cooldown, skip this check.
        Returns False → cooldown expired; stamps now and saves.
        """
        if key in self._state:
            try:
                last    = datetime.fromisoformat(self._state[key])
                elapsed = (datetime.now() - last).total_seconds() / 3600
                if elapsed < hours:
                    return True
            except Exception:
                pass
        self._state[key] = datetime.now().isoformat()
        self._save_state()
        return False

    def _reset_cooldown(self, key: str) -> None:
        """Remove a cooldown stamp so the check runs again next cycle."""
        if key in self._state:
            del self._state[key]
            self._save_state()

    # ── Delivery ──────────────────────────────────────────────────────────────

    def _deliver(self, text: str, remote: bool = False) -> None:
        """Show a Windows toast, speak the message, and optionally push to phone."""
        try:
            from winotify import Notification
            Notification(
                app_id="El Fager",
                title="El Fager",
                msg=text[:256],
                duration="long",
            ).show()
        except Exception:
            pass
        if self._speak_fn:
            try:
                self._speak_fn(text)
            except Exception:
                pass
        else:
            print(f"[Proactive] {text}")
        if remote:
            try:
                from core.notifier import get_notifier
                get_notifier().send(text)
            except Exception:
                pass

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(30)          # let El Fager fully initialise first
        while self._running:
            try:
                self._run_checks()
            except Exception as e:
                print(f"[Proactive] Cycle error: {e}")
            time.sleep(self.CHECK_INTERVAL)

    def _run_checks(self) -> None:
        now  = datetime.now()
        hour = now.hour

        if not (6 <= hour <= 23):
            return          # sleep hours — stay quiet

        self._check_battery()               # all hours
        self._check_prayer_times()          # all waking hours
        self._check_upcoming_events()       # all waking hours
        self._check_price_alerts()          # all waking hours
        self._check_autonomous_tasks()      # all waking hours

        if 7 <= hour <= 11:
            self._check_deadlines()
            self._check_weather()
            self._check_overdue_invoices()

        if 19 <= hour <= 22:
            self._check_journal()
            self._check_expenses()
            self._check_budget_exceeded()

        if now.weekday() in (4, 5) and 17 <= hour <= 20:
            self._check_weekly_review()

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_battery(self) -> None:
        """Warn when battery < 25 % and unplugged."""
        try:
            import psutil
            batt = psutil.sensors_battery()
            if batt is None or batt.power_plugged:
                return
            pct = batt.percent
            if pct < 15:
                if not self._cooldown("battery_critical", 0.5):
                    self._deliver(f"Battery critical -- {pct:.0f}%! Plug in now, Mo.", remote=True)
            elif pct < 25:
                if not self._cooldown("battery_low", 0.5):
                    self._deliver(f"Mo, battery at {pct:.0f}%. Plug in soon.")
            else:
                # Not low enough — reset so we warn again if it drops later
                self._reset_cooldown("battery_low")
                self._reset_cooldown("battery_critical")
        except Exception:
            pass

    def _check_prayer_times(self) -> None:
        """Speak a reminder ~10 minutes before each prayer."""
        try:
            import httpx
            resp = httpx.get(
                "https://api.aladhan.com/v1/timingsByCity",
                params={"city": "Cairo", "country": "Egypt", "method": 5},
                timeout=6,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return
            timings = resp.json()["data"]["timings"]
            now    = datetime.now()
            today  = date.today().isoformat()
            for name in ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"):
                t_str = timings.get(name, "").split(" ")[0]
                if not t_str:
                    continue
                try:
                    prayer_dt  = datetime.strptime(
                        f"{now.strftime('%Y-%m-%d')} {t_str}", "%Y-%m-%d %H:%M"
                    )
                    delta_min = (prayer_dt - now).total_seconds() / 60
                    if 7 <= delta_min <= 18:
                        key = f"prayer_{name}_{today}"
                        if not self._cooldown(key, 23):
                            self._deliver(f"Mo, {name} is in {int(delta_min)} minutes — {_fmt12(t_str)}.")
                except ValueError:
                    pass
        except Exception:
            pass

    def _check_upcoming_events(self) -> None:
        """Remind Mo of a calendar event starting in 5–20 minutes."""
        try:
            from tools.calendar_tool import list_calendar_events
            text  = list_calendar_events("today")
            now   = datetime.now()
            today = date.today().isoformat()
            # Match time formats: "10:30 AM", "14:30", "10:30am"
            pattern = r"(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?\s*[—\-–]\s*([^\n\r]+)"
            for m in re.finditer(pattern, text):
                h    = int(m.group(1))
                mins = int(m.group(2))
                ampm = (m.group(3) or "").upper()
                title = m.group(4).strip()
                if ampm == "PM" and h != 12:
                    h += 12
                elif ampm == "AM" and h == 12:
                    h = 0
                event_dt  = now.replace(hour=h, minute=mins, second=0, microsecond=0)
                delta_min = (event_dt - now).total_seconds() / 60
                if 5 <= delta_min <= 20:
                    key = f"event_{h:02d}{mins:02d}_{today}"
                    if not self._cooldown(key, 2):
                        self._deliver(f"Mo, '{title}' starts in {int(delta_min)} minutes.")
        except Exception:
            pass

    def _check_deadlines(self) -> None:
        """Alert when a memorised deadline is today or tomorrow."""
        if self._cooldown("deadlines", 12):
            return
        try:
            if not self._memory:
                return
            deadline_text = self._memory.get_upcoming_deadlines()
            if not deadline_text:
                self._reset_cooldown("deadlines")
                return
            urgent = [
                line.strip()
                for line in deadline_text.splitlines()
                if any(
                    w in line.lower()
                    for w in ("today", "tomorrow", "in 1 day", "overdue")
                )
                and line.strip()
            ]
            if urgent:
                self._deliver("Deadline reminder: " + " | ".join(urgent[:2]))
            else:
                self._reset_cooldown("deadlines")
        except Exception:
            pass

    def _check_weather(self) -> None:
        """Morning alert for rain or sandstorms."""
        if self._cooldown("weather", 20):
            return
        try:
            from tools.weather_tool import get_weather
            text  = get_weather("Cairo")
            lower = text.lower()
            if "sandstorm" in lower or "dust storm" in lower:
                self._deliver("Mo, sandstorm warning in Cairo today. Mask up or stay in.")
                return
            if any(w in lower for w in ("rain", "shower", "drizzle", "thunder")):
                m = re.search(r"(\d+)\s*%", text)
                pct = int(m.group(1)) if m else 80
                if pct >= 50:
                    self._deliver(f"Mo, {pct}% chance of rain in Cairo today — grab an umbrella.")
                    return
            # No alert warranted — reset so we re-check tomorrow
            self._reset_cooldown("weather")
        except Exception:
            pass

    def _check_journal(self) -> None:
        """Evening nudge if Mo hasn't written a journal entry today."""
        if self._cooldown("journal", 20):
            return
        try:
            journal_dir = Path("data/journal")
            if not journal_dir.exists():
                self._reset_cooldown("journal")
                return
            today      = date.today().strftime("%Y-%m-%d")
            all_files  = list(journal_dir.glob("*.md"))
            # Only nudge if Mo has an existing journal habit (>= 3 past entries)
            if len(all_files) < 3:
                self._reset_cooldown("journal")
                return
            today_files = [
                f for f in all_files
                if today in f.name
            ]
            if not today_files:
                self._deliver(
                    "Mo, you haven't journaled today. Jot something down before bed?"
                )
            else:
                self._reset_cooldown("journal")
        except Exception:
            pass

    def _check_expenses(self) -> None:
        """Evening nudge if Mo hasn't logged any expenses today."""
        if self._cooldown("expenses", 20):
            return
        try:
            expenses_file = Path("data/expenses.csv")
            if not expenses_file.exists():
                self._reset_cooldown("expenses")
                return
            today   = date.today().isoformat()
            content = expenses_file.read_text(encoding="utf-8")
            lines   = [l for l in content.splitlines() if l and not l.startswith("#")]
            # Only nudge if Mo has a history of logging
            if len(lines) < 5:
                self._reset_cooldown("expenses")
                return
            today_entries = [l for l in lines if l.startswith(today)]
            if not today_entries:
                self._deliver(
                    "Mo, any expenses today? Log them before you forget — log_expense."
                )
            else:
                self._reset_cooldown("expenses")
        except Exception:
            pass

    def _check_weekly_review(self) -> None:
        """Friday / Saturday evening — prompt for a weekly review."""
        if self._cooldown("weekly_review", 7 * 24):
            return
        self._deliver(
            "Mo, good time for your weekly review. Ask me for a 'weekly report' when ready."
        )

    def _check_price_alerts(self) -> None:
        """Check stock price alerts every cycle — deliver immediately when triggered."""
        try:
            from tools.stocks_tool import check_price_alerts
            messages = check_price_alerts()
            for msg in messages:
                self._deliver(msg, remote=True)
        except Exception:
            pass

    def _check_overdue_invoices(self) -> None:
        """Morning sweep — alert if any sent invoices are past due date."""
        if self._cooldown("overdue_invoices", 24):
            return
        try:
            from tools.invoice_tool import get_overdue_invoices
            overdue = get_overdue_invoices()
            if not overdue:
                self._reset_cooldown("overdue_invoices")
                return
            if len(overdue) == 1:
                inv = overdue[0]
                self._deliver(
                    f"Mo, invoice {inv['id']} for {inv['client']} "
                    f"({float(inv['amount']):,.0f} {inv['currency']}) is overdue — "
                    f"due {inv['due_date']}. Follow up?"
                )
            else:
                total = sum(float(i["amount"]) for i in overdue)
                currency = overdue[0]["currency"]
                self._deliver(
                    f"Mo, you have {len(overdue)} overdue invoices totalling "
                    f"{total:,.0f} {currency}. Ask me to 'list overdue invoices' to review."
                )
        except Exception:
            pass

    def _check_autonomous_tasks(self) -> None:
        """Pick up and execute pending autonomous tasks (max 2 per cycle)."""
        if self._brain_fn is None:
            return
        try:
            from core.autonomous_tasks import AutonomousTaskManager
            mgr = AutonomousTaskManager()
            due = mgr.get_due()
            if not due:
                return
            for task in due[:2]:
                mgr.mark_running(task["id"])
                try:
                    result = self._brain_fn(task["description"])
                    short = (result or "Done.")[:200]
                    mgr.complete(task["id"], short)
                    announcement = f"Background task done: {task['description'][:50]}. {short[:100]}"
                    self._deliver(announcement, remote=True)
                except Exception as e:
                    mgr.fail(task["id"], str(e))
        except Exception as e:
            print(f"[Proactive] autonomous task check error: {e}")

    def _check_budget_exceeded(self) -> None:
        """Evening budget check — alert if any budgets are over limit."""
        if self._cooldown("budget_exceeded", 20):
            return
        try:
            from tools.budget_tool import get_exceeded_budgets
            exceeded = get_exceeded_budgets()
            if not exceeded:
                self._reset_cooldown("budget_exceeded")
                return
            top = exceeded[:2]
            parts = []
            for b in top:
                parts.append(
                    f"{b['category']} at {b['pct']:.0f}% "
                    f"({b['actual']:,.0f}/{b['limit']:,.0f} {b['currency']})"
                )
            self._deliver(
                "Mo, budget alert — " + " | ".join(parts) + ". Want a full budget breakdown?"
            )
        except Exception:
            pass
