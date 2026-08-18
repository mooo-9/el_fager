"""
Prayer times for Cairo — Phase 6E.
Uses Aladhan API (free, no key) with Egyptian General Authority of Survey method.
"""

from datetime import datetime
import httpx

_PRAYER_NAMES_EN = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]

_API = "https://api.aladhan.com/v1/timingsByCity"


def get_prayer_times(date: str = None) -> str:
    """
    Return today's (or a specific date's) prayer times for Cairo.
    date — optional, format YYYY-MM-DD. Defaults to today.
    """
    if date is None:
        date = datetime.now().strftime("%d-%m-%Y")
    else:
        # Accept YYYY-MM-DD and convert to DD-MM-YYYY for the API
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            date = d.strftime("%d-%m-%Y")
        except ValueError:
            pass  # pass as-is

    try:
        resp = httpx.get(
            _API,
            params={
                "city": "Cairo",
                "country": "Egypt",
                "method": 5,   # Egyptian General Authority of Survey
                "date": date,
            },
            timeout=8,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 200:
            return f"[Prayer times error: {data.get('status', 'unknown')}]"

        timings = data["data"]["timings"]
        readable_date = data["data"]["date"]["readable"]

        lines = [f"Prayer times for Cairo — {readable_date}:\n"]
        pairs = [
            ("Fajr", timings.get("Fajr")),
            ("Sunrise", timings.get("Sunrise")),
            ("Dhuhr", timings.get("Dhuhr")),
            ("Asr", timings.get("Asr")),
            ("Maghrib", timings.get("Maghrib")),
            ("Isha", timings.get("Isha")),
        ]
        for en, t in pairs:
            if t:
                # Strip timezone suffix (e.g. "(EET)")
                t_clean = t.split(" ")[0]
                lines.append(f"  {en}:  {t_clean}")

        # Highlight next prayer
        now = datetime.now()
        for en, t in pairs:
            if not t:
                continue
            try:
                t_clean = t.split(" ")[0]
                prayer_dt = datetime.strptime(
                    f"{now.strftime('%Y-%m-%d')} {t_clean}", "%Y-%m-%d %H:%M"
                )
                if prayer_dt > now:
                    lines.append(f"\nNext prayer: {en} at {t_clean}")
                    break
            except ValueError:
                pass

        return "\n".join(lines)

    except Exception as e:
        return f"[Prayer times error: {e}]"


def get_next_prayer() -> str:
    """Return only the next upcoming prayer and its time."""
    full = get_prayer_times()
    for line in full.splitlines():
        if line.startswith("Next prayer:"):
            return line.replace("Next prayer: ", "")
    return full
