"""The turn profiler.

Two properties matter and both are easy to lose: it costs nothing when off,
and it never raises. A profiler that breaks a turn is worse than no profiler,
and one that stays on by default is a latency bug of its own.
"""
import json

import pytest

from core import turn_profile


@pytest.fixture
def on(monkeypatch, tmp_path):
    """Enable profiling and divert its output away from the real data dir."""
    monkeypatch.setattr(turn_profile, "ENABLED", True)
    monkeypatch.setattr(turn_profile, "_DIR", tmp_path)
    monkeypatch.setattr(turn_profile, "_current", None)
    return tmp_path


@pytest.fixture
def clock(monkeypatch):
    """A clock that only moves when told, so durations are exact."""
    now = {"t": 1000.0}
    monkeypatch.setattr(turn_profile.time, "monotonic", lambda: now["t"])
    return now


class TestDisabledByDefault:
    def test_it_is_off_unless_the_env_var_is_set(self, monkeypatch):
        # Reimporting with the var unset must leave it off — profiling that
        # switches itself on costs latency on every turn for everyone.
        monkeypatch.delenv("EL_FAGER_PROFILE", raising=False)
        import importlib
        reloaded = importlib.reload(turn_profile)
        assert reloaded.ENABLED is False
        monkeypatch.setenv("EL_FAGER_PROFILE", "1")
        assert importlib.reload(turn_profile).ENABLED is True
        monkeypatch.delenv("EL_FAGER_PROFILE", raising=False)
        importlib.reload(turn_profile)

    @pytest.mark.parametrize("value", ["", "0", "false", "False"])
    def test_falsey_values_do_not_enable_it(self, monkeypatch, value):
        monkeypatch.setenv("EL_FAGER_PROFILE", value)
        import importlib
        assert importlib.reload(turn_profile).ENABLED is False
        monkeypatch.delenv("EL_FAGER_PROFILE", raising=False)
        importlib.reload(turn_profile)

    def test_every_call_is_a_no_op_when_off(self, monkeypatch, tmp_path):
        monkeypatch.setattr(turn_profile, "ENABLED", False)
        monkeypatch.setattr(turn_profile, "_DIR", tmp_path)
        turn_profile.begin("x")
        turn_profile.start("s")
        turn_profile.end("s")
        turn_profile.mark("m")
        turn_profile.tool("t", 5)
        assert turn_profile.finish() is None
        assert list(tmp_path.iterdir()) == []


class TestRecording:
    def test_a_span_measures_the_time_between_start_and_end(self, on, clock):
        turn_profile.begin("turn")
        turn_profile.start("stt")
        clock["t"] += 0.812
        turn_profile.end("stt")
        entry = turn_profile.finish()
        assert entry["stages"]["stt"] == pytest.approx(812.0, abs=0.5)

    def test_a_mark_measures_from_the_start_of_the_turn(self, on, clock):
        # first_token and first_audio are moments, not spans: what matters is
        # how long Mo waited, not how long the producing step took.
        turn_profile.begin("turn")
        clock["t"] += 0.4
        turn_profile.start("memory")
        clock["t"] += 0.1
        turn_profile.end("memory")
        clock["t"] += 1.0
        turn_profile.mark("first_token")
        entry = turn_profile.finish()
        assert entry["stages"]["memory"] == pytest.approx(100.0, abs=0.5)
        assert entry["stages"]["first_token"] == pytest.approx(1500.0, abs=0.5)

    def test_the_same_tool_twice_accumulates(self, on, clock):
        turn_profile.begin("turn")
        turn_profile.tool("list_emails", 120)
        turn_profile.tool("list_emails", 80)
        assert turn_profile.finish()["tools"]["list_emails"] == pytest.approx(200.0)

    def test_total_covers_the_whole_turn(self, on, clock):
        turn_profile.begin("turn")
        clock["t"] += 4.2
        entry = turn_profile.finish()
        assert entry["total_ms"] == pytest.approx(4200.0, abs=0.5)

    def test_it_writes_one_json_line_per_turn(self, on, clock):
        for i in range(3):
            turn_profile.begin(f"turn {i}")
            turn_profile.start("stt")
            clock["t"] += 0.5
            turn_profile.end("stt")
            turn_profile.finish()
        written = list(on.glob("turns-*.jsonl"))
        assert len(written) == 1
        lines = written[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        assert json.loads(lines[0])["stages"]["stt"] == pytest.approx(500.0, abs=0.5)


class TestItNeverBreaksATurn:
    def test_ending_a_stage_that_never_started_is_ignored(self, on):
        turn_profile.begin("turn")
        turn_profile.end("never_started")
        assert "never_started" not in turn_profile.finish()["stages"]

    def test_recording_with_no_open_turn_is_harmless(self, on):
        turn_profile.start("stt")
        turn_profile.mark("first_token")
        turn_profile.tool("x", 1)
        assert turn_profile.finish() is None

    def test_an_unwritable_directory_does_not_raise(self, on, monkeypatch):
        monkeypatch.setattr(turn_profile, "_DIR", on / "nope" / "\0bad")
        turn_profile.begin("turn")
        assert turn_profile.finish() is None      # swallowed, not raised
