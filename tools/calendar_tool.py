"""
Google Calendar tool — Phase 2D.

Requires data/credentials.json (download from Google Cloud Console).
token.json is auto-created on first successful OAuth flow.
Both files are in .gitignore — never commit them.
"""

import os
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CREDENTIALS_PATH = "data/credentials.json"
TOKEN_PATH = "data/token.json"
CALENDAR_AVAILABLE = os.path.exists(CREDENTIALS_PATH)

CAIRO_TZ = ZoneInfo("Africa/Cairo")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Module-level pending deletion state (ephemeral — resets on restart)
_pending_deletion: dict = {}


# ── Auth ─────────────────────────────────────────────────────────────────────

def get_calendar_service():
    """Build and return authenticated Google Calendar service, or None on failure."""
    if not CALENDAR_AVAILABLE:
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        if not creds or not creds.valid:
            refreshed = False
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    refreshed = True
                except Exception:
                    # Refresh token revoked/expired server-side -- fall through
                    # to a fresh interactive OAuth flow instead of failing.
                    creds = None
            if not refreshed:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        print(f"[El Fager] Calendar auth failed: {e}")
        return None


# ── Natural language date/time parsers ───────────────────────────────────────

def parse_date(date_str: str, reference: datetime = None) -> date:
    """
    Parse natural date strings to a date object (Cairo timezone).
    Accepts: "today", "tomorrow", "monday", "next thursday", "YYYY-MM-DD"
    """
    ref = reference or datetime.now(CAIRO_TZ)
    today = ref.date()
    s = date_str.strip().lower()

    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)

    # YYYY-MM-DD
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass

    # Day names: "monday", "next thursday", etc.
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    next_prefix = s.startswith("next ")
    day_word = s.removeprefix("next ").strip()
    if day_word in day_names:
        target_weekday = day_names.index(day_word)
        current_weekday = today.weekday()
        days_ahead = (target_weekday - current_weekday) % 7
        if days_ahead == 0:
            days_ahead = 7  # always go to next occurrence
        if next_prefix and days_ahead < 7:
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    raise ValueError(
        f"Couldn't parse date '{date_str}'. Try: 'today', 'tomorrow', 'Monday', 'next Thursday', or 'YYYY-MM-DD'"
    )


def parse_time(time_str: str) -> time:
    """
    Parse natural time strings to a time object.
    Accepts: "3pm", "3:30pm", "15:00", "3:30 PM", "9am"
    """
    s = time_str.strip().lower().replace(" ", "")

    # 24h: "15:00", "9:30"
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return time(h, mn)

    # "3pm", "3:30pm", "9am", "11:45am"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)", s)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        period = m.group(3)
        if period == "pm" and h != 12:
            h += 12
        if period == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return time(h, mn)

    raise ValueError(
        f"Couldn't parse time '{time_str}'. Try: '3pm', '3:30pm', '15:00', '9am'"
    )


def _parse_time_range(time_range: str):
    """Return (time_min_rfc3339, time_max_rfc3339, label) for list_events."""
    now = datetime.now(CAIRO_TZ)
    today = now.date()
    s = time_range.strip().lower()

    if s == "today":
        t_min = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=CAIRO_TZ)
        t_max = t_min + timedelta(days=1)
        label = f"today ({now.strftime('%A, %b %d')})"
    elif s == "tomorrow":
        tomorrow = today + timedelta(days=1)
        t_min = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0, tzinfo=CAIRO_TZ)
        t_max = t_min + timedelta(days=1)
        label = f"tomorrow ({t_min.strftime('%A, %b %d')})"
    elif s == "this week":
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        t_min = datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=CAIRO_TZ)
        t_max = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, tzinfo=CAIRO_TZ)
        label = "this week"
    else:
        # "next 3 days", "next 7 days", or fall back to 7 days
        m = re.search(r"(\d+)\s+day", s)
        days = int(m.group(1)) if m else 7
        t_min = now
        t_max = now + timedelta(days=days)
        label = f"the next {days} days"

    return t_min.isoformat(), t_max.isoformat(), label


def _fmt_time(dt: datetime) -> str:
    """Format datetime to 12h time without leading zero — cross-platform safe."""
    t = dt.strftime("%I:%M %p")
    return t[1:] if t.startswith("0") else t


def _format_event(event: dict) -> str:
    """Format a single calendar event as a readable string."""
    title = event.get("summary", "(no title)")
    start = event.get("start", {})
    end = event.get("end", {})

    if "dateTime" in start:
        start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(CAIRO_TZ)
        end_dt = datetime.fromisoformat(end["dateTime"]).astimezone(CAIRO_TZ)
        duration_min = int((end_dt - start_dt).total_seconds() / 60)
        if duration_min < 60:
            dur = f"{duration_min} min"
        elif duration_min == 60:
            dur = "1 hour"
        elif duration_min % 60 == 0:
            dur = f"{duration_min // 60} hours"
        else:
            dur = f"{duration_min // 60}h {duration_min % 60}m"
        return f"- {_fmt_time(start_dt)} — {title} ({dur})"
    else:
        # All-day event
        return f"- All day — {title}"


# ── Public calendar functions ─────────────────────────────────────────────────

def list_events(time_range: str = "today", max_results: int = 10) -> str:
    """List Mo's Google Calendar events for a given time range."""
    if not CALENDAR_AVAILABLE:
        return "[Calendar not set up — place credentials.json in data/ folder. See README for instructions.]"

    service = get_calendar_service()
    if service is None:
        return "[Calendar auth failed — check credentials.json]"

    try:
        time_min, time_max, label = _parse_time_range(time_range)
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
        if not events:
            return f"No events found for {label}"

        lines = [f"📅 Events for {label}:"]
        for ev in events:
            lines.append(_format_event(ev))

        output = "\n".join(lines)
        if len(output) > 2000:
            output = output[:2000] + "\n[... truncated]"
        return output

    except Exception as e:
        return f"[Calendar error: {e}]"


def create_event(
    title: str,
    date: str,
    start_time: str,
    duration_minutes: int = 60,
    description: str = "",
    location: str = "",
) -> str:
    """Create a new Google Calendar event."""
    if not CALENDAR_AVAILABLE:
        return "[Calendar not set up — place credentials.json in data/ folder. See README for instructions.]"

    service = get_calendar_service()
    if service is None:
        return "[Calendar auth failed]"

    try:
        event_date = parse_date(date)
        event_time = parse_time(start_time)
    except ValueError as e:
        return f"[Couldn't parse date/time: {e}. Try 'tomorrow at 3pm' or '2025-01-16 at 15:00']"

    try:
        start_dt = datetime(
            event_date.year, event_date.month, event_date.day,
            event_time.hour, event_time.minute,
            tzinfo=CAIRO_TZ,
        )
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        event_body = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Africa/Cairo"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Africa/Cairo"},
        }
        service.events().insert(calendarId="primary", body=event_body).execute()

        readable_date = start_dt.strftime("%A, %b %d")
        readable_time = _fmt_time(start_dt)
        return f"✅ Created: {title} on {readable_date} at {readable_time} ({duration_minutes} min)"

    except Exception as e:
        return f"[Calendar error: {e}]"


def update_event(
    search_term: str,
    new_title: str = None,
    new_time: str = None,
    new_date: str = None,
    new_duration_minutes: int = None,
) -> str:
    """Update an existing calendar event found by title keyword."""
    if not CALENDAR_AVAILABLE:
        return "[Calendar not set up — place credentials.json in data/ folder. See README for instructions.]"

    service = get_calendar_service()
    if service is None:
        return "[Calendar auth failed]"

    try:
        now = datetime.now(CAIRO_TZ)
        time_max = (now + timedelta(days=30)).isoformat()
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max,
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
        match = next(
            (e for e in events if search_term.lower() in e.get("summary", "").lower()),
            None,
        )
        if not match:
            return f"No event found matching '{search_term}' in the next 30 days"

        event_id = match["id"]
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        if new_title:
            event["summary"] = new_title

        if new_time or new_date or new_duration_minutes is not None:
            start = event.get("start", {})
            if "dateTime" in start:
                current_start = datetime.fromisoformat(start["dateTime"]).astimezone(CAIRO_TZ)
                current_end = datetime.fromisoformat(event["end"]["dateTime"]).astimezone(CAIRO_TZ)
                current_duration = int((current_end - current_start).total_seconds() / 60)
            else:
                current_start = datetime.now(CAIRO_TZ)
                current_duration = 60

            new_d = parse_date(new_date) if new_date else current_start.date()
            new_t = parse_time(new_time) if new_time else current_start.time().replace(second=0, microsecond=0)
            dur = new_duration_minutes if new_duration_minutes is not None else current_duration

            new_start = datetime(
                new_d.year, new_d.month, new_d.day,
                new_t.hour, new_t.minute,
                tzinfo=CAIRO_TZ,
            )
            new_end = new_start + timedelta(minutes=dur)
            event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "Africa/Cairo"}
            event["end"] = {"dateTime": new_end.isoformat(), "timeZone": "Africa/Cairo"}

        original_title = match.get("summary", search_term)
        service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
        return f"✅ Updated: {original_title} → changes applied"

    except ValueError as e:
        return f"[Couldn't parse date/time: {e}]"
    except Exception as e:
        return f"[Calendar error: {e}]"


def delete_event(search_term: str) -> str:
    """
    Find a calendar event and ask for confirmation before deleting.
    Stores pending deletion state for confirm_delete_event() to complete.
    """
    if not CALENDAR_AVAILABLE:
        return "[Calendar not set up — place credentials.json in data/ folder. See README for instructions.]"

    service = get_calendar_service()
    if service is None:
        return "[Calendar auth failed]"

    try:
        now = datetime.now(CAIRO_TZ)
        time_max = (now + timedelta(days=30)).isoformat()
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max,
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
        match = next(
            (e for e in events if search_term.lower() in e.get("summary", "").lower()),
            None,
        )
        if not match:
            return f"No event found matching '{search_term}' in the next 30 days"

        title = match.get("summary", "(no title)")
        start = match.get("start", {})
        if "dateTime" in start:
            start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(CAIRO_TZ)
            readable = f"{start_dt.strftime('%A, %b %d')} at {_fmt_time(start_dt)}"
        else:
            readable = start.get("date", "unknown date")

        _pending_deletion["event_id"] = match["id"]
        _pending_deletion["title"] = title
        _pending_deletion["expires_at"] = datetime.now(CAIRO_TZ) + timedelta(seconds=60)

        return f"Found: {title} on {readable}. Confirm deletion by saying 'yes delete it'."

    except Exception as e:
        return f"[Calendar error: {e}]"


def confirm_delete_event() -> str:
    """Complete a pending calendar event deletion after Mo confirms."""
    if not CALENDAR_AVAILABLE:
        return "[Calendar not set up — place credentials.json in data/ folder. See README for instructions.]"

    if not _pending_deletion:
        return "No pending deletion to confirm"

    if datetime.now(CAIRO_TZ) > _pending_deletion.get("expires_at", datetime.min.replace(tzinfo=CAIRO_TZ)):
        _pending_deletion.clear()
        return "Deletion request expired — say 'cancel my [event name]' again to retry"

    service = get_calendar_service()
    if service is None:
        return "[Calendar auth failed]"

    try:
        event_id = _pending_deletion["event_id"]
        title = _pending_deletion["title"]
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        _pending_deletion.clear()
        return f"🗑️ Deleted: {title}"
    except Exception as e:
        _pending_deletion.clear()
        return f"[Calendar error: {e}]"
