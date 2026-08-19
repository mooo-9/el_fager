"""The Cockpit's transcript panel.

Lives under tests/ui because it needs the qapp fixture, and because importing
a Qt module from the root tests directory has already been shown to reorder
initialisation enough to crash an unrelated Qt test later in the run.
"""
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QLabel


class TestTheCockpitUsesIt:
    def test_the_transcript_panel_renders_labels_and_bodies(self, qapp):
        from ui.cockpit import CockpitWindow

        w = CockpitWindow(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        w.set_wake_listener(None)
        w._set_transcript("Lead line.\n\n**Academic:** two left\n\n**Today:** none")

        rows = [w._reading_layout.itemAt(i).widget().text()
                for i in range(w._reading_layout.count())
                if isinstance(w._reading_layout.itemAt(i).widget(), QLabel)]
        assert "ACADEMIC" in rows, "the label was not lifted into a kicker"
        assert "two left" in rows
        assert not any("**" in r for r in rows), "raw markdown reached a label"
        w.close()

    def test_setting_it_twice_replaces_rather_than_stacks(self, qapp):
        from ui.cockpit import CockpitWindow

        w = CockpitWindow(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        w.set_wake_listener(None)
        w._set_transcript("**One:** first")
        first = w._reading_layout.count()
        w._set_transcript("**Two:** second")
        assert w._reading_layout.count() == first, "old rows were left behind"
        w.close()
