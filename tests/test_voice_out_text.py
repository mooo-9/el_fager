"""What the TTS is handed, as opposed to what the model wrote.

The voice reads exactly the string it is given, so anything a reader expands
silently has to be expanded first. These pin the two halves of that: the
expansions that must happen, and — more easily broken — the things that must
be left alone. Both regexes here have already shipped a bug that mangled
ordinary text, hence the second group.
"""
import pytest

from core.voice_out import _clean


class TestSpokenExpansions:
    @pytest.mark.parametrize("written,spoken", [
        ("It takes 3-4 hours.", "It takes 3 to 4 hours."),
        ("Coffee w/ milk.", "Coffee with milk."),
        ("Tea w/o sugar.", "Tea without sugar."),
        ("Do you want yes/no?", "Do you want yes or no?"),
        ("Coffee & eggs.", "Coffee and eggs."),
    ])
    def test_it_expands_what_the_eye_reads_silently(self, written, spoken):
        assert _clean(written) == spoken

    @pytest.mark.parametrize("written,fragment", [
        ("Open it, e.g. now.", "for example"),
        ("Open it, i.e. now.", "that is"),
        ("Bring keys, wallet, etc.", "and so on"),
        ("It runs 24/7.", "twenty four seven"),
        ("FYI the gym is shut.", "just so you know"),
        ("Send it ASAP.", "as soon as possible"),
    ])
    def test_abbreviations_become_words(self, written, fragment):
        assert fragment in _clean(written)

    def test_a_dash_becomes_the_pause_it_stood_for(self):
        # Most voices swallow an em dash entirely, losing the beat.
        assert _clean("Review at 4 — gym at 7.") == "Review at 4, gym at 7."

    def test_an_ellipsis_does_not_become_a_stutter(self):
        assert "..." not in _clean("Well... maybe.")


class TestLeftAlone:
    """The expansions are regex substitutions on prose, which is exactly how
    they go wrong. An ISO date really did come out as '2026 to 08 to 17'."""

    @pytest.mark.parametrize("text", [
        "The 2026-08-17 deadline is fixed.",
        "The meeting is at 3:45 PM sharp.",
        "Call +201152215125 now.",
        "Running Python 3.14.4 here.",
        "I moved the draft to tomorrow, so today is just the review.",
        "You have three things left today.",
    ])
    def test_ordinary_text_survives_untouched(self, text):
        assert _clean(text) == text


class TestMarkdownStillStripped:
    @pytest.mark.parametrize("written,spoken", [
        ("Check **the draft**.", "Check the draft."),
        ("Open `config.json`.", "Open config.json."),
        ("## Heading", "Heading"),
    ])
    def test_nothing_symbolic_reaches_the_voice(self, written, spoken):
        assert _clean(written) == spoken
