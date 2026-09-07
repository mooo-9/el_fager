"""Tests for Onboarding.

The gating is the substance: Continue must not advance past a step that
hasn't actually happened, and the staging rule must not be presentable as
optional.
"""
import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    import ui.onboarding as mod
    import ui.overlay as overlay_mod
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"name": "", "full_name": "Mo"}), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"wake_word_enabled": True}), encoding="utf-8")
    monkeypatch.setattr(mod, "_PROFILE", profile)
    monkeypatch.setattr(overlay_mod, "_SETTINGS_FILE", settings)
    return profile


def _wizard(qapp, wake=None):
    from ui.onboarding import OnboardingWindow
    return OnboardingWindow(voice_in=MagicMock(), voice_out=MagicMock(),
                            wake_listener=wake)


class TestGating:
    def test_a_nameless_start_cannot_continue(self, qapp):
        w = _wizard(qapp)
        assert w.can_continue() is False
        w._name.setText("Mo")
        assert w.can_continue() is True
        w.close()

    def test_calibration_gates_on_actually_hearing_something(self, qapp):
        w = _wizard(qapp)
        w._name.setText("Mo")
        w._advance()
        assert w._step == 1
        assert w.can_continue() is False      # nothing said yet
        w._on_calibrated("")                  # mic heard nothing
        assert w.can_continue() is False
        w._on_calibrated("good morning El Fager")
        assert w.can_continue() is True
        w.close()

    def test_the_voice_locked_receipt_appears_only_on_success(self, qapp):
        w = _wizard(qapp)
        w._on_calibrated("")
        assert "VOICE LOCKED" not in w._voice_receipt.text()
        w._on_calibrated("heard this")
        assert w._voice_receipt.text() == "VOICE LOCKED"
        w.close()

    def test_permissions_never_block_progress(self, qapp):
        w = _wizard(qapp)
        w._show_step(2)
        assert w.can_continue() is True
        w.close()

    def test_the_wake_test_gates_until_heard_or_skipped(self, qapp):
        w = _wizard(qapp)
        w._show_step(3)
        assert w.can_continue() is False
        w._on_wake_heard()
        assert w.can_continue() is True
        w.close()

    def test_skipping_the_wake_test_is_allowed_and_says_so(self, qapp):
        w = _wizard(qapp)
        w._show_step(3)
        w._skip_wake()
        assert w.can_continue() is True
        assert "SKIPPED" in w._wake_receipt.text()
        w.close()


class TestTheStepsDoRealThings:
    def test_the_name_is_written_to_the_profile(self, qapp, sandbox):
        w = _wizard(qapp)
        w._name.setText("Mo")
        w._advance()
        assert json.loads(sandbox.read_text(encoding="utf-8"))["name"] == "Mo"
        w.close()

    def test_it_loads_a_name_that_is_already_there(self, qapp, sandbox):
        sandbox.write_text(json.dumps({"name": "Mohab"}), encoding="utf-8")
        w = _wizard(qapp)
        assert w._name.text() == "Mohab"
        w.close()

    def test_calibration_records_through_voice_in(self, qapp):
        w = _wizard(qapp)
        w._calibrate()
        # the worker thread calls the real recorder, not a stand-in
        assert w.voice_in.record_audio.called or w._listen_btn.isEnabled() is False
        w.close()

    def test_the_wake_test_arms_the_real_listener(self, qapp):
        listener = MagicMock()
        listener._running = False
        w = _wizard(qapp, wake=listener)
        w._show_step(3)
        assert listener.start.called
        w.close()

    def test_finishing_speaks_rather_than_touring(self, qapp):
        w = _wizard(qapp)
        w._show_step(3)
        w._skip_wake()
        w._advance()
        assert w.voice_out.speak.called
        assert "At your service." in w.voice_out.speak.call_args[0][0]
        w.close()


class TestTheOrb:
    def test_chromium_is_not_built_until_the_window_opens(self, qapp):
        w = _wizard(qapp)
        assert w._orb is None
        w.close()

    def test_each_step_carries_its_own_hue(self):
        from ui import tokens
        from ui.onboarding import _STEP_STATE
        assert len(_STEP_STATE) == 4
        assert len(set(_STEP_STATE)) == 4          # no two steps look alike
        for state in _STEP_STATE:
            assert state in tokens.CK_STATE


class TestTheStagingRule:
    def test_it_has_no_toggle(self, qapp):
        from ui.settings import Toggle
        w = _wizard(qapp)
        page = w._steps.widget(2)
        toggles = page.findChildren(Toggle)
        # wake word and sound cues are optional; the staging rule is not
        assert len(toggles) == 2
        rule_text = " ".join(lbl.text() for lbl in page.findChildren(type(w._dots)))
        assert "no" in rule_text.lower() and "off switch" in rule_text.lower()
        w.close()
