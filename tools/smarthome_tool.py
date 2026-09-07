"""
Smart home tool — Phase 6G (Enhanced).

Philips Hue: direct bridge REST API via httpx (no pip package needed).
TP-Link Kasa: python-kasa library (pip install python-kasa).

Setup in .env:
  HUE_BRIDGE_IP=192.168.x.x
  HUE_USERNAME=abc123...           # from bridge button-press pairing
  KASA_DEVICE_IPS=192.168.x.x,192.168.x.y   # comma-separated IPs

Hue functions (25):
  list_hue_lights, list_hue_groups, hue_on, hue_off, hue_toggle,
  hue_brightness, hue_color, hue_temperature, hue_scene,
  hue_alert, hue_effect, hue_status, hue_group_on, hue_group_off,
  hue_group_brightness, hue_group_color, hue_group_temperature, hue_group_scene,
  hue_fade, hue_fade_off, hue_wake_up, hue_cancel_wake_up,
  hue_list_sensors, hue_save_state, hue_restore_state, hue_list_states

Kasa functions (8):
  kasa_list_devices, kasa_on, kasa_off, kasa_toggle,
  kasa_status, kasa_power_usage, kasa_energy_today, kasa_energy_month

Global functions (1):
  smart_home_status
"""

import asyncio
import json
import os
import threading
from pathlib import Path

import httpx
from dotenv import load_dotenv
from core import atomic
load_dotenv()

_HUE_IP   = os.getenv("HUE_BRIDGE_IP",   "").strip()
_HUE_USER = os.getenv("HUE_USERNAME",    "").strip()
_KASA_IPS = [ip.strip() for ip in os.getenv("KASA_DEVICE_IPS", "").split(",") if ip.strip()]

_STATES_FILE = Path("data/smart_home_states.json")
_WAKE_TIMERS: dict[str, list[threading.Timer]] = {}

_HUE_NOT_SET = (
    "[Hue not set up — add HUE_BRIDGE_IP and HUE_USERNAME to .env. "
    "Find bridge IP at meethue.com/api/nupnp. "
    "Username: press bridge button, then POST to http://{ip}/api with body {\"devicetype\":\"elfager\"}.]"
)
_KASA_NOT_SET = (
    "[Kasa not set up — add KASA_DEVICE_IPS to .env (comma-separated IPs). "
    "Find IPs in the Kasa app: device > Settings > Device Info.]"
)

# ── Color & temperature tables ────────────────────────────────────────────────

# Named color → Hue API hue value (0–65535). -1 = white (no saturation)
_HUE_COLORS: dict[str, int] = {
    "red":     0,     "orange":  5000,  "yellow":  10000,
    "lime":    20000, "green":   25500, "teal":    33000,
    "cyan":    35000, "sky":     40000, "blue":    46920,
    "indigo":  50000, "purple":  56100, "violet":  58000,
    "pink":    60000, "magenta": 62000, "white":   -1,
}

# Color temperature presets: name → mirek (153 = 6500K daylight, 500 = 2000K candle)
_HUE_TEMP_PRESETS: dict[str, int] = {
    "candle":   500,   # 2000K — warmest, most amber
    "warm":     370,   # 2700K — incandescent feel
    "soft":     370,   # alias
    "cozy":     370,   # alias
    "neutral":  250,   # 4000K — balanced white
    "cool":     182,   # 5500K — crisp, alert
    "daylight": 153,   # 6500K — brightest/coolest
    "reading":  250,   # 4000K — easy on eyes
    "focus":    182,   # 5500K — productive, alert
    "morning":  300,   # 3300K — gentle start to day
    "evening":  400,   # 2500K — wind-down warmth
}

# Mood/scene presets → Hue state dict (bri: 1–254, ct: mirek, hue: 0–65535, sat: 0–254)
_HUE_SCENES: dict[str, dict] = {
    "movie":    {"on": True, "bri": 77,  "ct": 370, "sat": 0},
    "cinema":   {"on": True, "bri": 50,  "ct": 400, "sat": 0},
    "reading":  {"on": True, "bri": 220, "ct": 250, "sat": 0},
    "focus":    {"on": True, "bri": 254, "ct": 182, "sat": 0},
    "energize": {"on": True, "bri": 254, "ct": 153, "sat": 0},
    "relax":    {"on": True, "bri": 144, "ct": 370, "sat": 0},
    "sleep":    {"on": True, "bri": 15,  "ct": 500, "sat": 0},
    "night":    {"on": True, "bri": 40,  "ct": 500, "sat": 0},
    "morning":  {"on": True, "bri": 180, "ct": 300, "sat": 0},
    "dinner":   {"on": True, "bri": 144, "ct": 400, "sat": 15},
    "romantic": {"on": True, "hue": 0,   "sat": 200, "bri": 50},
    "sunset":   {"on": True, "hue": 5000,"sat": 200, "bri": 150},
    "party":    {"on": True, "hue": 46920,"sat": 254,"bri": 254},
    "bright":   {"on": True, "bri": 254, "ct": 250, "sat": 0},
    "dim":      {"on": True, "bri": 50,  "ct": 370, "sat": 0},
    "study":    {"on": True, "bri": 240, "ct": 220, "sat": 0},
    "workout":  {"on": True, "bri": 254, "ct": 153, "sat": 0},
    "gaming":   {"on": True, "hue": 46920,"sat": 200,"bri": 150},
    "chill":    {"on": True, "bri": 100, "ct": 400, "sat": 0},
    "off":      {"on": False},
}

# Hue sensor type labels
_SENSOR_TYPES = {
    "ZLLPresence":   "Motion",
    "ZLLTemperature":"Temperature",
    "ZLLLightLevel": "Light level",
    "ZLLSwitch":     "Dimmer switch",
    "ZGPSwitch":     "Tap switch",
    "Daylight":      "Daylight",
    "CLIPPresence":  "Software motion",
}


# ── Hue helpers ───────────────────────────────────────────────────────────────

def _hue_available() -> bool:
    return bool(_HUE_IP and _HUE_USER)


def _hue_base() -> str:
    return f"http://{_HUE_IP}/api/{_HUE_USER}"


def _hue_get(path: str) -> dict:
    resp = httpx.get(f"{_hue_base()}{path}", timeout=5)
    resp.raise_for_status()
    return resp.json()


def _hue_put(path: str, body: dict) -> list:
    resp = httpx.put(f"{_hue_base()}{path}", json=body, timeout=5)
    resp.raise_for_status()
    return resp.json()


def _light_ids(name_or_id: str, lights: dict) -> list[str]:
    """Resolve 'all', a name substring, or a numeric ID → list of light IDs."""
    if name_or_id.lower() == "all":
        return list(lights.keys())
    if name_or_id in lights:
        return [name_or_id]
    name_lower = name_or_id.lower()
    return [lid for lid, l in lights.items() if name_lower in l.get("name", "").lower()]


def _group_ids(name_or_id: str, groups: dict) -> list[str]:
    """Resolve a group name substring or numeric ID → list of group IDs."""
    if name_or_id.lower() == "all":
        return list(groups.keys())
    if name_or_id in groups:
        return [name_or_id]
    name_lower = name_or_id.lower()
    return [gid for gid, g in groups.items() if name_lower in g.get("name", "").lower()]


def _bri_pct(bri: int) -> int:
    return int(bri / 2.54)


def _pct_bri(pct: int) -> int:
    return max(1, int(max(0, min(100, pct)) * 2.54))


def _light_names(ids: list[str], lights: dict) -> str:
    names = [lights[lid]["name"] for lid in ids if lid in lights]
    return ", ".join(names) if names else "selected lights"


def _kelvin_to_mirek(k: int) -> int:
    return max(153, min(500, int(1_000_000 / k)))


def _resolve_temp(temp_str: str) -> tuple[int, str] | tuple[None, str]:
    """Return (mirek, label) or (None, error_message)."""
    key = temp_str.lower().strip()
    if key in _HUE_TEMP_PRESETS:
        return _HUE_TEMP_PRESETS[key], key
    try:
        k = int(key.rstrip("k"))
        return _kelvin_to_mirek(k), f"{k}K"
    except ValueError:
        presets = ", ".join(_HUE_TEMP_PRESETS)
        return None, f"Unknown temperature '{temp_str}'. Use a preset ({presets}) or a Kelvin value like '3000'."


def _load_states() -> dict:
    if _STATES_FILE.exists():
        try:
            return json.loads(_STATES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_states(data: dict) -> None:
    _STATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic.write(_STATES_FILE, json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _cancel_wake_timers(key: str) -> None:
    for t in _WAKE_TIMERS.pop(key, []):
        t.cancel()


# ── Hue: individual light controls ───────────────────────────────────────────

def list_hue_lights() -> str:
    """List all Philips Hue lights with name, state, brightness, and color temperature."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        lights = _hue_get("/lights")
        if not lights:
            return "No Hue lights found — check bridge pairing."
        lines = [f"Hue lights ({len(lights)} total):\n"]
        on_count = sum(1 for l in lights.values() if l.get("state", {}).get("on"))
        lines[0] = f"Hue lights ({on_count} on, {len(lights)-on_count} off):\n"
        for lid, light in lights.items():
            name  = light.get("name", f"Light {lid}")
            state = light.get("state", {})
            on    = "ON" if state.get("on") else "off"
            bri   = _bri_pct(state.get("bri", 0))
            reach = "" if state.get("reachable", True) else " [unreachable]"
            ct    = state.get("ct")
            eff   = state.get("effect", "none")
            extra = ""
            if ct:
                extra = f", ~{int(1_000_000/ct)}K"
            if eff != "none":
                extra += f", {eff}"
            lines.append(f"  {lid}. {name}: {on}, {bri}%{extra}{reach}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Hue error: {e}]"


def list_hue_groups() -> str:
    """List all Philips Hue rooms, zones, and groups."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        groups = _hue_get("/groups")
        if not groups:
            return "No Hue groups found."
        lines = [f"Hue groups/rooms ({len(groups)}):\n"]
        for gid, group in groups.items():
            name   = group.get("name", f"Group {gid}")
            gtype  = group.get("type", "")
            action = group.get("action", {})
            any_on = group.get("state", {}).get("any_on", False)
            all_on = group.get("state", {}).get("all_on", False)
            n_lights = len(group.get("lights", []))
            bri    = _bri_pct(action.get("bri", 0))
            ct     = action.get("ct")
            status = "ALL ON" if all_on else ("SOME ON" if any_on else "off")
            ct_str = f", ~{int(1_000_000/ct)}K" if ct else ""
            lines.append(f"  {gid}. [{gtype}] {name}: {status}, {bri}%{ct_str}, {n_lights} light(s)")
        return "\n".join(lines)
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_on(light: str = "all") -> str:
    """Turn Hue light(s) on."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        for lid in ids:
            _hue_put(f"/lights/{lid}/state", {"on": True})
        return f"Turned on: {_light_names(ids, lights)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_off(light: str = "all") -> str:
    """Turn Hue light(s) off."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        for lid in ids:
            _hue_put(f"/lights/{lid}/state", {"on": False})
        return f"Turned off: {_light_names(ids, lights)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_toggle(light: str = "all") -> str:
    """Toggle Hue light(s) — on if off, off if on."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        results = []
        for lid in ids:
            current = lights.get(lid, {}).get("state", {}).get("on", False)
            new_state = not current
            _hue_put(f"/lights/{lid}/state", {"on": new_state})
            name = lights.get(lid, {}).get("name", lid)
            results.append(f"{name}: {'ON' if new_state else 'off'}")
        return "Toggled: " + ", ".join(results)
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_brightness(level: int, light: str = "all") -> str:
    """Set Hue light(s) brightness 0–100%."""
    if not _hue_available():
        return _HUE_NOT_SET
    level = max(0, min(100, int(level)))
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        state = {"on": level > 0, "bri": _pct_bri(level)} if level > 0 else {"on": False}
        for lid in ids:
            _hue_put(f"/lights/{lid}/state", state)
        return f"Brightness set to {level}% — {_light_names(ids, lights)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_color(color: str, light: str = "all") -> str:
    """
    Set Hue light(s) color. Named colors preserve current brightness.
    Colors: red, orange, yellow, lime, green, teal, cyan, sky, blue,
            indigo, purple, violet, pink, magenta, white.
    Also accepts hex codes like #FF0000.
    """
    if not _hue_available():
        return _HUE_NOT_SET

    color_str = color.strip()

    # Hex color support (#RRGGBB or RRGGBB)
    hex_str = color_str.lstrip("#")
    if len(hex_str) == 6 and all(c in "0123456789abcdefABCDEF" for c in hex_str):
        r = int(hex_str[0:2], 16) / 255
        g = int(hex_str[2:4], 16) / 255
        b = int(hex_str[4:6], 16) / 255
        # RGB → XY (wide color gamut approximation)
        r2 = pow(r, 2.2) if r > 0.04045 else r / 12.92
        g2 = pow(g, 2.2) if g > 0.04045 else g / 12.92
        b2 = pow(b, 2.2) if b > 0.04045 else b / 12.92
        X = r2 * 0.664511 + g2 * 0.154324 + b2 * 0.162028
        Y = r2 * 0.283881 + g2 * 0.668433 + b2 * 0.047685
        Z = r2 * 0.000088 + g2 * 0.072310 + b2 * 0.986039
        total = X + Y + Z or 1
        xy = [round(X / total, 4), round(Y / total, 4)]
        try:
            lights = _hue_get("/lights")
            ids = _light_ids(light, lights)
            if not ids:
                return f"No light found matching '{light}'."
            avg_bri = int(sum(lights.get(lid, {}).get("state", {}).get("bri", 200) for lid in ids) / len(ids))
            state = {"on": True, "xy": xy, "bri": max(100, avg_bri)}
            for lid in ids:
                _hue_put(f"/lights/{lid}/state", state)
            return f"Lights set to #{hex_str}"
        except Exception as e:
            return f"[Hue error: {e}]"

    # Named color
    color_key = color_str.lower()
    if color_key not in _HUE_COLORS:
        return (
            f"Unknown color '{color}'. "
            f"Named colors: {', '.join(_HUE_COLORS)}. "
            "Or pass a hex code like #FF6600."
        )
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."

        hue_val = _HUE_COLORS[color_key]
        if hue_val == -1:
            state = {"on": True, "sat": 0, "bri": 254}
        else:
            avg_bri = int(sum(lights.get(lid, {}).get("state", {}).get("bri", 200) for lid in ids) / len(ids))
            state = {"on": True, "hue": hue_val, "sat": 254, "bri": max(100, avg_bri)}

        for lid in ids:
            _hue_put(f"/lights/{lid}/state", state)
        return f"Lights set to {color_key}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_temperature(temp: str, light: str = "all") -> str:
    """
    Set white color temperature of Hue light(s).
    Presets: candle, warm, soft, cozy, morning, neutral, reading, evening, cool, focus, daylight.
    Or pass a Kelvin value like '3000'.
    Preserves current brightness.
    """
    if not _hue_available():
        return _HUE_NOT_SET
    ct, label = _resolve_temp(str(temp))
    if ct is None:
        return label  # error message
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        for lid in ids:
            current_bri = lights.get(lid, {}).get("state", {}).get("bri", 200)
            _hue_put(f"/lights/{lid}/state", {"on": True, "ct": ct, "sat": 0, "bri": current_bri})
        return f"Color temperature set to {label} — {_light_names(ids, lights)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_scene(scene_name: str, light: str = "all") -> str:
    """
    Apply a built-in mood preset to Hue lights.
    Scenes: movie, cinema, reading, study, focus, energize, workout, gaming,
            relax, chill, sleep, night, morning, dinner, romantic, sunset, party, bright, dim, off.
    """
    if not _hue_available():
        return _HUE_NOT_SET
    key = scene_name.lower().strip()
    if key not in _HUE_SCENES:
        return f"Unknown scene '{scene_name}'. Available: {', '.join(_HUE_SCENES)}"
    state = _HUE_SCENES[key].copy()
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        for lid in ids:
            _hue_put(f"/lights/{lid}/state", state)
        return f"Scene '{key}' activated — {_light_names(ids, lights)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_alert(light: str = "all", mode: str = "short") -> str:
    """
    Flash Hue light(s) to locate or get attention.
    mode — 'short' (one flash) | 'long' (15 sec) | 'stop'
    """
    if not _hue_available():
        return _HUE_NOT_SET
    alert_map = {"short": "select", "long": "lselect", "stop": "none"}
    alert_val = alert_map.get(mode.lower(), "select")
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        for lid in ids:
            _hue_put(f"/lights/{lid}/state", {"alert": alert_val})
        target = _light_names(ids, lights)
        if alert_val == "none":
            return f"Alert stopped: {target}"
        duration = "15 seconds" if alert_val == "lselect" else "once"
        return f"Flashing {target} ({duration})"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_effect(effect: str = "colorloop", light: str = "all") -> str:
    """
    Apply a dynamic effect.
    effect — 'colorloop' / 'loop' / 'cycle' | 'none' / 'stop'
    """
    if not _hue_available():
        return _HUE_NOT_SET
    effect_val = "colorloop" if effect.lower().strip() in ("colorloop", "loop", "cycle") else "none"
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        for lid in ids:
            state = {"effect": effect_val}
            if effect_val == "colorloop":
                state["on"] = True
            _hue_put(f"/lights/{lid}/state", state)
        target = _light_names(ids, lights)
        return f"Colorloop {'started' if effect_val == 'colorloop' else 'stopped'}: {target}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_status(light: str) -> str:
    """Get detailed current state of a specific Hue light."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."
        lines = []
        for lid in ids[:4]:
            l     = lights.get(lid, {})
            name  = l.get("name", lid)
            ltype = l.get("type", "")
            model = l.get("modelid", "")
            state = l.get("state", {})
            on    = "ON" if state.get("on") else "OFF"
            bri   = _bri_pct(state.get("bri", 0))
            reach = state.get("reachable", True)
            ct    = state.get("ct")
            hue_v = state.get("hue")
            sat   = state.get("sat", 0)
            eff   = state.get("effect", "none")
            info  = [f"{name} (ID {lid}):"]
            info.append(f"  State: {on}, brightness {bri}%")
            if ct:
                info.append(f"  Color temp: ~{int(1_000_000/ct)}K")
            elif hue_v is not None:
                best = min(_HUE_COLORS, key=lambda c: abs(_HUE_COLORS[c] - hue_v) if _HUE_COLORS[c] >= 0 else 99999)
                info.append(f"  Color: ~{best} (hue {hue_v}, saturation {sat})")
            if eff != "none":
                info.append(f"  Effect: {eff}")
            if model:
                info.append(f"  Model: {model} ({ltype})")
            if not reach:
                info.append("  [UNREACHABLE] - check power/connection")
            lines.append("\n".join(info))
        return "\n\n".join(lines)
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_group_on(group: str = "all") -> str:
    """Turn a Hue room or zone on."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        groups = _hue_get("/groups")
        ids = _group_ids(group, groups)
        if not ids:
            return f"No group found matching '{group}'. Say 'list hue groups'."
        for gid in ids:
            _hue_put(f"/groups/{gid}/action", {"on": True})
        names = [groups[gid]["name"] for gid in ids if gid in groups]
        return f"Turned on: {', '.join(names)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_group_off(group: str = "all") -> str:
    """Turn a Hue room or zone off."""
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        groups = _hue_get("/groups")
        ids = _group_ids(group, groups)
        if not ids:
            return f"No group found matching '{group}'. Say 'list hue groups'."
        for gid in ids:
            _hue_put(f"/groups/{gid}/action", {"on": False})
        names = [groups[gid]["name"] for gid in ids if gid in groups]
        return f"Turned off: {', '.join(names)}"
    except Exception as e:
        return f"[Hue error: {e}]"


# ── Hue: room/group-level controls ───────────────────────────────────────────

def hue_group_brightness(level: int, group: str = "all") -> str:
    """Set brightness for an entire Hue room or zone in one API call."""
    if not _hue_available():
        return _HUE_NOT_SET
    level = max(0, min(100, int(level)))
    try:
        groups = _hue_get("/groups")
        ids = _group_ids(group, groups)
        if not ids:
            return f"No group found matching '{group}'. Say 'list hue groups'."
        action = {"on": level > 0, "bri": _pct_bri(level)} if level > 0 else {"on": False}
        for gid in ids:
            _hue_put(f"/groups/{gid}/action", action)
        names = [groups[gid]["name"] for gid in ids if gid in groups]
        return f"Brightness set to {level}% — {', '.join(names)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_group_color(color: str, group: str = "all") -> str:
    """Set the color for an entire Hue room or zone. Same color palette as hue_color."""
    if not _hue_available():
        return _HUE_NOT_SET
    color_key = color.lower().strip()
    if color_key not in _HUE_COLORS:
        return f"Unknown color '{color}'. Available: {', '.join(_HUE_COLORS)}"
    hue_val = _HUE_COLORS[color_key]
    action = {"on": True, "sat": 0, "bri": 254} if hue_val == -1 else {"on": True, "hue": hue_val, "sat": 254}
    try:
        groups = _hue_get("/groups")
        ids = _group_ids(group, groups)
        if not ids:
            return f"No group found matching '{group}'. Say 'list hue groups'."
        for gid in ids:
            _hue_put(f"/groups/{gid}/action", action)
        names = [groups[gid]["name"] for gid in ids if gid in groups]
        return f"Set {', '.join(names)} to {color_key}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_group_temperature(temp: str, group: str = "all") -> str:
    """Set white color temperature for an entire Hue room or zone."""
    if not _hue_available():
        return _HUE_NOT_SET
    ct, label = _resolve_temp(str(temp))
    if ct is None:
        return label
    try:
        groups = _hue_get("/groups")
        ids = _group_ids(group, groups)
        if not ids:
            return f"No group found matching '{group}'. Say 'list hue groups'."
        for gid in ids:
            _hue_put(f"/groups/{gid}/action", {"on": True, "ct": ct, "sat": 0})
        names = [groups[gid]["name"] for gid in ids if gid in groups]
        return f"Color temperature set to {label} — {', '.join(names)}"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_group_scene(scene_name: str, group: str = "all") -> str:
    """Apply a mood preset to an entire Hue room or zone in one call."""
    if not _hue_available():
        return _HUE_NOT_SET
    key = scene_name.lower().strip()
    if key not in _HUE_SCENES:
        return f"Unknown scene '{scene_name}'. Available: {', '.join(_HUE_SCENES)}"
    state = _HUE_SCENES[key].copy()
    try:
        groups = _hue_get("/groups")
        ids = _group_ids(group, groups)
        if not ids:
            return f"No group found matching '{group}'. Say 'list hue groups'."
        for gid in ids:
            _hue_put(f"/groups/{gid}/action", state)
        names = [groups[gid]["name"] for gid in ids if gid in groups]
        return f"Scene '{key}' applied to: {', '.join(names)}"
    except Exception as e:
        return f"[Hue error: {e}]"


# ── Hue: transitions ──────────────────────────────────────────────────────────

def hue_fade(target_brightness: int, light: str = "all", seconds: int = 10) -> str:
    """
    Smoothly fade Hue light(s) to a target brightness over N seconds.
    Uses the native Hue transitiontime parameter — no polling needed.
    target_brightness — 0–100%. seconds — transition duration (1–3600).
    """
    if not _hue_available():
        return _HUE_NOT_SET
    target = max(0, min(100, int(target_brightness)))
    seconds = max(1, min(3600, int(seconds)))
    transitiontime = seconds * 10  # Hue uses units of 100ms

    try:
        lights = _hue_get("/lights")
        ids = _light_ids(light, lights)
        if not ids:
            return f"No light found matching '{light}'. Say 'list hue lights'."

        if target == 0:
            state = {"on": False, "transitiontime": transitiontime}
        else:
            state = {"on": True, "bri": _pct_bri(target), "transitiontime": transitiontime}

        for lid in ids:
            _hue_put(f"/lights/{lid}/state", state)

        target_label = "off" if target == 0 else f"{target}%"
        return f"Fading {_light_names(ids, lights)} to {target_label} over {seconds}s"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_fade_off(light: str = "all", seconds: int = 30) -> str:
    """
    Gradually fade Hue light(s) to off over N seconds.
    Perfect as a sleep timer. Default: 30 seconds.
    """
    return hue_fade(0, light, seconds)


def hue_wake_up(light: str = "all", duration_minutes: int = 30) -> str:
    """
    Gradual sunrise simulation over N minutes.
    Starts at 1% warm candle light and smoothly brightens to 100% morning white.
    Runs as a background process — say 'cancel wake up' to stop.
    """
    if not _hue_available():
        return _HUE_NOT_SET

    duration_minutes = max(1, min(120, int(duration_minutes)))
    steps = 20
    interval_s = (duration_minutes * 60) / steps

    # Cancel any existing wake-up for this target
    _cancel_wake_timers(light)

    def step(n: int) -> None:
        pct = max(1, int((n / steps) * 100))
        bri = _pct_bri(pct)
        # Mirek: 500 (candle 2000K) → 300 (morning 3300K)
        ct  = int(500 - (n / steps) * 200)
        # Transition into this step smoothly
        transition = max(10, int(interval_s * 10))
        try:
            lights_data = _hue_get("/lights")
            ids = _light_ids(light, lights_data)
            for lid in ids:
                _hue_put(f"/lights/{lid}/state", {
                    "on": True, "bri": bri, "ct": ct, "sat": 0,
                    "transitiontime": transition,
                })
        except Exception:
            pass

    # Fire immediately at 1% warm (step 0 = initial state)
    try:
        lights_data = _hue_get("/lights")
        ids = _light_ids(light, lights_data)
        if not ids:
            return f"No light found matching '{light}'."
        for lid in ids:
            _hue_put(f"/lights/{lid}/state", {"on": True, "bri": 3, "ct": 500, "sat": 0, "transitiontime": 10})
    except Exception as e:
        return f"[Hue error: {e}]"

    timers = []
    for n in range(1, steps + 1):
        t = threading.Timer(n * interval_s, step, args=[n])
        t.daemon = True
        t.start()
        timers.append(t)

    _WAKE_TIMERS[light] = timers
    return (
        f"Sunrise simulation started — lights will brighten over {duration_minutes} min "
        f"({steps} steps, one every {interval_s:.0f}s). Say 'cancel wake up' to stop."
    )


def hue_cancel_wake_up(light: str = "all") -> str:
    """Cancel an in-progress wake-up / sunrise simulation."""
    if not _hue_available():
        return _HUE_NOT_SET
    if light in _WAKE_TIMERS:
        _cancel_wake_timers(light)
        return f"Wake-up simulation cancelled for '{light}'"
    if _WAKE_TIMERS:
        keys = list(_WAKE_TIMERS.keys())
        for k in keys:
            _cancel_wake_timers(k)
        return f"Cancelled all active wake-up simulations ({', '.join(keys)})"
    return "No active wake-up simulation found."


# ── Hue: state snapshots ──────────────────────────────────────────────────────

def hue_save_state(name: str) -> str:
    """
    Save the current state of all Hue lights as a named snapshot.
    Useful before changing scenes — save 'work' state to restore later.
    """
    if not _hue_available():
        return _HUE_NOT_SET
    name = name.strip()
    if not name:
        return "Please provide a name for the snapshot, e.g. 'evening setup'."
    try:
        lights = _hue_get("/lights")
        snapshot = {}
        for lid, l in lights.items():
            st = l.get("state", {})
            entry = {"on": st.get("on", False), "bri": st.get("bri", 254)}
            if st.get("ct"):
                entry["ct"] = st["ct"]
            if st.get("hue") is not None:
                entry["hue"] = st["hue"]
                entry["sat"] = st.get("sat", 0)
            snapshot[lid] = entry

        states = _load_states()
        from datetime import datetime
        states[name] = {"saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "lights": snapshot}
        _save_states(states)
        on_count = sum(1 for e in snapshot.values() if e.get("on"))
        return f"Saved state '{name}' — {len(snapshot)} lights ({on_count} were on)"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_restore_state(name: str) -> str:
    """Restore a previously saved Hue light snapshot by name."""
    if not _hue_available():
        return _HUE_NOT_SET
    name = name.strip()
    states = _load_states()
    if name not in states:
        saved = ", ".join(states) or "none"
        return f"No state saved as '{name}'. Saved states: {saved}"
    try:
        snapshot = states[name]["lights"]
        saved_at = states[name].get("saved_at", "unknown time")
        for lid, state in snapshot.items():
            _hue_put(f"/lights/{lid}/state", state)
        on_count = sum(1 for e in snapshot.values() if e.get("on"))
        return f"Restored state '{name}' (saved {saved_at}) — {len(snapshot)} lights ({on_count} on)"
    except Exception as e:
        return f"[Hue error: {e}]"


def hue_list_states() -> str:
    """List all saved Hue light state snapshots."""
    states = _load_states()
    if not states:
        return "No saved light states. Say 'save hue state [name]' to create one."
    lines = [f"Saved light states ({len(states)}):\n"]
    for name, data in states.items():
        saved_at = data.get("saved_at", "unknown")
        n_lights = len(data.get("lights", {}))
        on_count = sum(1 for e in data.get("lights", {}).values() if e.get("on"))
        lines.append(f"  • '{name}' — saved {saved_at}, {n_lights} lights ({on_count} on)")
    lines.append("\nSay 'restore [name]' to apply a state.")
    return "\n".join(lines)


# ── Hue: sensors ─────────────────────────────────────────────────────────────

def hue_list_sensors() -> str:
    """
    List all Philips Hue sensors: motion detectors, temperature sensors, light level sensors,
    dimmer switches, and tap switches.
    """
    if not _hue_available():
        return _HUE_NOT_SET
    try:
        sensors = _hue_get("/sensors")
        if not sensors:
            return "No Hue sensors found."

        by_type: dict[str, list[str]] = {}
        for sid, sensor in sensors.items():
            stype = sensor.get("type", "Unknown")
            label = _SENSOR_TYPES.get(stype, stype)
            name  = sensor.get("name", f"Sensor {sid}")
            st    = sensor.get("state", {})
            config = sensor.get("config", {})
            on    = config.get("on", True)
            reach = config.get("reachable", True)

            detail = ""
            if stype == "ZLLPresence":
                present = st.get("presence", False)
                detail = f"Motion: {'detected' if present else 'none'}"
            elif stype == "ZLLTemperature":
                temp_raw = st.get("temperature")
                if temp_raw is not None:
                    detail = f"Temp: {temp_raw / 100:.1f}°C"
            elif stype == "ZLLLightLevel":
                lux_raw = st.get("lightlevel")
                if lux_raw is not None:
                    lux = round(10 ** ((lux_raw - 1) / 10000), 1)
                    dark = st.get("dark", False)
                    detail = f"Light: {lux} lux {'(dark)' if dark else ''}"
            elif stype in ("ZLLSwitch", "ZGPSwitch"):
                btn = st.get("buttonevent")
                detail = f"Last button: {btn}" if btn else "No button press recorded"

            status_parts = []
            if not on:
                status_parts.append("disabled")
            if not reach and stype not in ("Daylight", "CLIPPresence"):
                status_parts.append("unreachable")
            status = f" [{', '.join(status_parts)}]" if status_parts else ""

            line = f"  {sid}. {name}: {detail}{status}" if detail else f"  {sid}. {name}{status}"
            by_type.setdefault(label, []).append(line)

        lines = [f"Hue sensors ({len(sensors)}):\n"]
        for label, items in sorted(by_type.items()):
            lines.append(f"  [{label}]")
            lines.extend(items)
        return "\n".join(lines)
    except Exception as e:
        return f"[Hue error: {e}]"


# ── Kasa helpers ──────────────────────────────────────────────────────────────

async def _kasa_connect(ip: str):
    try:
        from kasa import Device
        return await Device.connect(host=ip)
    except (ImportError, AttributeError):
        from kasa import SmartDevice
        device = SmartDevice(ip)
        await device.update()
        return device


async def _kasa_all_devices() -> list:
    results = []
    for ip in _KASA_IPS:
        try:
            dev = await _kasa_connect(ip)
            results.append((ip, dev))
        except Exception:
            pass
    return results


async def _kasa_find(name_or_ip: str):
    """Find a Kasa device by exact IP or alias substring. Returns (ip, device) or (None, None)."""
    if name_or_ip in _KASA_IPS:
        try:
            return name_or_ip, await _kasa_connect(name_or_ip)
        except Exception:
            return None, None
    for ip in _KASA_IPS:
        try:
            dev = await _kasa_connect(ip)
            if name_or_ip.lower() in (dev.alias or "").lower():
                return ip, dev
        except Exception:
            continue
    return None, None


# ── Kasa: device controls ─────────────────────────────────────────────────────

def kasa_list_devices() -> str:
    """List all configured TP-Link Kasa smart devices and their state."""
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        devices = asyncio.run(_kasa_all_devices())
        if not devices:
            return "No Kasa devices reachable — check KASA_DEVICE_IPS in .env and device power."
        on_count = sum(1 for _, dev in devices if dev.is_on)
        lines = [f"Kasa devices ({on_count} on, {len(devices)-on_count} off):\n"]
        for ip, dev in devices:
            state = "ON" if dev.is_on else "off"
            alias = dev.alias or ip
            model = getattr(dev, "model", "")
            model_str = f" [{model}]" if model else ""
            lines.append(f"  • {alias}{model_str} ({ip}): {state}")
        unreachable = len(_KASA_IPS) - len(devices)
        if unreachable:
            lines.append(f"\n  ({unreachable} device(s) unreachable)")
        return "\n".join(lines)
    except Exception as e:
        return f"[Kasa error: {e}]"


def kasa_on(device: str) -> str:
    """Turn a TP-Link Kasa device on by name or IP."""
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        async def _run():
            ip, dev = await _kasa_find(device)
            if dev is None:
                return f"Device '{device}' not found. Check KASA_DEVICE_IPS in .env."
            await dev.turn_on()
            return f"Turned on: {dev.alias or ip}"
        return asyncio.run(_run())
    except Exception as e:
        return f"[Kasa error: {e}]"


def kasa_off(device: str) -> str:
    """Turn a TP-Link Kasa device off by name or IP."""
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        async def _run():
            ip, dev = await _kasa_find(device)
            if dev is None:
                return f"Device '{device}' not found. Check KASA_DEVICE_IPS in .env."
            await dev.turn_off()
            return f"Turned off: {dev.alias or ip}"
        return asyncio.run(_run())
    except Exception as e:
        return f"[Kasa error: {e}]"


def kasa_toggle(device: str) -> str:
    """Toggle a TP-Link Kasa device on/off based on its current state."""
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        async def _run():
            ip, dev = await _kasa_find(device)
            if dev is None:
                return f"Device '{device}' not found. Check KASA_DEVICE_IPS in .env."
            if dev.is_on:
                await dev.turn_off()
                return f"Toggled OFF: {dev.alias or ip}"
            else:
                await dev.turn_on()
                return f"Toggled ON: {dev.alias or ip}"
        return asyncio.run(_run())
    except Exception as e:
        return f"[Kasa error: {e}]"


def kasa_status(device: str) -> str:
    """Get detailed status of a single TP-Link Kasa device."""
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        async def _run():
            ip, dev = await _kasa_find(device)
            if dev is None:
                return f"Device '{device}' not found. Check KASA_DEVICE_IPS in .env."
            alias = dev.alias or ip
            state = "ON" if dev.is_on else "OFF"
            model = getattr(dev, "model", "unknown")
            hw    = getattr(dev, "hw_info", {})
            fw    = hw.get("sw_ver", "")
            lines = [
                f"{alias} ({ip}):",
                f"  State: {state}",
                f"  Model: {model}",
            ]
            if fw:
                lines.append(f"  Firmware: {fw}")
            return "\n".join(lines)
        return asyncio.run(_run())
    except Exception as e:
        return f"[Kasa error: {e}]"


def kasa_power_usage(device: str) -> str:
    """
    Get real-time power consumption (watts, voltage, current).
    Only supported on energy-monitoring models: KP115, KP125, HS300, EP25, etc.
    """
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        async def _run():
            ip, dev = await _kasa_find(device)
            if dev is None:
                return f"Device '{device}' not found. Check KASA_DEVICE_IPS in .env."
            alias = dev.alias or ip
            try:
                await dev.update()
                if hasattr(dev, "emeter_realtime"):
                    emeter = dev.emeter_realtime
                    if hasattr(emeter, "power"):
                        lines = [f"{alias} — live power:"]
                        lines.append(f"  Power:   {emeter.power:.1f} W")
                        v = getattr(emeter, "voltage", None)
                        i = getattr(emeter, "current", None)
                        if v:
                            lines.append(f"  Voltage: {v:.1f} V")
                        if i:
                            lines.append(f"  Current: {i:.3f} A")
                        return "\n".join(lines)
            except Exception:
                pass
            return (
                f"[{alias} does not support energy monitoring. "
                "Supported models: KP115, KP125, HS300, EP25.]"
            )
        return asyncio.run(_run())
    except Exception as e:
        return f"[Kasa error: {e}]"


def kasa_energy_today(device: str) -> str:
    """
    Get today's total energy consumption in Wh/kWh from a TP-Link Kasa device.
    Only supported on energy-monitoring models (KP115, KP125, HS300, etc.).
    """
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        async def _run():
            ip, dev = await _kasa_find(device)
            if dev is None:
                return f"Device '{device}' not found. Check KASA_DEVICE_IPS in .env."
            alias = dev.alias or ip
            try:
                await dev.update()
                if hasattr(dev, "emeter_today"):
                    today = dev.emeter_today
                    if today is not None:
                        wh = float(today) * 1000 if float(today) < 10 else float(today)
                        kwh = wh / 1000
                        return f"{alias} — today's usage: {wh:.0f} Wh ({kwh:.3f} kWh)"
                # Try dict form
                if hasattr(dev, "get_emeter_daily"):
                    from datetime import date
                    d = date.today()
                    data = await dev.get_emeter_daily(year=d.year, month=d.month)
                    today_wh = data.get(d.day, 0) * 1000
                    return f"{alias} — today's usage: {today_wh:.0f} Wh ({today_wh/1000:.3f} kWh)"
            except Exception:
                pass
            return f"[{alias} does not support energy stats. Models with energy monitoring: KP115, KP125, HS300.]"
        return asyncio.run(_run())
    except Exception as e:
        return f"[Kasa error: {e}]"


def kasa_energy_month(device: str) -> str:
    """
    Get this month's total energy consumption from a TP-Link Kasa device.
    Only supported on energy-monitoring models (KP115, KP125, HS300, etc.).
    """
    if not _KASA_IPS:
        return _KASA_NOT_SET
    try:
        async def _run():
            ip, dev = await _kasa_find(device)
            if dev is None:
                return f"Device '{device}' not found. Check KASA_DEVICE_IPS in .env."
            alias = dev.alias or ip
            try:
                await dev.update()
                from datetime import date
                d = date.today()

                if hasattr(dev, "emeter_month"):
                    month_kwh = float(dev.emeter_month or 0)
                    return f"{alias} — this month's usage: {month_kwh:.3f} kWh"

                if hasattr(dev, "get_emeter_daily"):
                    data = await dev.get_emeter_daily(year=d.year, month=d.month)
                    total_kwh = sum(data.values())
                    lines = [f"{alias} — {d.strftime('%B')} usage: {total_kwh:.3f} kWh"]
                    lines.append(f"  ({len(data)} day(s) with data so far)")
                    return "\n".join(lines)
            except Exception:
                pass
            return f"[{alias} does not support monthly energy stats. Models with energy monitoring: KP115, KP125, HS300.]"
        return asyncio.run(_run())
    except Exception as e:
        return f"[Kasa error: {e}]"


# ── Global: combined overview ─────────────────────────────────────────────────

def smart_home_status() -> str:
    """
    Combined overview of all smart home devices — Hue lights and Kasa plugs —
    in a single response. Good for a morning briefing or quick check.
    """
    sections = []

    # Hue section
    if _hue_available():
        try:
            lights = _hue_get("/lights")
            groups = _hue_get("/groups")
            on_lights  = [l["name"] for l in lights.values() if l.get("state", {}).get("on")]
            off_lights = [l["name"] for l in lights.values() if not l.get("state", {}).get("on")]
            unreach    = [l["name"] for l in lights.values() if not l.get("state", {}).get("reachable", True)]

            hue_lines = [f"Hue lights — {len(on_lights)} on, {len(off_lights)} off:"]
            if on_lights:
                hue_lines.append(f"  ON:  {', '.join(on_lights)}")
            if off_lights:
                hue_lines.append(f"  off: {', '.join(off_lights)}")
            if unreach:
                hue_lines.append(f"  [Unreachable]: {', '.join(unreach)}")

            # Active rooms
            on_rooms = [g["name"] for g in groups.values() if g.get("state", {}).get("any_on")]
            if on_rooms:
                hue_lines.append(f"  Active rooms: {', '.join(on_rooms)}")

            sections.append("\n".join(hue_lines))
        except Exception as e:
            sections.append(f"Hue: [error — {e}]")
    else:
        sections.append("Hue: not configured (.env missing HUE_BRIDGE_IP / HUE_USERNAME)")

    # Kasa section
    if _KASA_IPS:
        try:
            devices = asyncio.run(_kasa_all_devices())
            on_devs  = [dev.alias or ip for ip, dev in devices if dev.is_on]
            off_devs = [dev.alias or ip for ip, dev in devices if not dev.is_on]
            unreach  = len(_KASA_IPS) - len(devices)

            kasa_lines = [f"Kasa plugs — {len(on_devs)} on, {len(off_devs)} off:"]
            if on_devs:
                kasa_lines.append(f"  ON:  {', '.join(on_devs)}")
            if off_devs:
                kasa_lines.append(f"  off: {', '.join(off_devs)}")
            if unreach:
                kasa_lines.append(f"  [Unreachable]: {unreach} device(s)")

            sections.append("\n".join(kasa_lines))
        except Exception as e:
            sections.append(f"Kasa: [error — {e}]")
    else:
        sections.append("Kasa: not configured (.env missing KASA_DEVICE_IPS)")

    # Wake-up timers
    if _WAKE_TIMERS:
        active = ", ".join(_WAKE_TIMERS.keys())
        sections.append(f"Active wake-up simulation: {active}")

    return "\n\n".join(sections)
