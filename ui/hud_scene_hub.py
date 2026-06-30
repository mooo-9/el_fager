"""
El Fager — HUD scene data hub.

Background QThread that fetches live data for all non-market HUD scenes:
  Briefing (9) — Cairo weather via Open-Meteo
  Inbox    (6) — Gmail unread count + latest sender
  Agenda   (7) — Next Google Calendar event today
  Memory   (8) — Facts + ChromaDB entry count
  Devices  (4) — CPU / RAM / disk via psutil
  Food    (10) — Macro targets from health_profile.json + today's logged meals
  Gym     (11) — PPL split day + workout log status

Each signal carries (prefix, highlight, suffix, tag) that maps directly
to HudWebView.push_proactive(scene, prefix, highlight, suffix, tag).

Initial delay: 20 s (staggers behind MarketUpdater's 8 s delay).
Refresh: every 5 minutes thereafter.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

_INIT_DELAY = 20
_INTERVAL   = 300          # 5 minutes
_DATA_DIR   = Path(__file__).parent.parent / "data"

# PPL split by weekday
_SPLIT = {
    "Monday":    "Push",
    "Tuesday":   "Pull",
    "Wednesday": "Legs",
    "Thursday":  "Push",
    "Friday":    "Pull",
    "Saturday":  "Legs",
    "Sunday":    "Rest",
}


class HudSceneHub(QThread):
    """Fetches live data for HUD scenes and emits (prefix, highlight, suffix, tag) signals."""

    # Each signal → push_proactive(scene_index, *args)
    briefing_ready  = pyqtSignal(str, str, str, str)   # scene 9
    inbox_ready     = pyqtSignal(str, str, str, str)   # scene 6
    agenda_ready    = pyqtSignal(str, str, str, str)   # scene 7
    memory_ready    = pyqtSignal(str, str, str, str)   # scene 8
    devices_ready   = pyqtSignal(str, str, str, str)   # scene 4
    nutrition_ready = pyqtSignal(str, str, str, str)   # scene 10 proactive banner
    nutrition_data  = pyqtSignal(int, int, int, int, int, int, int, int)  # full macro data
    gym_ready       = pyqtSignal(str, str, str, str)   # scene 11

    def run(self) -> None:
        for _ in range(_INIT_DELAY):
            if self.isInterruptionRequested():
                return
            time.sleep(1)

        while not self.isInterruptionRequested():
            try:
                self._fetch_all()
            except Exception as e:
                print(f"[SceneHub] Cycle error: {e}", flush=True)
            for _ in range(_INTERVAL):
                if self.isInterruptionRequested():
                    return
                time.sleep(1)

    # ------------------------------------------------------------------ #
    #  Fetch all scenes                                                    #
    # ------------------------------------------------------------------ #

    def _fetch_all(self):
        self._fetch_briefing()
        self._fetch_inbox()
        self._fetch_agenda()
        self._fetch_memory()
        self._fetch_devices()
        self._fetch_nutrition()
        self._fetch_gym()

    # ── Briefing (scene 9) ─────────────────────────────────────────────────

    def _fetch_briefing(self):
        try:
            from tools.weather_tool import get_weather
            raw = get_weather("cairo")
            # raw: "cairo — 37.8°C (feels 36.9°C), Partly cloudy\nHumidity: ..."
            line1 = raw.split("\n")[0]
            if "—" in line1 and "°C" in line1:
                after_dash = line1.split("—", 1)[-1].strip()
                # "37.8°C (feels 36.9°C), Partly cloudy"
                temp = after_dash.split("(")[0].strip()          # "37.8°C"
                cond = after_dash.split(",", 1)[-1].strip() if "," in after_dash else ""
                self.briefing_ready.emit("Cairo ", temp, f"  ·  {cond}" if cond else "", "WEATHER")
            else:
                self.briefing_ready.emit("", raw[:60], "", "WEATHER")
        except Exception as e:
            print(f"[SceneHub] Briefing: {e}", flush=True)

    # ── Inbox (scene 6) ────────────────────────────────────────────────────

    def _fetch_inbox(self):
        try:
            from tools.gmail_tool import GMAIL_AVAILABLE, get_gmail_service
            if not GMAIL_AVAILABLE:
                self.inbox_ready.emit("Gmail ", "not connected", "", "INBOX")
                return

            service = get_gmail_service()
            if service is None:
                self.inbox_ready.emit("Gmail ", "auth error", "", "INBOX")
                return

            result = (
                service.users().messages()
                .list(userId="me", q="is:unread", maxResults=1)
                .execute()
            )
            count = result.get("resultSizeEstimate", 0)
            messages = result.get("messages", [])

            if not count:
                self.inbox_ready.emit("Inbox ", "up to date", "  ·  no unread mail", "INBOX")
                return

            sender = "Unknown"
            if messages:
                meta = (
                    service.users().messages()
                    .get(userId="me", id=messages[0]["id"], format="metadata",
                         metadataHeaders=["From"])
                    .execute()
                )
                for h in meta.get("payload", {}).get("headers", []):
                    if h["name"] == "From":
                        raw_from = h["value"]
                        sender = raw_from.split("<")[0].strip().strip('"') or raw_from
                        break

            label = f"{min(count, 999)}{'+'*(count>999)} unread"
            self.inbox_ready.emit(f"{label}  ·  Latest: ", sender[:28], "", "INBOX")
        except Exception as e:
            print(f"[SceneHub] Inbox: {e}", flush=True)

    # ── Agenda (scene 7) ───────────────────────────────────────────────────

    def _fetch_agenda(self):
        try:
            from tools.calendar_tool import CALENDAR_AVAILABLE, get_calendar_service
            if not CALENDAR_AVAILABLE:
                self.agenda_ready.emit("Calendar ", "not connected", "", "AGENDA")
                return

            service = get_calendar_service()
            if service is None:
                self.agenda_ready.emit("Calendar ", "auth error", "", "AGENDA")
                return

            now = datetime.now(tz=timezone.utc)
            end = now.replace(hour=23, minute=59, second=59, microsecond=0)

            result = (
                service.events().list(
                    calendarId="primary",
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    maxResults=1,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
            )
            events = result.get("items", [])
            if not events:
                self.agenda_ready.emit("Agenda ", "clear today", "  ·  no upcoming events", "AGENDA")
                return

            ev = events[0]
            title = (ev.get("summary") or "Event")[:28]
            start = ev.get("start", {})
            start_str = start.get("dateTime", start.get("date", ""))
            time_label = ""
            if "T" in start_str:
                from zoneinfo import ZoneInfo
                parsed = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                cairo = parsed.astimezone(ZoneInfo("Africa/Cairo"))
                time_label = f"  ·  {cairo.strftime('%I:%M %p')}"
            self.agenda_ready.emit("Next: ", f"'{title}'", time_label, "AGENDA")
        except Exception as e:
            print(f"[SceneHub] Agenda: {e}", flush=True)

    # ── Memory (scene 8) ───────────────────────────────────────────────────

    def _fetch_memory(self):
        try:
            # Personal facts count
            facts_path = _DATA_DIR / "facts.json"
            fact_count = 0
            if facts_path.exists():
                raw = json.loads(facts_path.read_text(encoding="utf-8"))
                facts_list = raw.get("facts", raw) if isinstance(raw, dict) else raw
                fact_count = len(facts_list) if isinstance(facts_list, list) else 0

            # ChromaDB conversation memory count
            chroma_count = 0
            try:
                import chromadb
                client = chromadb.PersistentClient(path=str(_DATA_DIR / "chroma"))
                col = client.get_or_create_collection("memory")
                chroma_count = col.count()
            except Exception:
                pass

            total = fact_count + chroma_count
            self.memory_ready.emit(
                "Memory bank: ",
                f"{total} entries",
                f"  ·  {fact_count} facts  ·  {chroma_count} memories",
                "MEMORY",
            )
        except Exception as e:
            print(f"[SceneHub] Memory: {e}", flush=True)

    # ── Devices (scene 4) ──────────────────────────────────────────────────

    def _fetch_devices(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")

            ram_gb  = ram.used  / (1024 ** 3)
            tot_gb  = ram.total / (1024 ** 3)
            free_gb = disk.free / (1024 ** 3)

            self.devices_ready.emit(
                f"CPU {cpu:.0f}%  ·  RAM ",
                f"{ram_gb:.1f}/{tot_gb:.0f} GB",
                f"  ·  {free_gb:.0f} GB free",
                "SYSTEM",
            )
        except Exception as e:
            print(f"[SceneHub] Devices: {e}", flush=True)

    # ── Nutrition (scene 10) ───────────────────────────────────────────────

    def _fetch_nutrition(self):
        try:
            profile_path = _DATA_DIR / "health_profile.json"
            if not profile_path.exists():
                self.nutrition_ready.emit("Nutrition ", "profile not set", "", "FOOD")
                return

            p = json.loads(profile_path.read_text(encoding="utf-8"))
            targets   = p.get("targets", {})
            overrides = p.get("overrides", {})

            kcal    = round(targets.get("kcal", 0))
            protein = round(overrides.get("protein_g", targets.get("protein_g", 0)))
            carbs   = round(targets.get("carbs_g", 0))
            fat     = round(targets.get("fat_g", 0))

            # Check today's logged meals
            meal_log_path = _DATA_DIR / "meal_log.json"
            logged_kcal   = 0
            if meal_log_path.exists():
                try:
                    log_data = json.loads(meal_log_path.read_text(encoding="utf-8"))
                    today_s  = date.today().isoformat()
                    entries  = (
                        log_data if isinstance(log_data, list)
                        else log_data.get("entries", [])
                    )
                    logged_kcal = sum(
                        e.get("kcal", 0) for e in entries
                        if e.get("date", "")[:10] == today_s
                    )
                except Exception:
                    pass

            # Emit full macro data for buildNutri patch
            self.nutrition_data.emit(kcal, protein, carbs, fat, logged_kcal, 0, 0, 0)

            if logged_kcal:
                remaining = max(0, kcal - logged_kcal)
                self.nutrition_ready.emit(
                    f"{logged_kcal} kcal logged  ·  ",
                    f"{remaining} remaining",
                    f"  ·  target {kcal}",
                    "FOOD",
                )
            else:
                self.nutrition_ready.emit(
                    f"Target: {kcal} kcal  ·  ",
                    f"{protein}g protein",
                    f"  ·  {carbs}g carbs  ·  {fat}g fat",
                    "FOOD",
                )
        except Exception as e:
            print(f"[SceneHub] Nutrition: {e}", flush=True)

    # ── Gym (scene 11) ─────────────────────────────────────────────────────

    def _fetch_gym(self):
        try:
            today      = date.today()
            day_name   = today.strftime("%A")
            session    = _SPLIT.get(day_name, "Training")

            # Check workout log
            log_path         = _DATA_DIR / "workout_log.json"
            completed_today  = False
            if log_path.exists():
                try:
                    log_data = json.loads(log_path.read_text(encoding="utf-8"))
                    today_s  = today.isoformat()
                    entries  = (
                        log_data if isinstance(log_data, list)
                        else log_data.get("entries", [])
                    )
                    completed_today = any(
                        e.get("date", "")[:10] == today_s for e in entries
                    )
                except Exception:
                    pass

            if session == "Rest":
                self.gym_ready.emit("Today: ", "Rest Day", "  ·  recovery & mobility", "GYM")
            elif completed_today:
                self.gym_ready.emit(f"{session} Day ", "COMPLETE", "  ·  great work", "GYM")
            else:
                self.gym_ready.emit("Today: ", f"{session} Day", "  ·  session ready", "GYM")
        except Exception as e:
            print(f"[SceneHub] Gym: {e}", flush=True)
