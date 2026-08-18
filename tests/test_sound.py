"""Tests for the sound cues.

Cues are synthesised, so they can be measured rather than eyeballed: each
one's length, headroom, and dominant pitch are checked against the recipe.
The mix rules are the part that matters behaviourally — nothing talks over
the assistant except a failure.
"""
import numpy as np
import pytest

from core import sound


def _dominant_hz(buf: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(buf * np.hanning(len(buf))))
    return float(np.fft.rfftfreq(len(buf), 1 / sound.SR)[int(np.argmax(spectrum))])


class TestVoices:
    def test_the_pluck_lands_on_its_fundamental(self):
        assert _dominant_hz(sound.note(440, 0.3)) == pytest.approx(440, abs=12)

    def test_fm_is_more_harmonically_dense_than_a_pluck(self):
        # the modulator is what makes it read as metallic rather than woody
        def brightness(buf):
            spec = np.abs(np.fft.rfft(buf))
            freqs = np.fft.rfftfreq(len(buf), 1 / sound.SR)
            return float((spec * freqs).sum() / max(spec.sum(), 1e-9))
        assert brightness(sound.fm(440, 0.3, index=3.0)) > brightness(sound.note(440, 0.3))

    def test_the_noise_burst_sits_around_its_centre(self):
        assert _dominant_hz(sound.noise(0.05, 0.5, 2000, 3)) == pytest.approx(2000, rel=0.6)

    def test_every_voice_starts_and_ends_quietly(self):
        for buf in (sound.note(440), sound.fm(440), sound.noise()):
            assert abs(buf[0]) < 0.05           # no click on the way in
            assert abs(buf[-1]) < 0.1           # decayed on the way out


class TestCues:
    @pytest.mark.parametrize("name", list(sound.CUES))
    def test_a_cue_is_short_enough_to_be_a_cue(self, name):
        # The ≤400ms rule is about the cue itself; the ~0.9s reverb tail
        # trails past it by design, so measure the dry buffer.
        assert len(sound.CUES[name]()) / sound.SR <= 0.42

    @pytest.mark.parametrize("name", list(sound.CUES))
    def test_the_reverb_tail_decays_rather_than_ringing_on(self, name):
        buf = sound.render(name)
        tail = buf[int(sound.SR * 0.5):]
        assert float(np.max(np.abs(tail))) < 0.2

    @pytest.mark.parametrize("name", list(sound.CUES))
    def test_a_cue_keeps_headroom(self, name):
        assert np.max(np.abs(sound.render(name))) == pytest.approx(0.9, abs=0.01)

    @pytest.mark.parametrize("name", list(sound.CUES))
    def test_a_cue_is_not_silence(self, name):
        assert float(np.sqrt(np.mean(sound.render(name) ** 2))) > 0.01

    def test_all_seven_cues_exist(self):
        assert set(sound.CUES) == {
            "summon", "heard", "step", "resolved", "armed", "sent", "error"}

    def test_the_cues_are_distinguishable_from_each_other(self):
        # recognisable eyes-closed means no two share a spectral shape
        shapes = {}
        for name in sound.CUES:
            buf = sound.render(name)
            spec = np.abs(np.fft.rfft(buf))
            freqs = np.fft.rfftfreq(len(buf), 1 / sound.SR)
            shapes[name] = (spec * freqs).sum() / max(spec.sum(), 1e-9)
        centroids = sorted(shapes.values())
        assert all(b - a > 1.0 for a, b in zip(centroids, centroids[1:]))

    def test_sent_falls_in_pitch(self):
        """A5 → D5 → A4: the arpeggio has to descend, or it reads as a question.

        Measured on the dry cue: the reverb impulse is random noise, so the
        wet tail has no stable pitch to compare against.
        """
        dry = sound.CUES["sent"]()
        head = _dominant_hz(dry[:int(sound.SR * 0.06)])
        tail = _dominant_hz(dry[int(sound.SR * 0.20):])
        assert head > tail

    def test_rendering_is_cached(self):
        assert sound.render("summon") is sound.render("summon")


class TestMixRules:
    def test_nothing_talks_over_the_assistant(self, monkeypatch):
        monkeypatch.setattr(sound, "_tts_busy", lambda: True)
        assert sound.play("sent") is False

    def test_except_a_failure_which_cuts_through(self, monkeypatch):
        monkeypatch.setattr(sound, "_tts_busy", lambda: True)
        monkeypatch.setattr(sound, "enabled", lambda name: True)
        played = {}
        monkeypatch.setitem(sound._sounds, "error", type("S", (), {"play": lambda self: played.setdefault("x", 1)})())
        assert sound.play("error") is True

    def test_a_disabled_cue_stays_silent(self, monkeypatch):
        monkeypatch.setattr(sound, "enabled", lambda name: False)
        assert sound.play("summon") is False

    def test_an_unknown_cue_is_ignored(self):
        assert sound.play("nonsense") is False

    def test_settings_can_switch_cues_off_wholesale(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text('{"sound_cues": false}', encoding="utf-8")
        monkeypatch.setattr(sound, "_SETTINGS", settings)
        assert sound.enabled("sent") is False

    def test_settings_can_switch_one_category_off(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text('{"sound_cues": {"step": false}}', encoding="utf-8")
        monkeypatch.setattr(sound, "_SETTINGS", settings)
        assert sound.enabled("step") is False
        assert sound.enabled("sent") is True

    def test_cues_default_on_when_settings_are_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sound, "_SETTINGS", tmp_path / "nope.json")
        assert sound.enabled("sent") is True
