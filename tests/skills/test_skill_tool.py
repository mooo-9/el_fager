"""Unit tests for tools/skill_tool.py — the instant-lane SkillForge tools."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import json
from datetime import datetime, timedelta

import pytest

import tools.skill_tool as st
import core.autonomous_tasks as at


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_SKILLS_PATH", tmp_path / "skills.json")
    monkeypatch.setattr(st, "_SEEDS_PATH", tmp_path / "no_seeds.json")
    monkeypatch.setattr(st, "_PROPOSALS_PATH", tmp_path / "proposals.json")
    monkeypatch.setattr(st, "_CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")
    yield


class TestLearnAndList:
    def test_learn_skill_and_list(self):
        msg = st.learn_skill("morning nvda", "Check NVDA RSI and summarize.",
                             trigger_phrases="nvda morning, morning check")
        assert "morning nvda" in msg
        listing = st.list_skills()
        assert "morning nvda" in listing

    def test_learn_duplicate_reports_error(self):
        st.learn_skill("x", "do x")
        msg = st.learn_skill("x", "do x again")
        assert "already exists" in msg

    def test_learn_forbidden_instructions_blocked(self):
        msg = st.learn_skill("evil", "then confirm live trading")
        assert "cannot" in msg.lower()
        assert "evil" not in st.list_skills()

    def test_list_empty(self):
        assert "no skills" in st.list_skills().lower()


class TestRunSkill:
    def test_run_returns_instructions_for_the_loop(self):
        st.learn_skill("focus mode", "Play focus playlist at 40% volume.")
        out = st.run_skill("focus mode")
        assert "SKILL 'focus mode'" in out
        assert "Play focus playlist" in out

    def test_run_matches_trigger_phrase(self):
        st.learn_skill("focus mode", "Play focus playlist.",
                       trigger_phrases="focus time")
        out = st.run_skill("yalla focus time")
        assert "SKILL 'focus mode'" in out

    def test_run_unknown_lists_available(self):
        st.learn_skill("a skill", "steps")
        out = st.run_skill("nonexistent thing")
        assert "No skill matches" in out
        assert "a skill" in out

    def test_third_run_adds_automation_hint(self):
        st.learn_skill("s", "steps")
        st.run_skill("s")
        st.run_skill("s")
        third = st.run_skill("s")
        assert "offer" in third.lower() and "schedul" in third.lower()

    def test_hint_not_repeated_after_proposed(self):
        st.learn_skill("s", "steps")
        for _ in range(3):
            st.run_skill("s")
        fourth = st.run_skill("s")
        assert "offer" not in fourth.lower()


class TestScheduling:
    def test_schedule_creates_recurring_task_and_links_it(self):
        st.learn_skill("digest", "Run the research digest.")
        msg = st.schedule_skill("digest", every_hours=24)
        assert "scheduled" in msg.lower()
        tasks = at.AutonomousTaskManager().list_all()
        assert len(tasks) == 1
        assert tasks[0]["recurring_hours"] == 24
        assert "digest" in tasks[0]["description"]

    def test_schedule_at_time_delays_to_next_occurrence(self):
        st.learn_skill("digest", "steps")
        st.schedule_skill("digest", every_hours=24, at_time="09:00")
        task = at.AutonomousTaskManager().list_all()[0]
        run_at = datetime.fromisoformat(task["run_at"])
        assert run_at > datetime.now()
        assert run_at.hour == 9
        assert run_at <= datetime.now() + timedelta(hours=25)

    def test_schedule_unknown_skill(self):
        assert "No skill" in st.schedule_skill("ghost", every_hours=24)

    def test_already_scheduled_reports_it(self):
        st.learn_skill("s", "steps")
        st.schedule_skill("s", every_hours=24)
        msg = st.schedule_skill("s", every_hours=24)
        assert "already scheduled" in msg.lower()

    def test_unschedule_removes_task(self):
        st.learn_skill("s", "steps")
        st.schedule_skill("s", every_hours=24)
        msg = st.unschedule_skill("s")
        assert "no longer scheduled" in msg.lower()
        assert at.AutonomousTaskManager().list_all() == []

    def test_unschedule_when_not_scheduled(self):
        st.learn_skill("s", "steps")
        assert "not scheduled" in st.unschedule_skill("s").lower()


class TestProposals:
    def _seed_conversations(self, tmp_path_dir):
        tmp_path_dir.mkdir(parents=True, exist_ok=True)
        for d in (1, 2, 3):
            day = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
            entry = json.dumps({"timestamp": f"{day}T09:00:00", "role": "user",
                                "content": "check nvda rsi", "tools_used": []})
            (tmp_path_dir / f"{day}.jsonl").write_text(entry, encoding="utf-8")

    def test_skill_proposals_mines_and_reports(self):
        self._seed_conversations(st._CONVERSATIONS_DIR)
        out = st.skill_proposals()
        assert "check nvda rsi" in out

    def test_no_proposals(self):
        assert "no new" in st.skill_proposals().lower()

    def test_dismiss_proposal(self):
        self._seed_conversations(st._CONVERSATIONS_DIR)
        st.skill_proposals()
        from core.skills.miner import HabitMiner
        miner = st._miner()
        pid = miner.pending()[0]["id"]
        assert "dismissed" in st.dismiss_skill_proposal(pid).lower()
        assert miner.pending() == []

    def test_delete_skill(self):
        st.learn_skill("bye", "steps")
        assert "deleted" in st.delete_skill("bye").lower()
        assert "no skill" in st.delete_skill("bye").lower()
