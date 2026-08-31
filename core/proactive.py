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
  • OAuth token age warning (Google tokens near the 7-day Testing-mode expiry)
  • Nightly backtest after US market close, alert only on metric regression
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
        self._hud_fn: Callable | None = None  # set by main.py via set_hud_notify()

    def set_hud_notify(self, fn: Callable) -> None:
        """Register a thread-safe callback for pushing proactive banners to the HUD."""
        self._hud_fn = fn

    def _hud_notify(self, scene: int, prefix: str, highlight: str, suffix: str, tag: str) -> None:
        """Push a proactive banner update to the HUD (non-blocking, never raises)."""
        if self._hud_fn:
            try:
                self._hud_fn(scene, prefix, highlight, suffix, tag)
            except Exception:
                pass

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
        self._check_missions()              # all waking hours

        if 7 <= hour <= 11:
            self._check_deadlines()
            self._check_weather()
            self._check_overdue_invoices()
            self._check_rest_day()
            self._check_oauth_tokens()
            self._check_skill_proposals()

        if hour == 23:
            self._check_nightly_backtest()

        if 19 <= hour <= 22:
            self._check_journal()
            self._check_expenses()
            self._check_budget_exceeded()
            self._check_api_budget()

        if now.weekday() in (4, 5) and 17 <= hour <= 20:
            self._check_weekly_review()

        if hour == 13:
            self._check_lunch_logged()

        if hour == 18:
            self._check_daily_nutrition()

        if hour == 20:
            self._check_gym_session()

        if now.weekday() == 0:  # Monday
            self._check_weekly_gym_report()

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
                            self._hud_notify(9, f"{name} prayer in ", f"{int(delta_min)} min", f" — {_fmt12(t_str)}", "PRAYER")
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
                        self._hud_notify(7, f"'{title}' in ", f"{int(delta_min)} min", "", "CALENDAR")
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
                # Show in HUD Stocks scene banner (whole message as highlight)
                self._hud_notify(5, "", msg, "", "MARKET")
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
            from core.agents.supervisor import assign
            for task in due[:2]:
                mgr.mark_running(task["id"])
                try:
                    # Mo is not watching, so the result is inspected before it
                    # counts as done -- a task that reported failure used to be
                    # marked complete.
                    report = assign("", task["description"], verify=True,
                                    source=f"task:{task['id']}",
                                    executor=self._brain_fn)
                    if report.ok:
                        short = (report.result or "Done.")[:200]
                        mgr.complete(task["id"], short)
                        self._deliver(
                            f"Background task done: {task['description'][:50]}. "
                            f"{short[:100]}",
                            remote=True,
                        )
                    else:
                        mgr.fail(task["id"], report.reason or "did not complete")
                        self._deliver(
                            f"Mo, the background task '{task['description'][:50]}' "
                            f"did not get done. {report.reason[:120]}",
                            remote=True,
                        )
                except Exception as e:
                    mgr.fail(task["id"], str(e))
        except Exception as e:
            print(f"[Proactive] autonomous task check error: {e}")

    _MAX_STEPS_PER_CYCLE = 3

    @staticmethod
    def _is_parallelisable(steps: list[dict]) -> bool:
        """True when every step in the group names a DISTINCT registry agent.

        Those agents build their own API client and share no state, so they are
        safe to run at once. A group containing an unassigned step is not: those
        run through brain.chat, which mutates conversation history and the
        live-trading state machine. Two steps naming the same agent are also
        left sequential -- an agent may hold a per-run resource (a browser, the
        mouse), and nothing guarantees two of it can run side by side.
        """
        if len(steps) < 2:
            return False
        agents = [s.get("agent") for s in steps]
        if not all(agents):
            return False
        return len(set(agents)) == len(agents)

    def _run_group_in_parallel(self, mgr, active: dict, context: str,
                               steps: list[dict]) -> None:
        """Execute an all-agent group at once, then apply bookkeeping in step
        order on this thread -- MissionManager rewrites the whole file on every
        write, so concurrent bookkeeping would lose updates."""
        from concurrent.futures import ThreadPoolExecutor

        from core.agents.supervisor import assign

        def run(step: dict):
            return assign(
                step["agent"],
                f"{context}\n\nYour task: {step['description']}",
                acceptance=step.get("acceptance"),
                source=f"mission:{active['id']}",
                max_attempts=1,
            )

        with ThreadPoolExecutor(max_workers=len(steps)) as pool:
            reports = list(pool.map(run, steps))

        for step, report in zip(steps, reports):
            if report.ok:
                mgr.complete_step(active["id"], step["n"], report.result or "Done.")
                continue
            mgr.fail_step(active["id"], step["n"], report.reason)
            refreshed = mgr.last_finished()
            if refreshed and refreshed["id"] == active["id"] \
                    and refreshed["status"] == "blocked":
                self._announce_blocked(active, step, report)
            return

        if mgr.get_active() is None:
            self._announce_complete(mgr)

    def _announce_blocked(self, active: dict, step: dict, report) -> None:
        why = (report.reason or "").strip()[:120]
        if why:
            why = why[0].upper() + why[1:]
            why = why if why.endswith(".") else why + "."
            why += " "
        self._deliver(
            f"Mo, mission '{active['goal']}' is stuck at step "
            f"{step['n']} ({step['description'][:60]}). "
            f"{report.callsign} tried twice. {why}"
            f"Tell me how to proceed.",
            remote=True,
        )

    def _announce_complete(self, mgr) -> None:
        finished = mgr.last_finished()
        if finished and finished["status"] == "done":
            last_result = (finished["steps"][-1].get("result") or "")[:150]
            self._deliver(
                f"Mission complete: {finished['goal']}. {last_result}",
                remote=True,
            )

    def _check_missions(self) -> None:
        """Execute the current group's pending steps (up to 3 per cycle)
        through the supervisor: a step naming an agent goes to that agent, the
        rest run via brain.chat(). Warden inspects every result, so a step only
        advances when the work actually passed. Same-group steps are
        independent; groups run in order. Completion and blockage are announced;
        step results become context for later groups
        (MissionManager.step_context)."""
        try:
            from core.missions import MissionManager
            mgr = MissionManager()
            steps = mgr.next_steps()[: self._MAX_STEPS_PER_CYCLE]
            if not steps:
                return
            # Only unassigned steps need the brain; a mission whose steps are
            # all assigned to agents runs without one.
            if self._brain_fn is None and not all(s.get("agent") for s in steps):
                return
            active = mgr.get_active()
            context = mgr.step_context()
            from core.agents.supervisor import assign

            if self._is_parallelisable(steps):
                self._run_group_in_parallel(mgr, active, context, steps)
                return

            for step in steps:
                agent = step.get("agent")
                if agent:
                    # An assigned step goes to that agent verbatim; the agent
                    # has no conversation history, so it carries its own context.
                    report = assign(
                        agent,
                        f"{context}\n\nYour task: {step['description']}",
                        acceptance=step.get("acceptance"),
                        source=f"mission:{active['id']}",
                        # MissionManager owns the retry: a failed step is
                        # requeued for the next cycle, then blocks.
                        max_attempts=1,
                    )
                else:
                    prompt = (
                        f"{context}\n\n"
                        f"You are executing step {step['n']} of this mission. "
                        f"Do it now using your tools and report the outcome concisely:\n"
                        f"{step['description']}"
                    )
                    report = assign("", prompt,
                                    acceptance=step.get("acceptance"),
                                    source=f"mission:{active['id']}",
                                    executor=self._brain_fn,
                                    max_attempts=1)

                if report.ok:
                    mgr.complete_step(active["id"], step["n"],
                                      report.result or "Done.")
                    continue

                # Warden rejected it, or the agent failed outright. The step is
                # NOT done -- fail_step retries it next cycle, then blocks.
                mgr.fail_step(active["id"], step["n"], report.reason)
                refreshed = mgr.last_finished()
                if refreshed and refreshed["id"] == active["id"] \
                        and refreshed["status"] == "blocked":
                    self._announce_blocked(active, step, report)
                return
            if mgr.get_active() is None:
                self._announce_complete(mgr)
        except Exception as e:
            print(f"[Proactive] mission check error: {e}")

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

    def _check_lunch_logged(self) -> None:
        """Remind Mo if no food logged around lunch time."""
        if self._cooldown("health_lunch_reminder", 20):
            return
        try:
            from core.agents.health_agent import HealthAgent
            from datetime import date
            log   = HealthAgent()._load_meal_log()
            today = date.today().isoformat()
            entry = next((e for e in log.get("entries", []) if e["date"] == today), None)
            if entry is None or len(entry.get("items", [])) == 0:
                self._deliver("Mo, you haven't logged any meals today -- don't skip lunch.")
        except Exception:
            pass

    def _check_daily_nutrition(self) -> None:
        """6 PM nutrition summary -- how close Mo is to daily targets."""
        if self._cooldown("health_daily_summary", 20):
            return
        try:
            from core.agents.health_agent import HealthAgent
            agent   = HealthAgent()
            profile = agent._load_profile()
            if profile is None:
                return
            summary = agent._nutrition_summary(profile)
            if "nothing logged" not in summary.lower():
                self._deliver(f"Nutrition check -- {summary}")
        except Exception:
            pass

    def _check_gym_session(self) -> None:
        """8 PM: if today is a gym day and no workout logged, nudge Mo."""
        if self._cooldown("health_gym_reminder", 20):
            return
        try:
            from core.agents.health_agent import HealthAgent, _GYM_PROGRAM_PATH as gym_path
            import datetime
            if not gym_path.exists():
                return
            program    = json.loads(gym_path.read_text())
            today_name = datetime.datetime.now().strftime("%A").lower()
            session    = program.get("split", {}).get(today_name)
            if not session:
                return
            log   = HealthAgent()._load_workout_log()
            today = datetime.date.today().isoformat()
            if not any(s["date"] == today for s in log.get("sessions", [])):
                self._deliver(f"Mo, it's {session} day -- did you train? Log it when you're done.")
        except Exception:
            pass

    def _check_weekly_gym_report(self) -> None:
        """Monday: weekly gym report."""
        if self._cooldown("health_weekly_report", 144):  # 6 days
            return
        try:
            from core.agents.health_agent import HealthAgent
            from datetime import date, timedelta
            log      = HealthAgent()._load_workout_log()
            week_ago = (date.today() - timedelta(days=7)).isoformat()
            sessions = [s for s in log.get("sessions", []) if s["date"] >= week_ago]
            count    = len(sessions)
            if count == 0:
                self._deliver("Weekly gym report -- no sessions logged last week. Get back on track, Mo.")
            else:
                days = ", ".join(s["session"].capitalize() for s in sessions[-3:])
                self._deliver(f"Weekly gym report -- {count} sessions last week. Latest: {days}.")
        except Exception:
            pass

    _DEFAULT_API_BUDGET_USD = 5.0

    def _check_api_budget(self) -> None:
        """Evening warning when today's Claude API spend exceeds the budget.
        Budget: data/settings.json 'api_daily_budget_usd' (0 disables)."""
        if self._cooldown("api_budget", 20):
            return
        try:
            budget = self._DEFAULT_API_BUDGET_USD
            settings_path = Path("data/settings.json")
            if settings_path.exists():
                try:
                    settings = json.loads(settings_path.read_text(encoding="utf-8"))
                    budget = float(settings.get("api_daily_budget_usd",
                                                self._DEFAULT_API_BUDGET_USD))
                except Exception:
                    pass
            if budget <= 0:
                return
            from core.telemetry import cost_today
            spent = cost_today()
            if spent > budget:
                self._deliver(
                    f"Mo, heads up -- I've cost about ${spent:.2f} in API calls "
                    f"today, over your ${budget:.2f} daily budget."
                )
            else:
                self._reset_cooldown("api_budget")
        except Exception:
            pass

    _TOKEN_FILES = ("data/token.json", "data/token_gmail.json", "data/token_gdrive.json")
    _TOKEN_WARN_AGE_DAYS = 6  # Testing-mode refresh tokens die at 7 days

    def _check_oauth_tokens(self) -> None:
        """Morning warning when a Google OAuth token is close to the 7-day
        Testing-mode revocation, so re-auth happens before things silently break."""
        if self._cooldown("oauth_tokens", 20):
            return
        try:
            stale = []
            for name in self._TOKEN_FILES:
                p = Path(name)
                if not p.exists():
                    continue
                age_days = (time.time() - p.stat().st_mtime) / 86400
                if age_days >= self._TOKEN_WARN_AGE_DAYS:
                    stale.append(f"{p.name} ({age_days:.0f} days old)")
            if stale:
                self._deliver(
                    "Mo, Google login tokens are about to expire: "
                    + ", ".join(stale)
                    + ". Say 'check my email' or 'check my calendar' to re-auth before they break."
                )
            else:
                self._reset_cooldown("oauth_tokens")
        except Exception:
            pass

    def _check_skill_proposals(self) -> None:
        """Morning: mine the conversation logs for repeated asks and offer
        AT MOST ONE new skill proposal per day (propose, never impose)."""
        if self._cooldown("skill_proposals", 20):
            return
        try:
            from core.skills.miner import HabitMiner
            miner = HabitMiner()
            miner.mine()
            pending = miner.pending()
            if not pending:
                self._reset_cooldown("skill_proposals")
                return
            p = pending[0]
            self._deliver(
                f"Mo, you've asked \"{p['example']}\" {p['count']} times across "
                f"{p['days_seen']} days. Want me to save it as a skill? "
                f"Say 'make it a skill' or 'dismiss it'."
            )
        except Exception as e:
            print(f"[Proactive] skill proposal check error: {e}")

    _GATE_MIN_SHARPE = 1.0
    _GATE_MAX_DRAWDOWN = 15.0

    def _check_nightly_backtest(self) -> None:
        """Nightly (11 PM Cairo, after US close): re-run the full backtest and
        speak up only when a symbol's gate metric regressed."""
        if self._cooldown("nightly_backtest", 20):
            return
        try:
            results_path = Path("data/backtest_results.json")
            previous: dict = {}
            if results_path.exists():
                try:
                    previous = json.loads(results_path.read_text(encoding="utf-8"))
                except Exception:
                    previous = {}

            from tools.backtest_tool import run_full_backtest
            run_full_backtest()  # refreshes data/backtest_results.json

            if not results_path.exists():
                return
            current = json.loads(results_path.read_text(encoding="utf-8"))

            regressions = []
            for symbol, stats in current.items():
                if symbol.startswith("_") or not isinstance(stats, dict):
                    continue
                sharpe = stats.get("sharpe_ratio", 0)
                drawdown = stats.get("max_drawdown_pct", 0)
                ret = stats.get("total_return_pct", 0)
                prev = previous.get(symbol) or {}
                if drawdown > self._GATE_MAX_DRAWDOWN:
                    regressions.append(f"{symbol} drawdown {drawdown:.1f}%")
                elif prev.get("sharpe_ratio", 0) >= self._GATE_MIN_SHARPE > sharpe:
                    regressions.append(f"{symbol} Sharpe fell to {sharpe:.2f}")
                elif prev.get("total_return_pct", 0) > 0 > ret:
                    regressions.append(f"{symbol} return went negative ({ret:.1f}%)")

            if regressions:
                self._deliver(
                    "Nightly backtest warning -- " + " | ".join(regressions[:3])
                    + ". Review before the next trading session.",
                    remote=True,
                )
        except Exception as e:
            print(f"[Proactive] nightly backtest error: {e}")

    def _check_rest_day(self) -> None:
        """Suggest rest after 4 consecutive training days."""
        if self._cooldown("health_rest_suggestion", 20):
            return
        try:
            from core.agents.health_agent import HealthAgent
            from datetime import date, timedelta
            log = HealthAgent()._load_workout_log()
            consecutive = 0
            for i in range(4):
                check_date = (date.today() - timedelta(days=i)).isoformat()
                if any(s["date"] == check_date for s in log.get("sessions", [])):
                    consecutive += 1
                else:
                    break
            if consecutive >= 4:
                self._deliver("Mo, you've trained 4 days straight -- consider a rest day for recovery.")
        except Exception:
            pass
