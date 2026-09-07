"""Tests for the Command Center's painted widgets.

The day-arc carries a motion rule worth pinning: it sweeps on first paint
only. A card that keeps animating would breach "UI never breathes".
"""
from ui.widgets import DayArc


class TestDayArc:
    def test_it_sweeps_on_first_paint_only(self, qapp):
        arc = DayArc()
        arc.set_values(900, 2400)
        assert arc._swept is True
        first_timer = arc._timer
        arc.set_values(1200, 2400)          # a later update must not re-animate
        assert arc._timer is first_timer
        arc.deleteLater()

    def test_past_the_target_it_reads_as_over(self, qapp):
        arc = DayArc()
        arc.set_values(2760, 2400)
        assert arc._over is True
        arc.deleteLater()

    def test_on_target_is_not_over(self, qapp):
        arc = DayArc()
        arc.set_values(2400, 2400)
        assert arc._over is False
        arc.deleteLater()

    def test_no_target_never_reads_as_over(self, qapp):
        # an unset goal must not paint the amber warning
        arc = DayArc()
        arc.set_values(1800, 0)
        assert arc._over is False
        arc.deleteLater()

    def test_it_paints_at_every_fill(self, qapp):
        for value, target in ((0, 2400), (900, 2400), (2400, 2400), (2760, 2400)):
            arc = DayArc()
            arc.set_values(value, target)
            arc._progress = 1.0
            assert not arc.grab().isNull()
            arc.deleteLater()
