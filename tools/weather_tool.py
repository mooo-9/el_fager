"""
Weather tool — Phase 6C.

Uses Open-Meteo API: completely free, no API key, no rate limits.
Geocoding: https://geocoding-api.open-meteo.com/v1/search
Forecast:  https://api.open-meteo.com/v1/forecast
"""

from datetime import date as _date

import httpx

# WMO Weather interpretation codes
WMO: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Heavy showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm + hail", 99: "Thunderstorm + heavy hail",
}

DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Pre-cached coordinates — avoids geocoding API round-trip for common cities
_COORD_CACHE: dict[str, tuple[float, float]] = {
    "cairo":         (30.0626,  31.2497),
    "giza":          (30.0131,  31.2089),
    "alexandria":    (31.2001,  29.9187),
    "dubai":         (25.2048,  55.2708),
    "riyadh":        (24.6877,  46.7219),
    "amman":         (31.9554,  35.9453),
    "beirut":        (33.8938,  35.5018),
    "istanbul":      (41.0082,  28.9784),
    "london":        (51.5074,  -0.1278),
    "paris":         (48.8566,   2.3522),
    "new york":      (40.7128, -74.0060),
    "new york city": (40.7128, -74.0060),
    "nyc":           (40.7128, -74.0060),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wind_dir(degrees: float) -> str:
    """Convert wind direction degrees to compass label."""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(float(degrees) / 45) % 8]


def _uv_label(uv) -> str:
    """Return UV index severity label."""
    try:
        uv = float(uv)
    except (TypeError, ValueError):
        return ""
    if uv <= 2:   return "Low"
    if uv <= 5:   return "Moderate"
    if uv <= 7:   return "High"
    if uv <= 10:  return "Very High"
    return "Extreme"


def _hhmm(iso_str: str) -> str:
    """Extract HH:MM from 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DDTHH:MM:SS'."""
    try:
        return iso_str[11:16]
    except Exception:
        return iso_str


def _get_coords(city: str) -> tuple[float, float] | None:
    key = city.lower().strip()
    if key in _COORD_CACHE:
        return _COORD_CACHE[key]
    try:
        resp = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=8,
        )
        results = resp.json().get("results", [])
        if not results:
            return None
        r = results[0]
        coords = (r["latitude"], r["longitude"])
        _COORD_CACHE[key] = coords
        return coords
    except Exception:
        return None


# ── Public functions ──────────────────────────────────────────────────────────

def get_weather(city: str = "Cairo") -> str:
    """Return current weather conditions and today's summary for a city."""
    coords = _get_coords(city)
    if coords is None:
        return f"City '{city}' not found — check the spelling."
    lat, lon = coords
    try:
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,apparent_temperature,"
                    "relative_humidity_2m,wind_speed_10m,wind_direction_10m,weather_code"
                ),
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,uv_index_max,sunrise,sunset"
                ),
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        data = resp.json()
        cur   = data.get("current", {})
        daily = data.get("daily", {})

        temp      = cur.get("temperature_2m", "?")
        feels     = cur.get("apparent_temperature", "?")
        humidity  = cur.get("relative_humidity_2m", "?")
        wind_spd  = cur.get("wind_speed_10m", "?")
        wind_deg  = cur.get("wind_direction_10m")
        code      = cur.get("weather_code", 0)
        condition = WMO.get(code, f"Code {code}")

        hi         = daily.get("temperature_2m_max",          ["?"])[0]
        lo         = daily.get("temperature_2m_min",          ["?"])[0]
        rain_prob  = daily.get("precipitation_probability_max",  [None])[0]
        uv         = daily.get("uv_index_max",                [None])[0]
        sunrise    = daily.get("sunrise",                     [None])[0]
        sunset     = daily.get("sunset",                      [None])[0]

        feels_str = f" (feels {feels}°C)" if feels != "?" and feels != temp else ""
        wind_dir_str = f" {_wind_dir(wind_deg)}" if wind_deg is not None else ""
        uv_str    = f"  UV: {int(uv)} ({_uv_label(uv)})" if uv is not None else ""
        rain_str  = f"  Rain: {rain_prob}%" if rain_prob is not None else ""
        sun_str   = (
            f"\nSunrise: {_hhmm(sunrise)}  Sunset: {_hhmm(sunset)}"
            if sunrise and sunset else ""
        )

        return (
            f"{city} — {temp}°C{feels_str}, {condition}\n"
            f"Humidity: {humidity}%  Wind: {wind_spd} km/h{wind_dir_str}{uv_str}\n"
            f"Today: high {hi}°C / low {lo}°C{rain_str}"
            f"{sun_str}"
        )
    except Exception as e:
        return f"[Weather error: {e}]"


def get_weather_forecast(city: str = "Cairo", days: int = 3) -> str:
    """Return a multi-day weather forecast for a city."""
    days = max(1, min(days, 7))
    coords = _get_coords(city)
    if coords is None:
        return f"City '{city}' not found — check the spelling."
    lat, lon = coords
    try:
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": (
                    "temperature_2m_max,temperature_2m_min,weather_code,"
                    "precipitation_probability_max,precipitation_sum,uv_index_max"
                ),
                "timezone": "auto",
                "forecast_days": days,
            },
            timeout=10,
        )
        data  = resp.json()
        daily = data.get("daily", {})

        dates      = daily.get("time", [])
        highs      = daily.get("temperature_2m_max", [])
        lows       = daily.get("temperature_2m_min", [])
        codes      = daily.get("weather_code", [])
        rain_probs = daily.get("precipitation_probability_max", [])
        rain_sums  = daily.get("precipitation_sum", [])
        uvs        = daily.get("uv_index_max", [])

        lines = [f"{days}-day forecast for {city}:\n"]
        for i, date_str in enumerate(dates):
            try:
                d          = _date.fromisoformat(date_str)
                day_label  = DAYS_OF_WEEK[d.weekday()]
                date_label = d.strftime("%b %d")
            except Exception:
                day_label  = date_str
                date_label = ""

            hi        = highs[i]      if i < len(highs)      else "?"
            lo        = lows[i]       if i < len(lows)        else "?"
            code      = codes[i]      if i < len(codes)       else 0
            condition = WMO.get(int(code), f"Code {code}")
            prob      = rain_probs[i] if i < len(rain_probs)  else None
            rain_sum  = rain_sums[i]  if i < len(rain_sums)   else 0
            uv        = uvs[i]        if i < len(uvs)          else None

            rain_str = ""
            if prob is not None:
                rain_str = f"  {int(prob)}% rain"
                if rain_sum and float(rain_sum) > 0:
                    rain_str += f" ({rain_sum}mm)"
            uv_str   = f"  UV {int(uv)}" if uv is not None else ""

            lines.append(
                f"{day_label} {date_label}: {hi}/{lo}°C — {condition}{uv_str}{rain_str}"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"[Weather error: {e}]"


def get_hourly_weather(city: str = "Cairo", hours: int = 12) -> str:
    """Return an hour-by-hour weather breakdown for the next N hours (max 24)."""
    hours = max(1, min(hours, 24))
    coords = _get_coords(city)
    if coords is None:
        return f"City '{city}' not found — check the spelling."
    lat, lon = coords
    try:
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m",  # any variable forces current.time into the response
                "hourly": (
                    "temperature_2m,apparent_temperature,"
                    "precipitation_probability,weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
                "forecast_days": 2,  # 48 h so end-of-day requests don't run short
            },
            timeout=10,
        )
        data = resp.json()

        current_time = data.get("current", {}).get("time", "")
        hourly       = data.get("hourly", {})
        times        = hourly.get("time", [])
        temps        = hourly.get("temperature_2m", [])
        feels        = hourly.get("apparent_temperature", [])
        probs        = hourly.get("precipitation_probability", [])
        codes        = hourly.get("weather_code", [])
        winds        = hourly.get("wind_speed_10m", [])

        # Find the first slot at or after the current local time
        start = 0
        if current_time:
            for i, t in enumerate(times):
                if t >= current_time:
                    start = i
                    break

        lines = [f"Next {hours} hours in {city}:\n"]
        shown = 0
        for i in range(start, len(times)):
            if shown >= hours:
                break
            try:
                time_str  = _hhmm(times[i])
                temp      = temps[i]  if i < len(temps)  else "?"
                feel      = feels[i]  if i < len(feels)   else None
                prob      = probs[i]  if i < len(probs)   else 0
                code      = codes[i]  if i < len(codes)   else 0
                condition = WMO.get(int(code), f"Code {code}")
                wind      = winds[i]  if i < len(winds)   else "?"

                feel_str = (
                    f" (feels {feel}°C)"
                    if feel is not None and abs(float(feel) - float(temp)) >= 2
                    else ""
                )
                rain_str = f"  {int(prob)}% rain" if prob and int(prob) > 15 else ""
                lines.append(
                    f"{time_str}  {temp}°C{feel_str}  {condition}  Wind: {wind} km/h{rain_str}"
                )
                shown += 1
            except Exception:
                continue

        if shown == 0:
            return f"No hourly data available for {city}."
        return "\n".join(lines)
    except Exception as e:
        return f"[Weather error: {e}]"
