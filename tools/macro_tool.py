"""
Macro tool — define and run named sequences of tool calls.

Step types
----------
  {"tool": "get_weather", "args": {...}}     — call a tool
  {"type": "speak",  "text": "Good morning!"}  — speak a line mid-macro
  {"type": "wait",   "seconds": 3}             — pause between steps
  {"type": "notify", "title": "...", "message": "..."} — Windows toast only

Built-in sync
-------------
On every load, built-in entries in macros.json are refreshed from _BUILTIN_MACROS
(new built-ins and step fixes propagate automatically; run_count / last_run preserved
in data/macro_stats.json which is never overwritten).

Custom macros are persisted to data/macros.json.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

_MACROS_FILE = Path("data/macros.json")
_STATS_FILE  = Path("data/macro_stats.json")
_MAX_RECURSION_DEPTH = 3

# ── Global speak callback (set from main.py) ──────────────────────────────────
_SPEAK_FN: Callable[[str], None] | None = None

def set_speak_callback(fn: Callable[[str], None]) -> None:
    global _SPEAK_FN
    _SPEAK_FN = fn

def _macro_speak(text: str) -> None:
    """Speak mid-macro text via TTS or fallback to toast."""
    if _SPEAK_FN:
        try:
            _SPEAK_FN(text)
            return
        except Exception:
            pass
    try:
        from winotify import Notification
        Notification(app_id="El Fager", title="El Fager", msg=text[:256], duration="short").show()
    except Exception:
        print(f"[Macro] {text}")

def _macro_notify(title: str, message: str) -> None:
    """Show a Windows toast only (no TTS)."""
    try:
        from winotify import Notification
        Notification(app_id="El Fager", title=title, msg=message[:256], duration="long").show()
    except Exception:
        print(f"[Macro notify] {title}: {message}")


# ──────────────────────────────────────────────────────────────────────────────
# Built-in macros
# ──────────────────────────────────────────────────────────────────────────────

_BUILTIN_MACROS: list[dict] = [
    # ── Morning ───────────────────────────────────────────────────────────────
    {
        "name": "morning_routine",
        "description": "Full morning ritual — greeting, weather, prayer, calendar, emails, headlines, sunrise lights, music",
        "builtin": True,
        "tags": ["morning", "daily", "routine"],
        "voice_triggers": [
            "good morning", "morning", "morning routine", "sabaho", "sabah el kheer",
            "yala kol youm", "fel sub7", "el sub7", "wake up routine",
        ],
        "steps": [
            {"type": "speak",  "text": "Good morning Mo! Let me get you ready for the day."},
            {"tool": "get_weather",       "args": {"city": "Cairo"}},
            {"tool": "get_next_prayer",   "args": {}},
            {"tool": "list_events",       "args": {"time_range": "today", "max_results": 5}},
            {"tool": "list_messages",     "args": {"n": 3, "unread_only": True}},
            {"tool": "get_all_headlines", "args": {"n": 2}},
            {"tool": "hue_wake_up",       "args": {"light": "all", "duration_minutes": 15}},
            {"tool": "set_system_volume", "args": {"level": 40}},
            {"tool": "play_music",        "args": {"query": "morning chill"}},
        ],
    },
    # ── Night ─────────────────────────────────────────────────────────────────
    {
        "name": "night_routine",
        "description": "Evening wind-down — prayer, recap, tomorrow's agenda, sleep lights, fade, sleep music",
        "builtin": True,
        "tags": ["evening", "night", "daily", "routine"],
        "voice_triggers": [
            "good night", "night routine", "going to sleep", "i'm sleeping",
            "tes7a", "leila sa3ida", "ana ray7 anam", "wind down", "bedtime",
        ],
        "steps": [
            {"type": "speak",  "text": "Good night Mo. Here's your end-of-day recap."},
            {"tool": "get_next_prayer",   "args": {}},
            {"tool": "get_journal_stats", "args": {}},
            {"tool": "get_expense_summary","args": {"period": "today"}},
            {"tool": "list_events",       "args": {"time_range": "tomorrow", "max_results": 3}},
            {"tool": "hue_scene",         "args": {"scene_name": "sleep",   "light": "all"}},
            {"tool": "hue_brightness",    "args": {"level": 15, "light": "all"}},
            {"tool": "hue_fade_off",      "args": {"light": "all", "seconds": 1800}},
            {"tool": "set_system_volume", "args": {"level": 20}},
            {"tool": "play_music",        "args": {"query": "sleep music calm"}},
        ],
    },
    # ── Study ────────────────────────────────────────────────────────────────
    {
        "name": "study_mode",
        "description": "Focus session — check agenda, enable focus mode, 25-min Pomodoro, study lights, lofi music",
        "builtin": True,
        "tags": ["focus", "study", "work"],
        "voice_triggers": [
            "study mode", "study time", "let's study", "start studying", "focus mode",
            "5alena nadros", "5alini atrakez", "yala nabda2", "vamos estudiar",
        ],
        "steps": [
            {"type": "speak",  "text": "Study mode activated. Let's focus!"},
            {"tool": "list_events",       "args": {"time_range": "today", "max_results": 3}},
            {"tool": "enable_focus_mode", "args": {"hours": 2}},
            {"tool": "start_pomodoro",    "args": {"minutes": 25, "label": "Study"}},
            {"tool": "hue_scene",         "args": {"scene_name": "study",   "light": "all"}},
            {"tool": "hue_brightness",    "args": {"level": 85, "light": "all"}},
            {"tool": "hue_temperature",   "args": {"temp": "reading",       "light": "all"}},
            {"tool": "set_system_volume", "args": {"level": 35}},
            {"tool": "play_music",        "args": {"query": "lofi hip hop study"}},
        ],
    },
    # ── Chill ────────────────────────────────────────────────────────────────
    {
        "name": "chill_mode",
        "description": "Relax — stop focus and Pomodoro, warm dim lights, chill music",
        "builtin": True,
        "tags": ["relax", "break"],
        "voice_triggers": [
            "chill mode", "relax mode", "take a break", "chill out", "relax",
            "5ala9", "5odha rah", "raha", "istara7",
        ],
        "steps": [
            {"tool": "stop_pomodoro",      "args": {}},
            {"tool": "disable_focus_mode", "args": {}},
            {"tool": "hue_scene",          "args": {"scene_name": "relax", "light": "all"}},
            {"tool": "hue_brightness",     "args": {"level": 50, "light": "all"}},
            {"tool": "hue_temperature",    "args": {"temp": "warm",         "light": "all"}},
            {"tool": "set_system_volume",  "args": {"level": 45}},
            {"tool": "play_music",         "args": {"query": "chill lofi vibes"}},
        ],
    },
    # ── Break ─────────────────────────────────────────────────────────────────
    {
        "name": "break_time",
        "description": "Short break — stop Pomodoro, bright warm lights, light break music",
        "builtin": True,
        "tags": ["focus", "break"],
        "voice_triggers": [
            "break time", "take a break", "short break", "5 minute break",
            "aste ra7a", "5od ra7a", "break",
        ],
        "steps": [
            {"type": "speak",  "text": "Break time, Mo! Stand up, stretch, hydrate."},
            {"tool": "stop_pomodoro",     "args": {}},
            {"tool": "hue_brightness",    "args": {"level": 70, "light": "all"}},
            {"tool": "hue_temperature",   "args": {"temp": "cool",       "light": "all"}},
            {"tool": "set_system_volume", "args": {"level": 40}},
            {"tool": "play_music",        "args": {"query": "short break lo-fi"}},
            {"type": "notify", "title": "Break Time", "message": "5 minutes — stand, stretch, drink water. Back in 5!"},
        ],
    },
    # ── Exam mode ─────────────────────────────────────────────────────────────
    {
        "name": "exam_mode",
        "description": "Maximum focus for exams — 50-min deep Pomodoro, daylight lights, muted distractions",
        "builtin": True,
        "tags": ["focus", "study", "exam"],
        "voice_triggers": [
            "exam mode", "exam time", "i have an exam", "finals mode",
            "el ekhtibar", "el imtihan", "yala nemtahan", "deep focus",
        ],
        "steps": [
            {"type": "speak",  "text": "Exam mode, Mo. Maximum concentration. You've got this!"},
            {"tool": "list_events",       "args": {"time_range": "today", "max_results": 2}},
            {"tool": "enable_focus_mode", "args": {"hours": 3}},
            {"tool": "start_pomodoro",    "args": {"minutes": 50, "label": "Exam"}},
            {"tool": "hue_brightness",    "args": {"level": 100, "light": "all"}},
            {"tool": "hue_temperature",   "args": {"temp": "daylight",    "light": "all"}},
            {"tool": "pause_music",       "args": {}},
            {"tool": "set_system_volume", "args": {"level": 15}},
            {"type": "notify", "title": "Exam Mode", "message": "50-min deep work session started. No distractions."},
        ],
    },
    # ── Deep work ─────────────────────────────────────────────────────────────
    {
        "name": "deep_work",
        "description": "2-hour deep work block — 50-min Pomodoro, no music, daylight lights",
        "builtin": True,
        "tags": ["focus", "work"],
        "voice_triggers": [
            "deep work", "deep focus", "2 hours focus", "no distractions",
            "serious mode", "concentration mode",
        ],
        "steps": [
            {"type": "speak",  "text": "Deep work session. Two hours, maximum output."},
            {"tool": "enable_focus_mode", "args": {"hours": 2}},
            {"tool": "start_pomodoro",    "args": {"minutes": 50, "label": "Deep Work"}},
            {"tool": "hue_brightness",    "args": {"level": 95, "light": "all"}},
            {"tool": "hue_temperature",   "args": {"temp": "daylight",    "light": "all"}},
            {"tool": "pause_music",       "args": {}},
            {"tool": "mute_system",       "args": {}},
            {"type": "notify", "title": "Deep Work", "message": "50-min block started. Come back when done."},
        ],
    },
    # ── Workout ───────────────────────────────────────────────────────────────
    {
        "name": "workout_mode",
        "description": "High-energy workout — loud music, bright energize lights",
        "builtin": True,
        "tags": ["health", "energy"],
        "voice_triggers": [
            "workout mode", "gym mode", "let's work out", "exercise time",
            "sports mode", "yala netrenen", "let's go", "hype mode",
        ],
        "steps": [
            {"type": "speak",  "text": "Let's go Mo! Time to move!"},
            {"tool": "disable_focus_mode","args": {}},
            {"tool": "hue_scene",         "args": {"scene_name": "energize", "light": "all"}},
            {"tool": "hue_brightness",    "args": {"level": 100, "light": "all"}},
            {"tool": "set_system_volume", "args": {"level": 80}},
            {"tool": "play_music",        "args": {"query": "workout hype"}},
        ],
    },
    # ── Prayer ────────────────────────────────────────────────────────────────
    {
        "name": "prayer_mode",
        "description": "Prayer time — pause music, dim warm reading lights, show prayer times",
        "builtin": True,
        "tags": ["prayer", "daily"],
        "voice_triggers": [
            "prayer time", "prayer mode", "it's prayer time", "salah time",
            "wa2et el salah", "el salah", "time to pray", "wakt elsalah",
        ],
        "steps": [
            {"tool": "pause_music",       "args": {}},
            {"tool": "hue_scene",         "args": {"scene_name": "reading", "light": "all"}},
            {"tool": "hue_brightness",    "args": {"level": 40, "light": "all"}},
            {"tool": "hue_temperature",   "args": {"temp": "warm",          "light": "all"}},
            {"tool": "set_system_volume", "args": {"level": 0}},
            {"tool": "get_prayer_times",  "args": {}},
        ],
    },
    # ── Nap ───────────────────────────────────────────────────────────────────
    {
        "name": "nap_time",
        "description": "Power nap — sleep lights, reminder in 20 minutes",
        "builtin": True,
        "tags": ["rest", "sleep"],
        "voice_triggers": [
            "nap time", "power nap", "quick nap", "i'm napping", "ana 7anam shewaya",
            "nap mode", "quick sleep",
        ],
        "steps": [
            {"type": "speak",  "text": "Nap time. I'll wake you in 20 minutes, Mo. Sleep well."},
            {"tool": "pause_music",       "args": {}},
            {"tool": "hue_scene",         "args": {"scene_name": "sleep", "light": "all"}},
            {"tool": "hue_brightness",    "args": {"level": 5,  "light": "all"}},
            {"tool": "set_system_volume", "args": {"level": 0}},
            {"tool": "set_reminder",      "args": {"message": "Wake up from nap! Time to get back to work.", "minutes": 20}},
            {"type": "notify", "title": "Nap Timer Set", "message": "20-minute nap started. Wake-up reminder set."},
        ],
    },
    # ── Gaming ────────────────────────────────────────────────────────────────
    {
        "name": "gaming_mode",
        "description": "Gaming session — colorloop lights, gaming music, disable focus mode",
        "builtin": True,
        "tags": ["entertainment", "relax"],
        "voice_triggers": [
            "gaming mode", "game time", "let's play", "gaming", "yala nel3ab",
            "ps5 time", "pc gaming", "game on",
        ],
        "steps": [
            {"tool": "disable_focus_mode","args": {}},
            {"tool": "hue_effect",        "args": {"effect": "colorloop", "light": "all"}},
            {"tool": "hue_brightness",    "args": {"level": 60, "light": "all"}},
            {"tool": "set_system_volume", "args": {"level": 60}},
            {"tool": "play_music",        "args": {"query": "gaming music epic"}},
        ],
    },
    # ── Coffee ────────────────────────────────────────────────────────────────
    {
        "name": "coffee_time",
        "description": "Coffee break — warm dim lights, cafe jazz",
        "builtin": True,
        "tags": ["break", "relax"],
        "voice_triggers": [
            "coffee time", "coffee break", "need coffee", "cafe mode",
            "ah2wi", "3ayez coffee", "coffee", "ahwa",
        ],
        "steps": [
            {"type": "speak",  "text": "Coffee time. Enjoy the break, Mo."},
            {"tool": "hue_brightness",    "args": {"level": 45, "light": "all"}},
            {"tool": "hue_temperature",   "args": {"temp": "candle",        "light": "all"}},
            {"tool": "set_system_volume", "args": {"level": 35}},
            {"tool": "play_music",        "args": {"query": "cafe jazz acoustic morning"}},
        ],
    },
    # ── Leave home ────────────────────────────────────────────────────────────
    {
        "name": "leave_home",
        "description": "Leaving — weather check, pause music, lights off",
        "builtin": True,
        "tags": ["home", "routine"],
        "voice_triggers": [
            "leaving home", "i'm leaving", "bye", "going out", "leaving",
            "ana ray7", "5alas 3ayez a5rog", "ta3ala",
        ],
        "steps": [
            {"tool": "get_weather",    "args": {"city": "Cairo"}},
            {"tool": "get_next_prayer","args": {}},
            {"tool": "pause_music",    "args": {}},
            {"tool": "hue_off",        "args": {"light": "all"}},
            {"type": "notify", "title": "Left Home", "message": "Lights off, music paused. Have a great time!"},
        ],
    },
    # ── Weekend ───────────────────────────────────────────────────────────────
    {
        "name": "weekend_mode",
        "description": "Weekend vibes — no focus, warm lights, weekend playlist",
        "builtin": True,
        "tags": ["relax", "weekend"],
        "voice_triggers": [
            "weekend mode", "it's the weekend", "weekend", "yala weekend",
            "el weekend", "no work today", "lazy day",
        ],
        "steps": [
            {"type": "speak",  "text": "Weekend vibes, Mo! No work allowed."},
            {"tool": "disable_focus_mode", "args": {}},
            {"tool": "stop_pomodoro",      "args": {}},
            {"tool": "hue_scene",          "args": {"scene_name": "relax", "light": "all"}},
            {"tool": "hue_brightness",     "args": {"level": 60, "light": "all"}},
            {"tool": "hue_temperature",    "args": {"temp": "warm",         "light": "all"}},
            {"tool": "set_system_volume",  "args": {"level": 55}},
            {"tool": "play_music",         "args": {"query": "weekend vibes happy"}},
        ],
    },
    # ── Commute ───────────────────────────────────────────────────────────────
    {
        "name": "commute_mode",
        "description": "Commuting — weather, top news, podcast or music",
        "builtin": True,
        "tags": ["commute", "travel"],
        "voice_triggers": [
            "commute mode", "i'm commuting", "on the way", "metro mode",
            "ana fi 3agala", "going to uni", "going to work", "commuting",
        ],
        "steps": [
            {"type": "speak",  "text": "Commute mode. Here's what you need for the road."},
            {"tool": "get_weather",       "args": {"city": "Cairo"}},
            {"tool": "get_next_prayer",   "args": {}},
            {"tool": "get_all_headlines", "args": {"n": 3}},
            {"tool": "set_system_volume", "args": {"level": 70}},
            {"tool": "play_music",        "args": {"query": "podcast learning"}},
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_macros() -> list[dict]:
    """
    Load macros, always refreshing built-in definitions from _BUILTIN_MACROS.
    Custom macros are preserved. Run stats (last_run, run_count) live in
    data/macro_stats.json and are never overwritten.
    """
    if _MACROS_FILE.exists():
        try:
            saved = json.loads(_MACROS_FILE.read_text(encoding="utf-8"))
        except Exception:
            saved = []
    else:
        saved = []

    builtin_names = {m["name"] for m in _BUILTIN_MACROS}
    customs = [m for m in saved if not m.get("builtin") and m["name"] not in builtin_names]
    merged  = list(_BUILTIN_MACROS) + customs
    _save_macros(merged)
    return merged


def _save_macros(data: list[dict]) -> None:
    _MACROS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MACROS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _load_stats() -> dict:
    if _STATS_FILE.exists():
        try:
            return json.loads(_STATS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_stats(stats: dict) -> None:
    _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATS_FILE.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _record_run(name: str) -> None:
    stats = _load_stats()
    entry = stats.get(name, {"run_count": 0, "last_run": None})
    entry["run_count"] += 1
    entry["last_run"]   = datetime.now().isoformat()
    stats[name] = entry
    _save_stats(stats)


def _find_macro(name: str, macros: list[dict]) -> dict | None:
    return next((m for m in macros if m["name"].lower() == name.lower()), None)


# ──────────────────────────────────────────────────────────────────────────────
# Step dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def _dispatch_macro_step(tool_name: str, args: dict, _depth: int = 0) -> str:
    """
    Run a single tool-type step. _depth prevents infinite macro→macro recursion.
    """
    if _depth >= _MAX_RECURSION_DEPTH:
        return f"[macro] max nesting depth ({_MAX_RECURSION_DEPTH}) reached — skipping '{tool_name}'"

    try:
        # ── Weather ──────────────────────────────────────────────────────
        if tool_name == "get_weather":
            from tools.weather_tool import get_weather
            return get_weather(args.get("city", "Cairo"))
        if tool_name == "get_weather_forecast":
            from tools.weather_tool import get_weather_forecast
            return get_weather_forecast(args.get("city", "Cairo"), args.get("days", 3))
        if tool_name == "get_hourly_weather":
            from tools.weather_tool import get_hourly_weather
            return get_hourly_weather(args.get("city", "Cairo"), args.get("hours", 12))

        # ── Calendar ─────────────────────────────────────────────────────
        if tool_name in ("list_events", "list_calendar_events"):
            from tools.calendar_tool import list_events
            return list_events(args.get("time_range", "today"), args.get("max_results", 10))

        # ── Email ────────────────────────────────────────────────────────
        if tool_name in ("list_messages", "list_emails"):
            from tools.gmail_tool import list_messages
            return list_messages(args.get("n", 5), args.get("unread_only", True))

        # ── Prayer times ─────────────────────────────────────────────────
        if tool_name == "get_prayer_times":
            from tools.prayer_tool import get_prayer_times
            return get_prayer_times()
        if tool_name == "get_next_prayer":
            from tools.prayer_tool import get_next_prayer
            return get_next_prayer()

        # ── Hue — single lights ───────────────────────────────────────────
        if tool_name == "hue_on":
            from tools.smarthome_tool import hue_on
            return hue_on(args.get("light", "all"))
        if tool_name == "hue_off":
            from tools.smarthome_tool import hue_off
            return hue_off(args.get("light", "all"))
        if tool_name == "hue_toggle":
            from tools.smarthome_tool import hue_toggle
            return hue_toggle(args.get("light", "all"))
        if tool_name == "hue_brightness":
            from tools.smarthome_tool import hue_brightness
            return hue_brightness(int(args.get("level", 80)), args.get("light", "all"))
        if tool_name == "hue_color":
            from tools.smarthome_tool import hue_color
            return hue_color(args.get("color", "white"), args.get("light", "all"))
        if tool_name == "hue_temperature":
            from tools.smarthome_tool import hue_temperature
            return hue_temperature(str(args.get("temp", "neutral")), args.get("light", "all"))
        if tool_name == "hue_scene":
            from tools.smarthome_tool import hue_scene
            return hue_scene(args.get("scene_name", "relax"), args.get("light", "all"))
        if tool_name == "hue_alert":
            from tools.smarthome_tool import hue_alert
            return hue_alert(args.get("light", "all"), args.get("mode", "short"))
        if tool_name == "hue_effect":
            from tools.smarthome_tool import hue_effect
            return hue_effect(args.get("effect", "colorloop"), args.get("light", "all"))
        if tool_name == "hue_wake_up":
            from tools.smarthome_tool import hue_wake_up
            return hue_wake_up(args.get("light", "all"), int(args.get("duration_minutes", 30)))
        if tool_name == "hue_fade_off":
            from tools.smarthome_tool import hue_fade_off
            return hue_fade_off(args.get("light", "all"), int(args.get("seconds", 1800)))
        if tool_name == "hue_save_state":
            from tools.smarthome_tool import hue_save_state
            return hue_save_state(args.get("name", "macro_snapshot"))
        if tool_name == "hue_restore_state":
            from tools.smarthome_tool import hue_restore_state
            return hue_restore_state(args.get("name", "macro_snapshot"))
        if tool_name == "list_hue_lights":
            from tools.smarthome_tool import list_hue_lights
            return list_hue_lights()
        if tool_name == "list_hue_groups":
            from tools.smarthome_tool import list_hue_groups
            return list_hue_groups()

        # ── Hue — groups/rooms ────────────────────────────────────────────
        if tool_name == "hue_group_on":
            from tools.smarthome_tool import hue_group_on
            return hue_group_on(args.get("group", "all"))
        if tool_name == "hue_group_off":
            from tools.smarthome_tool import hue_group_off
            return hue_group_off(args.get("group", "all"))
        if tool_name == "hue_group_brightness":
            from tools.smarthome_tool import hue_group_brightness
            return hue_group_brightness(int(args.get("level", 80)), args.get("group", "all"))
        if tool_name == "hue_group_scene":
            from tools.smarthome_tool import hue_group_scene
            return hue_group_scene(args.get("scene_name", "relax"), args.get("group", "all"))
        if tool_name == "hue_group_temperature":
            from tools.smarthome_tool import hue_group_temperature
            return hue_group_temperature(str(args.get("temp", "neutral")), args.get("group", "all"))

        # ── Kasa ─────────────────────────────────────────────────────────
        if tool_name == "kasa_on":
            from tools.smarthome_tool import kasa_on
            return kasa_on(args.get("device", ""))
        if tool_name == "kasa_off":
            from tools.smarthome_tool import kasa_off
            return kasa_off(args.get("device", ""))
        if tool_name == "kasa_toggle":
            from tools.smarthome_tool import kasa_toggle
            return kasa_toggle(args.get("device", ""))
        if tool_name == "kasa_status":
            from tools.smarthome_tool import kasa_status
            return kasa_status(args.get("device", ""))
        if tool_name == "smart_home_status":
            from tools.smarthome_tool import smart_home_status
            return smart_home_status()

        # ── Music ─────────────────────────────────────────────────────────
        if tool_name == "play_music":
            from tools.spotify_tool import play_music
            return play_music(args.get("query", ""))
        if tool_name == "pause_music":
            from tools.spotify_tool import pause_music
            return pause_music()
        if tool_name == "next_track":
            from tools.spotify_tool import next_track
            return next_track()
        if tool_name == "what_playing":
            from tools.spotify_tool import what_playing
            return what_playing()
        if tool_name == "set_volume":
            from tools.spotify_tool import set_volume
            return set_volume(int(args.get("level", 50)))

        # ── Focus / Pomodoro ──────────────────────────────────────────────
        if tool_name == "enable_focus_mode":
            from tools.focus_tool import enable_focus_mode
            return enable_focus_mode(float(args.get("hours", 2)))
        if tool_name == "disable_focus_mode":
            from tools.focus_tool import disable_focus_mode
            return disable_focus_mode()
        if tool_name == "start_pomodoro":
            from tools.pomodoro_tool import start_pomodoro
            return start_pomodoro(int(args.get("minutes", 25)), args.get("label", "Focus"))
        if tool_name == "stop_pomodoro":
            from tools.pomodoro_tool import stop_pomodoro
            return stop_pomodoro()

        # ── Journal ───────────────────────────────────────────────────────
        if tool_name == "get_journal_stats":
            from tools.journal_tool import get_journal_stats
            return get_journal_stats()
        if tool_name == "journal_streak":
            from tools.journal_tool import journal_streak
            return journal_streak()
        if tool_name == "mood_summary":
            from tools.journal_tool import mood_summary
            return mood_summary(args.get("days", 7))
        if tool_name == "most_recent_entry":
            from tools.journal_tool import most_recent_entry
            return most_recent_entry()

        # ── Expenses ──────────────────────────────────────────────────────
        if tool_name == "get_expense_summary":
            from tools.expense_tool import get_expense_summary
            return get_expense_summary(args.get("period", "today"))
        if tool_name == "list_recent_expenses":
            from tools.expense_tool import list_recent_expenses
            return list_recent_expenses(args.get("n", 5))

        # ── News ──────────────────────────────────────────────────────────
        if tool_name == "get_news":
            from tools.news_tool import get_news
            return get_news(args.get("category", "world"), args.get("n", 5))
        if tool_name == "get_all_headlines":
            from tools.news_tool import get_all_headlines
            return get_all_headlines(args.get("n", 2))
        if tool_name == "search_news":
            from tools.news_tool import search_news
            return search_news(args.get("query", ""), args.get("n", 5))

        # ── Reminders ─────────────────────────────────────────────────────
        if tool_name == "set_reminder":
            from tools.reminder_tool import set_reminder
            return set_reminder(args.get("message", "Reminder"), int(args.get("minutes", 10)))

        # ── System controls ───────────────────────────────────────────────
        if tool_name == "set_system_volume":
            from tools.system_control_tool import set_system_volume
            return set_system_volume(int(args.get("level", 50)))
        if tool_name == "get_system_volume":
            from tools.system_control_tool import get_system_volume
            return get_system_volume()
        if tool_name == "mute_system":
            from tools.system_control_tool import mute_system
            return mute_system()
        if tool_name == "get_battery_status":
            from tools.system_control_tool import get_battery_status
            return get_battery_status()

        # ── Code execution ────────────────────────────────────────────────
        if tool_name == "run_python":
            from tools.code_tool import run_python
            return run_python(args.get("code", ""), args.get("timeout", 30))
        if tool_name == "run_powershell":
            from tools.code_tool import run_powershell
            return run_powershell(args.get("command", ""), args.get("timeout", 30))
        if tool_name == "execute_file":
            from tools.code_tool import execute_file
            return execute_file(args.get("path", ""), args.get("timeout", 60))

        # ── Analytics ────────────────────────────────────────────────────
        if tool_name == "weekly_report":
            from tools.analytics_tool import weekly_report
            return weekly_report()
        if tool_name == "spending_insights":
            from tools.analytics_tool import spending_insights
            return spending_insights(args.get("period", "week"))
        if tool_name == "productivity_insights":
            from tools.analytics_tool import productivity_insights
            return productivity_insights(args.get("period", "week"))
        if tool_name == "top_tools":
            from tools.analytics_tool import top_tools
            return top_tools(args.get("n", 5))

        # ── Nested macro ─────────────────────────────────────────────────
        if tool_name == "run_macro":
            return run_macro(args.get("name", ""), _depth=_depth + 1)

        return (
            f"[macro] '{tool_name}' not available in macro dispatch. "
            "Use create_macro with a supported tool name."
        )

    except Exception as e:
        return f"[macro] {tool_name} failed: {e}"


def _run_step(step: dict, _depth: int = 0) -> tuple[str, str, bool]:
    """
    Run one step (any type). Returns (marker, result_line, ok).
    """
    step_type = step.get("type")

    # ── speak step ──────────────────────────────────────────────────────
    if step_type == "speak":
        text = step.get("text", "")
        _macro_speak(text)
        return "OK", f"speak: {text[:60]}", True

    # ── wait step ───────────────────────────────────────────────────────
    if step_type == "wait":
        secs = float(step.get("seconds", 1))
        time.sleep(secs)
        return "OK", f"wait: {secs}s", True

    # ── notify step ─────────────────────────────────────────────────────
    if step_type == "notify":
        _macro_notify(step.get("title", "El Fager"), step.get("message", ""))
        return "OK", f"notify: {step.get('title', '')}", True

    # ── tool step ───────────────────────────────────────────────────────
    tool_name = step.get("tool", "")
    args      = step.get("args", {})
    result    = _dispatch_macro_step(tool_name, args, _depth=_depth)
    is_error  = result.startswith("[macro]")
    preview   = result.split("\n")[0][:120]
    return ("FAIL" if is_error else "OK"), f"{tool_name}: {preview}", not is_error


# ──────────────────────────────────────────────────────────────────────────────
# Public tool functions
# ──────────────────────────────────────────────────────────────────────────────

def create_macro(name: str, steps: list[dict], description: str = "", tags: list[str] | None = None) -> str:
    """
    Create or replace a custom macro.

    steps: list of step dicts. Each must have either:
      - "tool" key  → tool call, e.g. {"tool": "get_weather", "args": {"city": "Cairo"}}
      - "type" key  → speak/wait/notify, e.g. {"type": "speak", "text": "Hello!"}
    """
    if not steps:
        return "Steps list is empty — provide at least one step."

    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            return f"Step {i} must be a dict. Got: {step!r}"
        if "tool" not in step and "type" not in step:
            return f"Step {i} missing 'tool' or 'type' key. Got: {step!r}"
        if step.get("type") and step["type"] not in ("speak", "wait", "notify"):
            return f"Step {i}: unknown type '{step['type']}'. Valid: speak, wait, notify."

    macros   = _load_macros()
    existing = _find_macro(name, macros)
    if existing and existing.get("builtin"):
        return (
            f"'{name}' is a built-in macro. Use clone_macro to create a custom copy first."
        )

    macros = [m for m in macros if m["name"].lower() != name.lower()]
    macros.append({
        "name":        name,
        "description": description,
        "tags":        tags or [],
        "builtin":     False,
        "steps":       steps,
        "created_at":  datetime.now().isoformat(),
    })
    _save_macros(macros)
    return f"Macro '{name}' saved with {len(steps)} step(s)."


def run_macro(name: str, _depth: int = 0) -> str:
    """
    Run a named macro — executes all steps in sequence.
    Speak steps are voiced mid-run. Returns structured [OK]/[FAIL] report.
    """
    if _depth >= _MAX_RECURSION_DEPTH:
        return f"[macro] Recursion limit reached — cannot run '{name}' from within itself."

    macros = _load_macros()
    match  = _find_macro(name, macros)
    if not match:
        available = ", ".join(m["name"] for m in macros)
        return f"No macro named '{name}'. Available: {available}"

    steps    = match.get("steps", [])
    lines    = []
    ok = fail = 0

    for step in steps:
        marker, line, success = _run_step(step, _depth=_depth)
        lines.append(f"  [{marker}] {line}")
        if success:
            ok += 1
        else:
            fail += 1

    _record_run(name)

    total   = ok + fail
    summary = f"{match['name']} — {ok}/{total} steps OK" + (f", {fail} failed" if fail else "")
    return summary + "\n" + "\n".join(lines)


def list_macros(tag: str | None = None) -> str:
    """
    List all macros. Optionally filter by tag.
    Includes last_run and run_count from stats.
    """
    macros = _load_macros()
    stats  = _load_stats()

    if tag:
        macros = [m for m in macros if tag.lower() in [t.lower() for t in m.get("tags", [])]]
        if not macros:
            return f"No macros with tag '{tag}'."

    builtins = [m for m in macros if m.get("builtin")]
    customs  = [m for m in macros if not m.get("builtin")]

    def _format_macro(m: dict) -> str:
        s          = stats.get(m["name"], {})
        run_count  = s.get("run_count", 0)
        last_run   = s.get("last_run", "never")[:10] if s.get("last_run") else "never"
        tags_str   = f" [{', '.join(m['tags'])}]" if m.get("tags") else ""
        desc_str   = f" — {m['description']}" if m.get("description") else ""
        runs_str   = f" (run {run_count}x, last: {last_run})" if run_count else ""
        return f"    • {m['name']}{tags_str}: {len(m['steps'])} steps{desc_str}{runs_str}"

    label = f" (tag: {tag})" if tag else ""
    lines = [f"{len(macros)} macro(s){label} ({len(builtins)} built-in, {len(customs)} custom):"]

    if builtins:
        lines.append("  Built-in:")
        for m in builtins:
            lines.append(_format_macro(m))
    if customs:
        lines.append("  Custom:")
        for m in customs:
            lines.append(_format_macro(m))
    return "\n".join(lines)


def get_macro(name: str) -> str:
    macros = _load_macros()
    match  = _find_macro(name, macros)
    if not match:
        return f"No macro named '{name}'."

    stats     = _load_stats().get(name, {})
    run_count = stats.get("run_count", 0)
    last_run  = stats.get("last_run", "never")[:16] if stats.get("last_run") else "never"

    lines = [f"Macro: {match['name']}" + (" [built-in]" if match.get("builtin") else " [custom]")]
    if match.get("description"):
        lines.append(f"  {match['description']}")
    if match.get("tags"):
        lines.append(f"  Tags: {', '.join(match['tags'])}")
    if match.get("voice_triggers"):
        lines.append(f"  Triggers: \"{'\", \"'.join(match['voice_triggers'][:4])}\"")
    lines.append(f"  Runs: {run_count}x — last: {last_run}")
    lines.append(f"Steps ({len(match['steps'])}):")
    for i, step in enumerate(match["steps"], 1):
        s_type = step.get("type")
        if s_type == "speak":
            lines.append(f"  {i}. [speak] \"{step.get('text', '')}\"")
        elif s_type == "wait":
            lines.append(f"  {i}. [wait] {step.get('seconds', 1)}s")
        elif s_type == "notify":
            lines.append(f"  {i}. [notify] {step.get('title', '')} — {step.get('message', '')[:60]}")
        else:
            args_str = ", ".join(f"{k}={v!r}" for k, v in step.get("args", {}).items())
            lines.append(f"  {i}. {step['tool']}({args_str})")
    return "\n".join(lines)


def delete_macro(name: str) -> str:
    macros = _load_macros()
    match  = _find_macro(name, macros)
    if not match:
        return f"No macro named '{name}'."
    if match.get("builtin"):
        return f"'{name}' is built-in and can't be deleted. Use clone_macro to create a custom copy."
    macros = [m for m in macros if m["name"].lower() != name.lower()]
    _save_macros(macros)
    return f"Macro '{name}' deleted."


def clone_macro(source: str, new_name: str) -> str:
    """Copy any macro (including built-ins) under a new name for customisation."""
    import copy
    macros = _load_macros()
    match  = _find_macro(source, macros)
    if not match:
        return f"No macro named '{source}'."
    if _find_macro(new_name, macros):
        return f"A macro named '{new_name}' already exists. Delete it first."
    clone               = copy.deepcopy(match)
    clone["name"]       = new_name
    clone["builtin"]    = False
    clone["created_at"] = datetime.now().isoformat()
    clone["voice_triggers"] = []
    clone["description"] = (
        (clone.get("description", "") + f" (clone of {source})").strip()
    )
    macros.append(clone)
    _save_macros(macros)
    return (
        f"Cloned '{source}' -> '{new_name}' with {len(clone['steps'])} steps. "
        "Use add_step, remove_step, or edit_macro to customise it."
    )


def edit_macro(name: str, step_index: int, tool: str | None = None,
               args: dict | None = None, step_type: str | None = None,
               text: str | None = None, seconds: float | None = None,
               title: str | None = None, message: str | None = None) -> str:
    """
    Replace one step (1-based index) in a custom macro.

    For a tool step:   provide tool + optional args.
    For a speak step:  provide step_type="speak" + text.
    For a wait step:   provide step_type="wait"  + seconds.
    For a notify step: provide step_type="notify" + title + message.
    """
    macros = _load_macros()
    match  = _find_macro(name, macros)
    if not match:
        return f"No macro named '{name}'."
    if match.get("builtin"):
        return f"'{name}' is built-in. Clone it first with clone_macro, then edit the copy."

    steps = match.get("steps", [])
    if not (1 <= step_index <= len(steps)):
        return f"Step {step_index} out of range (macro has {len(steps)} steps)."

    if step_type == "speak":
        new_step = {"type": "speak", "text": text or ""}
    elif step_type == "wait":
        new_step = {"type": "wait", "seconds": seconds or 1}
    elif step_type == "notify":
        new_step = {"type": "notify", "title": title or "El Fager", "message": message or ""}
    else:
        if not tool:
            return "Provide 'tool' for a tool step, or 'step_type' for speak/wait/notify."
        new_step = {"tool": tool, "args": args or {}}

    steps[step_index - 1] = new_step
    _save_macros(macros)
    return f"Step {step_index} of '{name}' updated."


def add_step(name: str, tool: str | None = None, args: dict | None = None,
             position: int | None = None, step_type: str | None = None,
             text: str | None = None, seconds: float | None = None,
             title: str | None = None, message: str | None = None) -> str:
    """
    Add a step to a custom macro. Supply 'tool' for a tool step or 'step_type'
    for speak/wait/notify. position is 1-based; omit to append.
    """
    macros = _load_macros()
    match  = _find_macro(name, macros)
    if not match:
        return f"No macro named '{name}'."
    if match.get("builtin"):
        return f"'{name}' is built-in. Clone it first with clone_macro."

    if step_type == "speak":
        step = {"type": "speak", "text": text or ""}
    elif step_type == "wait":
        step = {"type": "wait", "seconds": seconds or 1}
    elif step_type == "notify":
        step = {"type": "notify", "title": title or "El Fager", "message": message or ""}
    else:
        if not tool:
            return "Provide 'tool' or 'step_type' (speak/wait/notify)."
        step = {"tool": tool, "args": args or {}}

    steps = match.get("steps", [])
    if position is None or position > len(steps):
        steps.append(step)
        pos_label = f"end (step {len(steps)})"
    else:
        idx = max(0, position - 1)
        steps.insert(idx, step)
        pos_label = f"position {position}"

    _save_macros(macros)
    return f"Added step at {pos_label} in '{name}'. {len(steps)} steps total."


def remove_step(name: str, step_index: int) -> str:
    """Remove one step (1-based index) from a custom macro."""
    macros = _load_macros()
    match  = _find_macro(name, macros)
    if not match:
        return f"No macro named '{name}'."
    if match.get("builtin"):
        return f"'{name}' is built-in. Clone it first."

    steps = match.get("steps", [])
    if not (1 <= step_index <= len(steps)):
        return f"Step {step_index} out of range ({len(steps)} steps)."

    removed = steps.pop(step_index - 1)
    label = removed.get("type") or removed.get("tool", "?")
    _save_macros(macros)
    return f"Removed step {step_index} ({label}) from '{name}'. {len(steps)} steps remaining."


def macro_stats() -> str:
    """Show run history — how many times each macro was run and when."""
    stats  = _load_stats()
    macros = _load_macros()
    if not stats:
        return "No macro runs recorded yet."

    lines  = [f"Macro run history ({len(stats)} macros run):"]
    sorted_stats = sorted(stats.items(), key=lambda x: x[1].get("run_count", 0), reverse=True)
    for macro_name, s in sorted_stats:
        run_count = s.get("run_count", 0)
        last_run  = s.get("last_run", "?")[:16] if s.get("last_run") else "?"
        lines.append(f"  • {macro_name}: {run_count}x (last: {last_run})")
    return "\n".join(lines)


def find_macro_by_trigger(phrase: str) -> str | None:
    """
    Find a macro whose voice_triggers match the given phrase.
    Prefers exact match, then trigger-is-substring-of-phrase.
    Returns macro name or None.
    """
    phrase_lower = phrase.lower().strip()
    macros       = _load_macros()
    # 1. Exact match
    for macro in macros:
        for trigger in macro.get("voice_triggers", []):
            if trigger.lower() == phrase_lower:
                return macro["name"]
    # 2. Trigger appears within what Mo said
    for macro in macros:
        for trigger in macro.get("voice_triggers", []):
            if trigger.lower() in phrase_lower:
                return macro["name"]
    return None
