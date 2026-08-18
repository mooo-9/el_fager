"""The calendar reminder check.

This never ran. `core/proactive.py` imported `list_calendar_events` — the
brain's *tool name* for the function, not an importable symbol; the real name
is `list_events` — and the resulting ImportError went into a bare
`except Exception: pass`. `git log -S` dates the bad import to the initial
commit, so from the day the project started, no calendar reminder ever fired
and nothing said so.

Nothing exercised this method, which is why two months passed. These tests
drive it against a fake calendar so the whole path is covered without a
Google account: the import resolves, the real output format parses, and a
failure is reported rather than swallowed.
"""
from datetime import datetime, timedelta

import pytest

from core.proactive import ProactiveEngine


def _engine(monkeypatch, calendar_text):
    """An engine wired to a fake calendar, recording what it would say."""
    import tools.calendar_tool as cal
    monkeypatch.setattr(cal, "list_events",
                        lambda *a, **k: calendar_text, raising=True)

    engine = ProactiveEngine.__new__(ProactiveEngine)
    spoken = []
    engine._deliver = lambda text: spoken.append(text)
    engine._hud_notify = lambda *a, **k: None
    engine._cooldown = lambda key, hours: False      # never suppressed
    return engine, spoken


def _event_line(minutes_from_now: int, title: str = "Team standup",
                duration: str = "30 min") -> str:
    """One line in the exact shape tools.calendar_tool._format_event emits."""
    when = datetime.now() + timedelta(minutes=minutes_from_now)
    stamp = when.strftime("%I:%M %p")
    stamp = stamp[1:] if stamp.startswith("0") else stamp
    return f"📅 Events for today:\n- {stamp} — {title} ({duration})"


class TestItRunsAtAll:
    def test_the_import_resolves(self):
        # The one-line defect: this raised ImportError for two months.
        from tools.calendar_tool import list_events
        assert callable(list_events)

    def test_an_imminent_event_produces_a_reminder(self, monkeypatch):
        engine, spoken = _engine(monkeypatch, _event_line(12))
        engine._check_upcoming_events()
        assert len(spoken) == 1
        assert "starts in" in spoken[0]


class TestTheWindow:
    @pytest.mark.parametrize("minutes", [6, 12, 19])
    def test_events_inside_the_window_are_announced(self, monkeypatch, minutes):
        engine, spoken = _engine(monkeypatch, _event_line(minutes))
        engine._check_upcoming_events()
        assert spoken, f"nothing said for an event {minutes} minutes away"

    @pytest.mark.parametrize("minutes", [2, 45, 240])
    def test_events_outside_it_are_not(self, monkeypatch, minutes):
        engine, spoken = _engine(monkeypatch, _event_line(minutes))
        engine._check_upcoming_events()
        assert not spoken, f"announced an event {minutes} minutes away"


class TestTheSpokenLine:
    def test_the_duration_suffix_is_dropped(self, monkeypatch):
        # _format_event appends "(30 min)", which read aloud as
        # "Team standup (30 min) starts in 12 minutes".
        engine, spoken = _engine(monkeypatch, _event_line(12, "Team standup"))
        engine._check_upcoming_events()
        assert "'Team standup'" in spoken[0]
        assert "30 min)" not in spoken[0]

    def test_a_title_with_its_own_brackets_keeps_them(self, monkeypatch):
        engine, spoken = _engine(
            monkeypatch, _event_line(12, "Review (draft) chapter", "1 hour"))
        engine._check_upcoming_events()
        assert "Review (draft) chapter" in spoken[0]


class TestQuietCases:
    def test_an_empty_calendar_says_nothing(self, monkeypatch):
        engine, spoken = _engine(monkeypatch, "No events found for today")
        engine._check_upcoming_events()
        assert not spoken

    def test_an_all_day_event_is_not_a_timed_reminder(self, monkeypatch):
        engine, spoken = _engine(
            monkeypatch, "📅 Events for today:\n- All day — Public holiday")
        engine._check_upcoming_events()
        assert not spoken


class TestFailuresAreVisible:
    def test_a_broken_calendar_is_reported_not_swallowed(self, monkeypatch, capsys):
        import tools.calendar_tool as cal

        def explode(*a, **k):
            raise RuntimeError("calendar auth failed")

        monkeypatch.setattr(cal, "list_events", explode, raising=True)
        engine = ProactiveEngine.__new__(ProactiveEngine)
        engine._deliver = lambda text: None
        engine._hud_notify = lambda *a, **k: None
        engine._cooldown = lambda key, hours: False

        engine._check_upcoming_events()      # must not raise
        assert "event check error" in capsys.readouterr().out, \
            "the failure was swallowed — exactly how the import bug hid"
