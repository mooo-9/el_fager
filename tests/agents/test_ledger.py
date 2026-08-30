import json

import pytest

from core.agents import ledger


@pytest.fixture(autouse=True)
def ledger_in_tmp(tmp_path, monkeypatch):
    path = tmp_path / "agent_runs.jsonl"
    monkeypatch.setattr("core.agents.ledger._LEDGER_PATH", path)
    return path


def test_record_writes_one_json_line(ledger_in_tmp):
    ledger.record("Sage", "research brokers", "pass", duration_s=1.2, result="done")
    entry = json.loads(ledger_in_tmp.read_text(encoding="utf-8").strip())
    assert entry["callsign"] == "Sage"
    assert entry["verdict"] == "pass"


def test_record_never_raises_on_a_broken_path(monkeypatch, tmp_path):
    monkeypatch.setattr("core.agents.ledger._LEDGER_PATH", tmp_path / "x" / "y" / "z")
    monkeypatch.setattr("pathlib.Path.mkdir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    ledger.record("Sage", "t", "pass")  # must not raise


def test_roster_status_counts_pass_rate():
    ledger.record("Sage", "a", "pass")
    ledger.record("Sage", "b", "fail")
    ledger.record("Argus", "c", "pass")
    stats = ledger.roster_status()
    assert stats["Sage"]["runs"] == 2
    assert stats["Sage"]["pass_rate"] == 50
    assert stats["Argus"]["pass_rate"] == 100


def test_recent_filters_by_callsign():
    ledger.record("Sage", "a", "pass")
    ledger.record("Argus", "b", "pass")
    assert [e["callsign"] for e in ledger.recent("Sage")] == ["Sage"]


def test_corrupt_lines_are_skipped(ledger_in_tmp):
    ledger.record("Sage", "a", "pass")
    with ledger_in_tmp.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    assert ledger.roster_status()["Sage"]["runs"] == 1


def test_active_runs_tracks_work_in_flight():
    token = ledger.start_run("Sage", "research brokers", "voice")
    assert [r["callsign"] for r in ledger.active_runs()] == ["Sage"]
    ledger.finish_run(token)
    assert ledger.active_runs() == []


def test_format_report_handles_an_empty_ledger():
    assert "No agent has run" in ledger.format_report()
