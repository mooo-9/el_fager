"""Barge-in: talking over the assistant cuts it off.

The detector never sees a microphone in these tests — feed() takes frame
levels directly, which is the whole reason the decision is separated from the
device. What is being pinned here is the judgement: the assistant's own voice
bleeding into the mic must NOT trip it, and Mo's must.
"""
import json

import pytest

from core.barge_in import BargeInMonitor


def _run(monitor: BargeInMonitor, level: float, seconds: float = 1.0):
    """Feed `seconds` of frames at one level (a frame is 100ms)."""
    for _ in range(int(seconds * 10)):
        monitor.feed(level)


class TestJudgement:
    def test_the_assistants_own_bleed_does_not_trip_it(self):
        # Speakers: the mic hears the assistant at a steady level for the
        # whole utterance. That is the case that must never self-interrupt.
        monitor = BargeInMonitor()
        _run(monitor, 0.05, seconds=8)
        assert not monitor.tripped.is_set()

    def test_a_voice_over_the_top_trips_it(self):
        monitor = BargeInMonitor()
        _run(monitor, 0.05, seconds=1)      # calibrate on the bleed
        _run(monitor, 0.30, seconds=0.5)    # Mo, well above it
        assert monitor.tripped.is_set()

    def test_silence_does_not_arm_a_hair_trigger(self):
        # On headphones the floor would be ~0, so an absolute floor keeps
        # room tone and a fan from counting as speech.
        monitor = BargeInMonitor()
        _run(monitor, 0.0, seconds=1)
        _run(monitor, 0.02, seconds=1)
        assert not monitor.tripped.is_set()

    def test_headphones_stay_sensitive(self):
        monitor = BargeInMonitor()
        _run(monitor, 0.001, seconds=1)     # near silence
        _run(monitor, 0.09, seconds=0.5)    # a normal speaking voice
        assert monitor.tripped.is_set()

    def test_a_single_bang_is_not_a_sentence(self):
        # One loud frame is a door or a keyboard; it takes sustained speech.
        monitor = BargeInMonitor()
        _run(monitor, 0.05, seconds=1)
        monitor.feed(0.9)
        assert not monitor.tripped.is_set()

    def test_it_stays_tripped_once_tripped(self):
        monitor = BargeInMonitor()
        _run(monitor, 0.05, seconds=1)
        _run(monitor, 0.30, seconds=0.5)
        _run(monitor, 0.0, seconds=2)
        assert monitor.tripped.is_set()

    def test_nothing_trips_during_calibration(self):
        monitor = BargeInMonitor(calibrate_sec=1.0)
        _run(monitor, 0.9, seconds=0.9)
        assert not monitor.tripped.is_set()


class TestSetting:
    @pytest.fixture
    def settings(self, tmp_path, monkeypatch):
        (tmp_path / "data").mkdir()
        monkeypatch.chdir(tmp_path)
        # The suite-wide test flag short-circuits enabled() so nothing opens
        # a microphone; drop it here to test the setting itself.
        monkeypatch.delenv("EL_FAGER_TEST_MODE", raising=False)

        def write(**keys):
            (tmp_path / "data" / "settings.json").write_text(
                json.dumps(keys), encoding="utf-8")
        return write

    def test_on_by_default(self, settings):
        from core import barge_in
        settings()
        assert barge_in.enabled() is True

    def test_it_can_be_switched_off(self, settings):
        from core import barge_in
        settings(barge_in=False)
        assert barge_in.enabled() is False

    def test_a_missing_settings_file_leaves_it_on(self, settings, tmp_path):
        from core import barge_in
        assert barge_in.enabled() is True

    def test_the_suite_never_opens_the_microphone(self):
        # PortAudio takes the whole process down when there is no device, so
        # this guard is what keeps the test run from segfaulting.
        from core import barge_in
        assert barge_in.enabled() is False


class TestPlaybackStops:
    def test_play_file_cuts_the_moment_the_hook_says_so(self, monkeypatch,
                                                        tmp_path):
        """The hook is polled during playback, not checked at the end."""
        import core.voice_out as vo

        polls = {"n": 0}

        class FakeMusic:
            def load(self, path): pass
            def play(self): pass
            def get_busy(self): return True      # a very long sentence
            def stop(self): pass
            def unload(self): pass

        monkeypatch.setattr(vo.pygame.mixer, "music", FakeMusic())
        monkeypatch.setattr(vo.time, "sleep", lambda s: None)

        def should_stop():
            polls["n"] += 1
            return polls["n"] > 3

        path = tmp_path / "chunk.wav"
        path.write_bytes(b"x")
        assert vo._play_file(str(path), should_stop) is True
        assert polls["n"] == 4                    # it polled, then cut

    def test_without_a_hook_it_plays_to_the_end(self, monkeypatch, tmp_path):
        import core.voice_out as vo

        frames = {"n": 0}

        class FakeMusic:
            def load(self, path): pass
            def play(self): pass
            def get_busy(self):
                frames["n"] += 1
                return frames["n"] < 3
            def stop(self): pass
            def unload(self): pass

        monkeypatch.setattr(vo.pygame.mixer, "music", FakeMusic())
        monkeypatch.setattr(vo.time, "sleep", lambda s: None)
        path = tmp_path / "chunk.wav"
        path.write_bytes(b"x")
        assert vo._play_file(str(path)) is False

    def test_the_rest_of_the_reply_is_dropped_not_played(self, monkeypatch,
                                                         tmp_path):
        """Once talked over, later sentences are discarded — and their temp
        files with them, or the synth worker blocks on a full queue."""
        import core.voice_out as vo

        played, discarded = [], []
        monkeypatch.setattr(vo, "_play_file",
                            lambda path, stop=None: (played.append(path), True)[1])
        monkeypatch.setattr(vo, "_discard", lambda path: discarded.append(path))

        out = vo.VoiceOutput.__new__(vo.VoiceOutput)
        out._synthesize = lambda text: f"/tmp/{text}.wav"
        result = out.speak_stream(iter(["one", "two", "three"]),
                                  should_stop=lambda: True)
        assert result is True
        assert played == ["/tmp/one.wav"]
        assert discarded == ["/tmp/two.wav", "/tmp/three.wav"]
