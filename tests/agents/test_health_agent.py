import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def clean_profile(tmp_path, monkeypatch):
    """Redirect data files to a temp directory for each test."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    yield tmp_path


def _make_agent():
    from core.agents.health_agent import HealthAgent
    return HealthAgent()


def test_agent_name():
    agent = _make_agent()
    assert agent.name == "health"


def test_no_profile_returns_setup_prompt():
    agent = _make_agent()
    result = agent.run("log meal: chicken breast 200g")
    assert "profile" in result.lower() or "stats" in result.lower()


def test_setup_profile_from_stats():
    agent = _make_agent()
    result = agent.run("my stats: 22 years old, 75kg, 175cm, goal is bulk")
    assert "3000" in result or "2995" in result or "calorie" in result.lower()
    profile = json.loads(Path("data/health_profile.json").read_text())
    assert profile["age"] == 22
    assert profile["weight_kg"] == 75.0
    assert profile["height_cm"] == 175.0
    assert profile["goal"] == "bulk"
    assert profile["targets"]["protein_g"] == 150.0


def test_override_target():
    agent = _make_agent()
    agent.run("my stats: 22 years old, 75kg, 175cm, goal is bulk")
    result = agent.run("set my daily protein to 200g")
    assert "200" in result
    profile = json.loads(Path("data/health_profile.json").read_text())
    assert profile["overrides"]["protein_g"] == 200.0
