"""Whisper's hint sentence carries the names Mo actually says.

Whisper continues the style and vocabulary of the text before the audio, so a
name in the hint is a name it can spell. Without them, on 2026-09-13
"Estanna" came back as "stand" and Fares Sokar as "Ferris Sokhar", and on
09-05 Tamer Hosny as "Tamir Hosni".
"""
import json
import os
import time

import pytest

from core import voice_in


@pytest.fixture
def files(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    contacts = tmp_path / "contacts.json"
    settings = tmp_path / "settings.json"
    profile.write_text(json.dumps({"name": "Mo", "full_name": "Mohamed"}), encoding="utf-8")
    contacts.write_text(json.dumps({"Test User": "+1", "Mo": "+2"}), encoding="utf-8")
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(voice_in, "_PROFILE", profile)
    monkeypatch.setattr(voice_in, "_CONTACTS", contacts)
    monkeypatch.setattr(voice_in, "_SETTINGS", settings)
    monkeypatch.setattr(voice_in, "_BIAS_CACHE", None)
    return {"profile": profile, "contacts": contacts, "settings": settings}


def _vocabulary(files, names):
    files["settings"].write_text(json.dumps({"voice_vocabulary": names}), encoding="utf-8")
    # A later mtime than the last read, even on a coarse filesystem clock.
    later = time.time() + 5
    os.utime(files["settings"], (later, later))


class TestVocabulary:
    def test_every_name_is_in_the_hint_as_written(self, files):
        names = ["Estanna", "Fares Sokar", "Tawsen", "Tamer Hosny", "Shehab", "Erzaa"]
        _vocabulary(files, names)
        prompt = voice_in._bias_prompt()
        for name in names:
            assert name in prompt

    def test_the_hint_still_reads_as_something_mo_would_say(self, files):
        _vocabulary(files, ["Estanna", "Fares Sokar"])
        prompt = voice_in._bias_prompt()
        assert prompt.startswith("Hey El Fager")
        assert "Mo" in prompt

    def test_blanks_and_repeats_are_dropped(self, files):
        _vocabulary(files, ["Shehab", "  ", "shehab", "Tawsen", ""])
        prompt = voice_in._bias_prompt()
        assert prompt.lower().count("shehab") == 1
        assert ", ," not in prompt

    def test_an_edit_applies_without_a_restart(self, files):
        _vocabulary(files, ["Shehab"])
        assert "Shehab" in voice_in._bias_prompt()
        _vocabulary(files, ["Erzaa"])
        prompt = voice_in._bias_prompt()
        assert "Erzaa" in prompt and "Shehab" not in prompt

    def test_a_long_list_cannot_crowd_out_the_audio(self, files):
        _vocabulary(files, [f"Artist Number {n}" for n in range(200)])
        prompt = voice_in._bias_prompt()
        assert len(prompt) <= voice_in.BIAS_PROMPT_MAX_CHARS
        assert "Artist Number 0" in prompt          # the start of the list is kept

    def test_no_list_leaves_the_hint_as_it_was(self, files):
        prompt = voice_in._bias_prompt()
        assert prompt == ("Hey El Fager, remind Mo, Mohamed about the review at 4 PM, "
                          "check my Todoist and my Obsidian notes, and tell me what's on my calendar.")

    def test_a_broken_settings_file_leaves_the_hint_as_it_was(self, files):
        files["settings"].write_text("{not json", encoding="utf-8")
        assert voice_in._bias_prompt().startswith("Hey El Fager, remind Mo")

    def test_the_hint_is_not_rebuilt_while_nothing_changed(self, files, monkeypatch):
        _vocabulary(files, ["Shehab"])
        voice_in._bias_prompt()
        reads = []
        real = voice_in._read_json
        monkeypatch.setattr(voice_in, "_read_json", lambda path: reads.append(path) or real(path))
        voice_in._bias_prompt()
        assert reads == []
