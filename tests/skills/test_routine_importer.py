"""Tests for RoutineImporter and the import_routines / sync_skills_to_claude
tools — calendar/gym sources are injected; no network, no real data dirs."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

import tools.skill_tool as st
import core.autonomous_tasks as at
from core.skills.importer import RoutineImporter, _prep_time


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_SKILLS_PATH", tmp_path / "skills.json")
    monkeypatch.setattr(st, "_SEEDS_PATH", tmp_path / "no_seeds.json")
    monkeypatch.setattr(st, "_PROPOSALS_PATH", tmp_path / "proposals.json")
    monkeypatch.setattr(st, "_CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(st, "_CLAUDE_SKILLS_DIR", tmp_path / ".claude" / "skills")
    monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")
    yield


def _events(*specs):
    """specs: (title, date, time)"""
    return [{"title": t, "date": d, "time": tm} for t, d, tm in specs]


class TestRoutineImporter:
    def test_recurring_event_becomes_daily_candidate(self):
        imp = RoutineImporter(
            calendar_fn=lambda: _events(
                ("Standup", "2026-07-07", "10:00"),
                ("Standup", "2026-07-08", "10:00"),
                ("Standup", "2026-07-09", "10:00"),
                ("Standup", "2026-07-10", "10:00"),
            ),
            gym_program_fn=lambda: {},
        )
        cands = imp.find_candidates()
        assert len(cands) == 1
        c = cands[0]
        assert c["name"] == "prep: standup"
        assert c["every_hours"] == 24
        assert c["at_time"] == "09:30"  # 30 min before

    def test_twice_in_two_weeks_is_weekly(self):
        imp = RoutineImporter(
            calendar_fn=lambda: _events(
                ("Team Sync", "2026-07-07", "14:00"),
                ("Team Sync", "2026-07-14", "14:00"),
            ),
            gym_program_fn=lambda: {},
        )
        c = imp.find_candidates()[0]
        assert c["every_hours"] == 168
        assert c["at_time"] == "13:30"

    def test_one_off_event_ignored(self):
        imp = RoutineImporter(
            calendar_fn=lambda: _events(("Dentist", "2026-07-08", "11:00")),
            gym_program_fn=lambda: {},
        )
        assert imp.find_candidates() == []

    def test_all_day_events_ignored(self):
        imp = RoutineImporter(
            calendar_fn=lambda: _events(
                ("Vacation", "2026-07-07", None),
                ("Vacation", "2026-07-08", None),
            ),
            gym_program_fn=lambda: {},
        )
        assert imp.find_candidates() == []

    def test_gym_program_becomes_candidate(self):
        imp = RoutineImporter(
            calendar_fn=lambda: [],
            gym_program_fn=lambda: {"split": {"monday": "push", "thursday": "pull"}},
        )
        cands = imp.find_candidates()
        assert len(cands) == 1
        assert cands[0]["name"] == "gym day briefing"

    def test_sources_failing_yield_nothing(self):
        imp = RoutineImporter(calendar_fn=lambda: [], gym_program_fn=lambda: {})
        assert imp.find_candidates() == []

    def test_prep_time_floors_at_six_am(self):
        assert _prep_time("06:10") == "06:00"
        assert _prep_time("14:00") == "13:30"


class TestImportRoutinesTool:
    def _patch_importer(self, monkeypatch, candidates):
        class FakeImporter:
            def find_candidates(self):
                return candidates
        import core.skills.importer as imp_mod
        monkeypatch.setattr(imp_mod, "RoutineImporter", lambda: FakeImporter())

    def test_import_creates_and_schedules(self, monkeypatch):
        self._patch_importer(monkeypatch, [{
            "name": "prep: standup", "instructions": "1) check calendar",
            "trigger_phrases": ["prep for standup"], "every_hours": 24,
            "at_time": "09:30", "origin": "calendar: 'Standup' on 4 days",
        }])
        msg = st.import_routines()
        assert "Imported and scheduled 1 routines" in msg
        listing = st.list_skills()
        assert "prep: standup" in listing
        assert "[scheduled]" in listing

    def test_import_skips_existing_names(self, monkeypatch):
        st.learn_skill("prep: standup", "already mine")
        self._patch_importer(monkeypatch, [{
            "name": "prep: standup", "instructions": "1) check calendar",
            "trigger_phrases": [], "every_hours": 24,
            "at_time": "09:30", "origin": "calendar",
        }])
        msg = st.import_routines()
        assert "Already existed" in msg

    def test_no_candidates_message(self, monkeypatch):
        self._patch_importer(monkeypatch, [])
        assert "No recurring routines" in st.import_routines()


class TestSyncSkillsToClaude:
    def test_sync_writes_skill_md(self, tmp_path):
        st.learn_skill("morning nvda", "Check NVDA RSI and summarize.",
                       trigger_phrases="nvda morning")
        msg = st.sync_skills_to_claude()
        assert "Synced 1 skills" in msg
        md = (tmp_path / ".claude" / "skills" / "fager-morning-nvda" / "SKILL.md")
        assert md.exists()
        text = md.read_text(encoding="utf-8")
        assert "run my skill 'morning nvda'" in text
        assert "Check NVDA RSI" in text

    def test_sync_removes_stale_exports(self, tmp_path):
        st.learn_skill("temp skill", "do a thing")
        st.sync_skills_to_claude()
        st.delete_skill("temp skill")
        msg = st.sync_skills_to_claude()
        assert "removed 1 stale" in msg
        assert not (tmp_path / ".claude" / "skills" / "fager-temp-skill").exists()

    def test_sync_never_touches_bridge_skill(self, tmp_path):
        bridge = tmp_path / ".claude" / "skills" / "fager"
        bridge.mkdir(parents=True)
        (bridge / "SKILL.md").write_text("bridge", encoding="utf-8")
        st.sync_skills_to_claude()
        assert (bridge / "SKILL.md").read_text(encoding="utf-8") == "bridge"
