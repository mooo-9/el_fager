"""Other apps' audio is lowered while El Fager listens, and put back after.

On 2026-09-05 the mic heard the song El Fager had just started and Whisper
transcribed it back, turn after turn. These run against fake audio sessions:
no speakers, no COM.
"""
import os

import pytest

from core import ducking


class FakeVolume:
    def __init__(self, level):
        self.level = level

    def GetMasterVolume(self):
        return self.level

    def SetMasterVolume(self, level, context):
        self.level = level


class FakeProcess:
    def __init__(self, pid, name):
        self.pid = pid
        self._name = name

    def name(self):
        return self._name


class FakeSession:
    def __init__(self, pid, name, level):
        self.Process = FakeProcess(pid, name) if pid is not None else None
        self.SimpleAudioVolume = FakeVolume(level)


@pytest.fixture
def sessions(monkeypatch):
    found = [
        FakeSession(1111, "Spotify.exe", 0.8),
        FakeSession(2222, "chrome.exe", 1.0),
        FakeSession(os.getpid(), "pythonw.exe", 0.6),   # El Fager's own voice
        FakeSession(None, "System Sounds", 1.0),
    ]
    monkeypatch.setattr(ducking, "_sessions", lambda: found)
    monkeypatch.setattr(ducking, "_enabled", lambda: True)   # off in test mode by design
    return {("system" if s.Process is None else s.Process.name()): s.SimpleAudioVolume
            for s in found}


class TestNeverInTests:
    def test_the_suite_never_lowers_real_apps(self, monkeypatch):
        monkeypatch.setenv("EL_FAGER_TEST_MODE", "1")
        assert ducking._enabled() is False


class TestDuck:
    def test_other_apps_drop_to_a_fraction_while_listening(self, sessions):
        with ducking.ducked():
            assert sessions["Spotify.exe"].level == pytest.approx(0.8 * ducking.DUCK_TO)
            assert sessions["chrome.exe"].level == pytest.approx(1.0 * ducking.DUCK_TO)

    def test_el_fagers_own_voice_and_system_sounds_are_left_alone(self, sessions):
        with ducking.ducked():
            assert sessions["pythonw.exe"].level == 0.6
            assert sessions["system"].level == 1.0

    def test_every_app_is_put_back_exactly_as_it_was(self, sessions):
        with ducking.ducked():
            pass
        assert sessions["Spotify.exe"].level == 0.8
        assert sessions["chrome.exe"].level == 1.0

    def test_they_come_back_even_when_recording_fails(self, sessions):
        with pytest.raises(RuntimeError):
            with ducking.ducked():
                raise RuntimeError("mic unplugged")
        assert sessions["Spotify.exe"].level == 0.8

    def test_a_volume_changed_by_hand_meanwhile_is_left_as_set(self, sessions):
        with ducking.ducked():
            sessions["chrome.exe"].SetMasterVolume(0.4, None)   # turned down by hand
        assert sessions["chrome.exe"].level == 0.4
        assert sessions["Spotify.exe"].level == 0.8

    def test_without_audio_control_listening_still_works(self, monkeypatch):
        monkeypatch.setattr(ducking, "_enabled", lambda: True)
        def broken():
            raise OSError("no audio endpoint")
        monkeypatch.setattr(ducking, "_sessions", broken)
        with ducking.ducked():
            pass                       # nothing raised: ducking is never a gate

    def test_it_can_be_switched_off_in_settings(self, sessions, monkeypatch):
        monkeypatch.setattr(ducking, "_enabled", lambda: False)
        with ducking.ducked():
            assert sessions["Spotify.exe"].level == 0.8

