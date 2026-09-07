"""core/atomic.py — a write either lands whole or not at all.

The failure this exists to prevent: Path.write_text() truncates first, so a
crash mid-write leaves a short file. Every loader here ends in
`except Exception: return {}`, so that file does not raise — trades.json
reports zero trades and the caller believes it.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import atomic


class TestWrite:
    def test_roundtrips(self, tmp_path):
        target = tmp_path / "state.json"
        atomic.write(target, json.dumps({"trades": 3}))
        assert json.loads(target.read_text(encoding="utf-8")) == {"trades": 3}

    def test_replaces_existing_content_entirely(self, tmp_path):
        target = tmp_path / "state.json"
        target.write_text("x" * 500, encoding="utf-8")
        atomic.write(target, "short")
        assert target.read_text(encoding="utf-8") == "short"

    def test_creates_missing_parents(self, tmp_path):
        target = tmp_path / "data" / "nested" / "state.json"
        atomic.write(target, "{}")
        assert target.read_text(encoding="utf-8") == "{}"

    def test_leaves_no_temporary_files(self, tmp_path):
        target = tmp_path / "state.json"
        atomic.write(target, "{}")
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_writes_non_ascii(self, tmp_path):
        """Mo talks to El Fager in Arabic; the logs hold it."""
        target = tmp_path / "state.json"
        payload = json.dumps({"note": "صباح الفجر"}, ensure_ascii=False)
        atomic.write(target, payload)
        assert json.loads(target.read_text(encoding="utf-8"))["note"] == "صباح الفجر"


class TestFailureLeavesTheOldFileIntact:
    """The property the whole module exists for."""

    @staticmethod
    def _explode_on_replace(monkeypatch):
        def boom(*a, **k):
            raise OSError("simulated crash between write and rename")
        monkeypatch.setattr(atomic.os, "replace", boom)

    def test_previous_contents_survive(self, tmp_path, monkeypatch):
        target = tmp_path / "trades.json"
        original = json.dumps([{"symbol": "NVDA", "qty": 2}])
        target.write_text(original, encoding="utf-8")

        self._explode_on_replace(monkeypatch)
        with pytest.raises(OSError):
            atomic.write(target, json.dumps([{"symbol": "NVDA", "qty": 3}]))

        assert target.read_text(encoding="utf-8") == original, \
            "a failed write must not touch the file that was already there"
        assert json.loads(target.read_text(encoding="utf-8"))[0]["qty"] == 2

    def test_no_temporary_file_is_left_behind(self, tmp_path, monkeypatch):
        target = tmp_path / "trades.json"
        target.write_text("[]", encoding="utf-8")

        self._explode_on_replace(monkeypatch)
        with pytest.raises(OSError):
            atomic.write(target, "[1]")

        assert [p.name for p in tmp_path.iterdir()] == ["trades.json"]

    def test_a_target_that_did_not_exist_still_does_not(self, tmp_path, monkeypatch):
        target = tmp_path / "trades.json"
        self._explode_on_replace(monkeypatch)
        with pytest.raises(OSError):
            atomic.write(target, "[]")
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []


class TestCallSitesUseIt:
    def test_no_bare_write_text_survives_in_shipped_code(self):
        """A new Path.write_text() would silently reintroduce the window."""
        import pathlib
        offenders = []
        root = pathlib.Path(__file__).resolve().parent.parent
        for folder in ("core", "tools", "ui"):
            for path in (root / folder).rglob("*.py"):
                if path.name == "atomic.py":
                    continue
                for n, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), 1):
                    if ".write_text(" in line:
                        offenders.append(f"{path.relative_to(root)}:{n}")
        assert not offenders, (
            "use core.atomic.write instead of Path.write_text: "
            + ", ".join(offenders))
