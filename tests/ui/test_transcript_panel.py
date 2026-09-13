"""The Cockpit's transcript panel.

Lives under tests/ui because it needs the qapp fixture, and because importing
a Qt module from the root tests directory has already been shown to reorder
initialisation enough to crash an unrelated Qt test later in the run.
"""
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QLabel


def _cockpit():
    from ui.cockpit import CockpitWindow
    w = CockpitWindow(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    w.set_wake_listener(None)
    return w


def _rows(w):
    return [label.text() for label in w._reading_box.findChildren(QLabel)]


class TestTheCockpitUsesIt:
    def test_the_transcript_panel_renders_labels_and_bodies(self, qapp):
        w = _cockpit()
        w.on_state_update("processing", "brief me", "")
        w.on_state_update("speaking", "brief me",
                          "Lead line.\n\n**Academic:** two left\n\n**Today:** none")
        rows = _rows(w)
        assert "ACADEMIC" in rows, "the label was not lifted into a kicker"
        assert "two left" in rows
        assert not any("**" in r for r in rows), "raw markdown reached a label"
        w.close()

    def test_the_answer_landing_replaces_rather_than_stacks(self, qapp):
        w = _cockpit()
        w.on_state_update("processing", "brief me", "")
        w.on_state_update("speaking", "brief me", "**One:** first")
        first = len(_rows(w))
        w.on_state_update("speaking", "brief me", "**Two:** second")
        assert len(_rows(w)) == first, "old rows were left behind"
        assert "first" not in _rows(w)
        w.close()
