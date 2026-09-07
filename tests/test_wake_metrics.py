"""Wake-word reliability: the front door has to be measurable.

A false accept is observable from inside — it woke and nothing was said. A
miss is not, by construction, so it is only ever counted when reported. These
tests hold that distinction, because a summary that invents a miss rate would
be worse than no summary.
"""
import json

import pytest


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    import core.wake_metrics as wm
    path = tmp_path / "wake_log.jsonl"
    monkeypatch.setattr(wm, "_LOG", path)
    wm.reset()
    yield path
    wm.reset()


def _lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class TestResolution:
    def test_a_wake_with_speech_behind_it_is_a_good_wake(self, log):
        from core import wake_metrics as wm
        wm.note_detection("hey_jarvis", 0.81)
        wm.note_speech(True)
        assert [e["outcome"] for e in _lines(log)] == ["heard"]

    def test_a_wake_with_nothing_behind_it_is_a_false_accept(self, log):
        from core import wake_metrics as wm
        wm.note_detection("hey_jarvis", 0.52)
        wm.note_speech(False)
        entry = _lines(log)[0]
        assert entry["outcome"] == "silent"
        assert entry["score"] == 0.52

    def test_a_turn_that_started_at_the_keyboard_records_nothing(self, log):
        # No detection is waiting, so a hotkey turn must not be counted as a
        # wake at all — that would bury the rate it exists to expose.
        from core import wake_metrics as wm
        wm.note_speech(True)
        assert _lines(log) == []

    def test_one_detection_resolves_once(self, log):
        from core import wake_metrics as wm
        wm.note_detection("hey_jarvis", 0.7)
        wm.note_speech(True)
        wm.note_speech(True)          # the next turn in the same conversation
        assert len(_lines(log)) == 1

    def test_a_stale_detection_is_dropped(self, log, monkeypatch):
        from datetime import datetime, timedelta
        import core.wake_metrics as wm
        wm.note_detection("hey_jarvis", 0.7)
        wm._pending["t"] = datetime.now() - timedelta(seconds=120)
        wm.note_speech(True)
        assert _lines(log) == []


class TestSummary:
    def _record(self, heard: int, silent: int):
        from core import wake_metrics as wm
        for _ in range(heard):
            wm.note_detection("hey_jarvis", 0.8)
            wm.note_speech(True)
        for _ in range(silent):
            wm.note_detection("hey_jarvis", 0.55)
            wm.note_speech(False)

    def test_it_counts_what_happened(self, log):
        from core import wake_metrics as wm
        self._record(heard=8, silent=2)
        s = wm.summary(7)
        assert s["detections"] == 10
        assert s["heard"] == 8
        assert s["false_accepts"] == 2
        assert s["false_accept_rate"] == pytest.approx(0.2)

    def test_misses_are_reported_never_inferred(self, log):
        from core import wake_metrics as wm
        self._record(heard=3, silent=0)
        wm.note_miss("said it twice in the kitchen")
        s = wm.summary(7)
        assert s["reported_misses"] == 1
        assert s["detections"] == 3          # a miss is not a detection
        assert "miss_rate" not in s          # it cannot be known from here

    def test_an_empty_log_summarises_to_zero_not_a_crash(self, log):
        from core import wake_metrics as wm
        s = wm.summary(7)
        assert s["detections"] == 0
        assert s["false_accept_rate"] == 0.0

    def test_the_caption_says_something_true_when_empty(self, log):
        from core import wake_metrics as wm
        assert wm.caption(7) == "NO WAKES RECORDED YET"

    def test_the_caption_carries_the_rate(self, log):
        from core import wake_metrics as wm
        self._record(heard=8, silent=2)
        caption = wm.caption(7)
        assert "WOKE 10×" in caption
        assert "20%" in caption


class TestListeningWindow:
    """An armed action keeps the mic open, or 'say send' is not a real path."""

    def _worker(self):
        from unittest.mock import MagicMock
        from core.pipeline import PipelineWorker
        return PipelineWorker(MagicMock(), MagicMock(), MagicMock(), MagicMock())

    def test_the_first_turn_waits_as_long_as_it_takes(self, qapp_free=None):
        assert self._worker()._listen_window(0) is None

    def test_later_turns_get_the_short_window(self):
        from core.pipeline import FOLLOWUP_WINDOW_SEC
        assert self._worker()._listen_window(1) == FOLLOWUP_WINDOW_SEC

    def test_an_armed_action_holds_the_mic_open_longer(self):
        from core import staging
        from core.pipeline import FOLLOWUP_WINDOW_SEC, STAGED_WINDOW_SEC
        staging.reset()
        staging.stage(medium="whatsapp", target="Omar", body="the meeting moved")
        try:
            window = self._worker()._listen_window(1)
            assert window == STAGED_WINDOW_SEC
            assert window > FOLLOWUP_WINDOW_SEC
        finally:
            staging.reset()

    def test_once_it_resolves_the_window_goes_back(self):
        from core import staging
        from core.pipeline import FOLLOWUP_WINDOW_SEC
        staging.reset()
        staging.stage(medium="gmail", target="a@b.c", body="hi")
        staging.resolve("sent")
        assert self._worker()._listen_window(1) == FOLLOWUP_WINDOW_SEC
        staging.reset()
