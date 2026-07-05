"""Tests for core/dashboard.py — snapshot assembly and the read-only server."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import urllib.request
from http.server import ThreadingHTTPServer
import threading

import pytest

import core.dashboard as db


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # all data/ reads resolve into tmp
    yield tmp_path


class TestSnapshot:
    def test_snapshot_has_all_sections_on_empty_disk(self, isolated):
        s = db.build_snapshot()
        for key in ("generated_at", "mission", "cost", "skills", "tasks",
                    "trading"):
            assert key in s
        assert s["mission"]["active"] is False
        assert s["cost"]["today_usd"] == 0

    def test_snapshot_reflects_trades(self, isolated):
        (isolated / "data").mkdir()
        (isolated / "data" / "trades.json").write_text(json.dumps([
            {"symbol": "NVDA", "side": "buy", "qty": 2, "price": 100.5,
             "timestamp": "2026-07-05T10:00:00", "conviction": 78.0},
        ]), encoding="utf-8")
        s = db.build_snapshot()
        assert s["trading"]["total_trades"] == 1
        assert s["trading"]["recent"][0]["symbol"] == "NVDA"

    def test_snapshot_never_contains_secrets(self, isolated):
        blob = json.dumps(db.build_snapshot()).lower()
        for word in ("api_key", "secret", "token", "password"):
            assert word not in blob


class TestServer:
    @pytest.fixture
    def server(self, isolated):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), db._Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()

    def test_api_status_serves_json(self, server):
        with urllib.request.urlopen(f"{server}/api/status", timeout=5) as r:
            assert r.status == 200
            data = json.loads(r.read().decode("utf-8"))
        assert "cost" in data and "mission" in data

    def test_root_serves_html(self, server):
        with urllib.request.urlopen(f"{server}/", timeout=5) as r:
            body = r.read().decode("utf-8")
        assert "EL FAGER" in body

    def test_unknown_path_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{server}/admin", timeout=5)
        assert exc.value.code == 404

    def test_post_not_allowed(self, server):
        req = urllib.request.Request(f"{server}/api/status", data=b"{}",
                                     method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 501  # BaseHTTPRequestHandler: no do_POST


class TestStartDashboard:
    def test_disabled_by_settings(self, isolated):
        (isolated / "data").mkdir()
        (isolated / "data" / "settings.json").write_text(
            json.dumps({"dashboard_enabled": False}), encoding="utf-8")
        assert db.start_dashboard() is None

    def test_starts_and_serves(self, isolated):
        (isolated / "data").mkdir()
        (isolated / "data" / "settings.json").write_text(
            json.dumps({"dashboard_host": "127.0.0.1", "dashboard_port": 0}),
            encoding="utf-8")
        srv = db.start_dashboard()
        assert srv is not None
        port = srv.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status",
                                    timeout=5) as r:
            assert r.status == 200
        srv.shutdown()
