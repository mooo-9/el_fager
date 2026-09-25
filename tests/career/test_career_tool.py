from unittest.mock import patch

import pytest

from core.career import pipeline, profile, store
from tools import career_tool

_TOOLS = ["prepare_applications", "review_applications", "approve_applications",
          "application_status", "check_application_replies", "import_cv",
          "set_application_answer", "application_settings", "interview_prep"]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    import core.autonomous_tasks as at
    monkeypatch.setattr(store, "DIR", tmp_path / "career")
    monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")


class TestSettings:
    def test_live_mode_needs_a_cv(self):
        assert career_tool.application_settings(live=True).startswith("Error: import your CV")
        assert store.settings()["live"] is False

    def test_live_mode_with_a_cv(self, tmp_path):
        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF")
        profile.save({"cv_path": str(cv)})
        assert career_tool.application_settings(live=True).startswith("Mode: LIVE")

    def test_with_no_input_it_only_shows(self):
        out = career_tool.application_settings()
        assert out.startswith("Mode: practice") and "Nightly job hunt: off" in out

    def test_nightly_creates_one_recurring_task_and_removes_it(self):
        from core.autonomous_tasks import AutonomousTaskManager
        out = career_tool.application_settings(nightly=True)
        career_tool.application_settings(nightly=True)            # twice: still one
        tasks = AutonomousTaskManager().list_all()
        assert len(tasks) == 1 and tasks[0]["recurring_hours"] == 24
        assert "prepare_applications" in tasks[0]["description"]
        assert "Nightly job hunt: on" in out
        career_tool.application_settings(nightly=False)
        assert AutonomousTaskManager().list_all() == []


class TestPrepare:
    def test_runs_in_the_background_once(self):
        with patch.object(pipeline, "start_in_background", side_effect=[True, False]):
            assert career_tool.prepare_applications().startswith("Preparing today's batch")
            assert career_tool.prepare_applications().startswith("The pipeline is already running")


class TestInterviewPrep:
    def test_uses_the_tracked_posting_and_research(self):
        from core.career import tracker
        tracker.add({"url": "https://x/1", "title": "Technology Consultant", "company": "EY",
                     "company_key": "EY", "status": "interview", "description": "SQL, Excel"})
        with patch("core.agents.research_agent.ResearchAgent.run", return_value="EY uses HireVue"), \
             patch("core.career.claude.ask", return_value="PREP SHEET") as ask:
            assert career_tool.interview_prep("EY") == "PREP SHEET"
        prompt = ask.call_args.args[0]
        assert "Role: Technology Consultant" in prompt
        assert "SQL, Excel" in prompt and "EY uses HireVue" in prompt


class TestBrainWiring:
    def test_every_tool_is_defined_and_in_the_jobs_group(self):
        from core.brain import _SLIM_TOOLS, _TOOL_GROUP_NAMES
        names = {t["name"] for t in _SLIM_TOOLS}
        assert set(_TOOLS) <= names
        assert set(_TOOLS) <= _TOOL_GROUP_NAMES["jobs"]

    @pytest.mark.parametrize("message", [
        "approve my applications", "how are my job applications going",
        "import my cv from the desktop", "prepare me for my interview at PwC",
        "my military status is exempted", "run the nightly job hunt",
    ])
    def test_career_talk_offers_the_tools(self, message):
        from core.brain import _select_tools
        assert set(_TOOLS) <= {t["name"] for t in _select_tools(message)}

    @pytest.mark.parametrize("name,args", [
        ("application_status", {}),
        ("approve_applications", {"skip": ["a1"]}),
        ("set_application_answer", {"question": "gpa", "answer": "3.4"}),
        ("interview_prep", {"company": "PwC", "role": "Graduate"}),
    ])
    def test_dispatch_reaches_the_tool(self, name, args):
        from core.brain import Brain
        with patch.object(career_tool, name, return_value="ok") as fn:
            assert Brain(profile={})._dispatch_tool(name, args) == "ok"
        fn.assert_called_once_with(**args)


class TestOnlyMoApproves:
    """Approving sends a whole batch under Mo's name. The nightly job hunt is a
    background brain turn: it may prepare the batch, never approve it."""

    def _turn(self, history):
        from tests.test_staged_confirm_by_voice import _end, _run_turn, _tool_use
        with patch.object(career_tool, "approve_applications", return_value="Approved 3") as fn:
            results, _ = _run_turn(__import__("core.brain", fromlist=["Brain"]).Brain(profile={}),
                                   "approve them", [_tool_use("approve_applications"), _end()],
                                   history=history)
        return fn, results

    def test_a_background_turn_cannot_approve(self):
        fn, results = self._turn(history=[])
        fn.assert_not_called()
        assert "NOT APPROVED" in results[-1]

    def test_mos_own_turn_can(self):
        fn, results = self._turn(history=None)
        fn.assert_called_once()
        assert results[-1] == "Approved 3"
