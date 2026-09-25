"""Sonnet 5 for the job hunt, Opus 5 for anything aimed at the Big 4 -- the
applications that matter most -- and nothing spent before Mo's CV is in."""
from unittest.mock import MagicMock, patch

import pytest

from core.career import claude, interview, pipeline, profile, referrals, scorer, store, tailor


@pytest.fixture(autouse=True)
def _career_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DIR", tmp_path / "career")


def _model_used(fn):
    with patch.object(claude, "_get_client") as client:
        client.return_value.messages.create.return_value = MagicMock(
            stop_reason="end_turn",
            content=[MagicMock(type="text", text='{"score": 70, "fit": "", "missing": [], '
                                                 '"level": "entry", "in_egypt": true, '
                                                 '"subject": "S", "body": "B", "note": "N", '
                                                 '"message": "M"}')])
        fn()
    return client.return_value.messages.create.call_args.kwargs["model"]


class TestModels:
    @pytest.mark.parametrize("tier,model", [
        ("big4", "claude-opus-5"), ("top", "claude-sonnet-5"), ("", "claude-sonnet-5")])
    def test_scoring_and_letters(self, tier, model):
        job = {"title": "Analyst", "company": "X", "tier": tier}
        assert _model_used(lambda: scorer.score(job, "profile")) == model
        assert _model_used(lambda: tailor.draft(job, "profile", "email")) == model

    def test_interview_prep_for_a_big4_firm_uses_opus(self):
        with patch("core.agents.research_agent.ResearchAgent.run", return_value=""):
            assert _model_used(lambda: interview.prep("PwC")) == "claude-opus-5"
            assert _model_used(lambda: interview.prep("Fawry")) == "claude-sonnet-5"

    def test_referral_notes_follow_the_persons_firm(self):
        person = {"name": "A", "headline": "", "company": "KPMG", "url": "u"}
        assert _model_used(lambda: referrals.draft(person)) == "claude-opus-5"
        assert _model_used(lambda: referrals.draft({**person, "company": "Valeo"})) == "claude-sonnet-5"


class TestDefaults:
    def test_twenty_a_day(self):
        assert store.settings()["daily_target"] == 20


class TestNothingSpentBeforeTheCv:
    def test_no_jobs_are_scored_or_drafted(self):
        with patch("core.career.sources.gather") as gather, \
             patch.object(scorer, "score") as score, \
             patch.object(pipeline, "_nightly_extras", return_value="") as extras, \
             patch.object(pipeline, "_notify"):
            out = pipeline.prepare_batch()
        gather.assert_not_called()
        score.assert_not_called()
        extras.assert_called_once_with(store.settings(), referrals=False)
        assert out.startswith("No CV imported yet")

    def test_programme_deadlines_are_still_watched(self, monkeypatch):
        from core.career import programmes
        checked = []
        monkeypatch.setattr(programmes, "check_all", lambda: checked.append(1) or "")
        with patch.object(referrals, "find") as find:
            pipeline._nightly_extras(store.settings(), referrals=False)
        assert checked == [1]
        find.assert_not_called()
