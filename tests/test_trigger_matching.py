"""Tool-group and model routing match on word boundaries, not substrings.

Plain `kw in msg` fired groups on fragments of unrelated words, which cost
latency and money on every turn that tripped one: a bigger tool schema shipped
to the model, and in the model router's case the expensive model chosen for an
ordinary question.

The risk in fixing it is the opposite failure — silently narrowing what El
Fager can reach. TestNothingStoppedFiring is the guard against that, and it
covers every trigger in the table rather than a sample.
"""
import pytest

from core.brain import (
    _CORE_NAMES,
    _GROUP_RE,
    _GROUP_TRIGGERS,
    _TOOL_GROUP_NAMES,
    _boundaried,
    _select_tools,
)

CORE_ONLY = len(_CORE_NAMES)


class TestFalsePositivesAreGone:
    @pytest.mark.parametrize("phrase,fragment,group", [
        ("is my android phone charged", "roi", "bizmath"),
        ("display my screen", "play", "media"),
        ("i am sleeping now", "ping", "network"),
    ])
    def test_a_fragment_inside_a_word_no_longer_fires_its_group(
            self, phrase, fragment, group):
        assert fragment in phrase, "the test phrase no longer contains the fragment"
        assert not _GROUP_RE[group].search(phrase)

    def test_they_ship_the_core_schema_and_nothing_more(self):
        for phrase in ("is my android phone charged",
                       "display my screen",
                       "i am sleeping now"):
            assert len(_select_tools(phrase)) == CORE_ONLY


class TestNothingStoppedFiring:
    """Every trigger in the table, not a sample of them. A boundary rule that
    quietly stopped a group activating would take tools away from the brain
    with no error to show for it."""

    @pytest.mark.parametrize("group,keyword", [
        (g, k) for g, kws in _GROUP_TRIGGERS.items() for k in kws
    ])
    def test_each_trigger_still_activates_its_group(self, group, keyword):
        assert _GROUP_RE[group].search(f"please {keyword} now")

    @pytest.mark.parametrize("group,keyword", [
        (g, k) for g, kws in _GROUP_TRIGGERS.items() for k in kws
    ])
    def test_each_trigger_still_selects_its_tools(self, group, keyword):
        selected = {t["name"] for t in _select_tools(f"please {keyword} now")}
        assert _TOOL_GROUP_NAMES[group] <= selected


class TestPunctuationEdgedTriggers:
    """Seven triggers begin or end on punctuation or a space. A blanket \\b
    would have stopped all seven matching, which is why the assertions are
    applied per edge."""

    @pytest.mark.parametrize("phrase,group", [
        ("ctrl+c to copy that", "mouse"),
        ("send a wa message to omar", "messaging"),
        ("open the file.exe", "files"),
        ("check my bill for this month", "finance"),
        ("make a qr code", "dev_utils"),
        ("unzip the archive.zip", "archive"),
    ])
    def test_they_still_match(self, phrase, group):
        assert _GROUP_RE[group].search(phrase)


class TestModelRouting:
    def _brain(self):
        from core.brain import Brain
        b = Brain.__new__(Brain)
        b._model, b._fast_model, b._fast_path_enabled = "full", "fast", True
        return b

    @pytest.mark.parametrize("phrase", [
        "measure the room",      # contains "sure"
        "my eyes hurt",          # contains "yes"
        "the yeast is proofing",  # contains "yea"
    ])
    def test_a_word_containing_a_confirmation_does_not_buy_the_full_model(
            self, phrase):
        assert self._brain()._select_model(phrase) == "fast"

    @pytest.mark.parametrize("phrase", [
        "yes", "yeah", "sure", "confirm", "go ahead", "send it", "cancel",
    ])
    def test_a_real_confirmation_still_does(self, phrase):
        assert self._brain()._select_model(phrase) == "full"

    @pytest.mark.parametrize("phrase", [
        "analyze this", "analysis please", "summarise it", "summary please",
        "what is the strategy", "explain why",
    ])
    def test_stem_hints_still_reach_their_longer_forms(self, phrase):
        # _COMPLEX_HINTS holds stems ("analyz", "summar", "strateg") on
        # purpose, so those must stay open-ended at the trailing edge.
        assert self._brain()._select_model(phrase) == "full"


class TestBoundaryBuilder:
    def test_a_word_gets_both_edges(self):
        pattern = _boundaried(["roi"])
        assert pattern.search("my roi is good")
        assert not pattern.search("android")

    def test_a_phrase_ending_in_punctuation_keeps_its_tail_open(self):
        assert _boundaried(["ctrl+"]).search("press ctrl+c")

    def test_a_phrase_starting_in_punctuation_keeps_its_head_open(self):
        assert _boundaried([".exe"]).search("run setup.exe")

    def test_trailing_false_leaves_a_stem_open(self):
        assert _boundaried(["summar"], trailing=False).search("summarise this")
        assert not _boundaried(["summar"]).search("summarise this")

    def test_matching_ignores_case(self):
        assert _boundaried(["roi"]).search("What is my ROI")
