"""Tests for core/dashboard.py — snapshot assembly and the read-only server."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
import threading
import time

import pytest

import core.dashboard as db


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # all data/ reads resolve into tmp
    yield tmp_path


_TOKEN = "test-token-not-a-real-secret"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The limiters are module state shared by every test in the process."""
    db._auth_failures.reset()
    db._commands.reset()
    yield
    db._auth_failures.reset()
    db._commands.reset()


@pytest.fixture
def token(isolated):
    """Give the isolated tmp dir a dashboard token, and hand it back."""
    (isolated / "data").mkdir(exist_ok=True)
    (isolated / "data" / "settings.json").write_text(
        json.dumps({"dashboard_token": _TOKEN}), encoding="utf-8")
    return _TOKEN


def _get(url: str, tok: str | None = None):
    """GET url, optionally bearing tok. Returns (status, body)."""
    req = urllib.request.Request(url)
    if tok is not None:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


class TestSnapshot:
    def test_snapshot_has_all_sections_on_empty_disk(self, isolated):
        s = db.build_snapshot()
        for key in ("generated_at", "mission", "cost", "skills", "tasks"):
            assert key in s
        assert s["mission"]["active"] is False
        assert s["cost"]["today_usd"] == 0

    def test_snapshot_never_contains_secrets(self, isolated):
        blob = json.dumps(db.build_snapshot()).lower()
        for word in ("api_key", "secret", "token", "password"):
            assert word not in blob


@pytest.fixture
def server(isolated):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), db._Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class TestServer:
    def test_api_status_serves_json(self, server, token):
        status, body = _get(f"{server}/api/status", token)
        assert status == 200
        data = json.loads(body)
        assert "cost" in data and "mission" in data

    def test_api_status_requires_a_token(self, server, token):
        """The snapshot carries trades, API spend and task descriptions."""
        status, _ = _get(f"{server}/api/status")
        assert status == 401

    def test_api_status_rejects_a_wrong_token(self, server, token):
        status, _ = _get(f"{server}/api/status", "not-the-token")
        assert status == 401

    def test_api_status_denied_when_no_token_is_configured(self, server):
        """Fails closed: an unconfigured dashboard serves nothing."""
        status, _ = _get(f"{server}/api/status")
        assert status == 401

    def test_root_serves_html_without_a_token(self, server):
        """The shell page carries no data — it must load to prompt for one."""
        status, body = _get(f"{server}/")
        assert status == 200
        assert "EL FAGER" in body

    def test_unknown_path_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{server}/admin", timeout=5)
        assert exc.value.code == 404

    def test_post_to_read_endpoint_rejected(self, server):
        req = urllib.request.Request(f"{server}/api/status", data=b"{}",
                                     method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 404  # only /api/command accepts POST


class TestDesignTokens:
    """The phone runs the same palette as the desktop, from the same source."""

    def test_the_root_block_is_generated_from_ui_tokens(self):
        from ui import tokens as t
        css = db._token_css()
        assert f"--accent-ember:{t.EMBER};" in css
        assert f"--surface-1:{t.SURFACE_1};" in css
        assert f"--text-hi:{t.TEXT_HI};" in css

    def test_it_runs_dawn_not_cockpit(self):
        # Cyan belongs to the Cockpit; the phone is the Command Center's
        # companion, so the accent here is ember.
        from ui import tokens as t
        assert f"--accent-ember:{t.EMBER};" in db._token_css()
        assert t.CK_STATE["listening"] not in db._token_css()

    def test_no_colour_literals_are_left_in_the_page_css(self):
        """Below :root everything must reference a token, or the phone can
        drift from ui/tokens.py again — which is how it drifted before."""
        import re
        style = db._PAGE.split("<style>", 1)[1].split("</style>", 1)[0]
        rules = style.split(db._token_css(), 1)[1]
        assert re.findall(r"#[0-9A-Fa-f]{3,8}\b", rules) == []

    def test_every_variable_the_page_uses_is_defined(self):
        import re
        used = set(re.findall(r"var\(--([a-z0-9-]+)\)", db._PAGE))
        defined = set(re.findall(r"--([a-z0-9-]+):", db._token_css()))
        assert used - defined == set()

    def test_the_template_placeholders_are_filled(self):
        assert "__TOKENS__" not in db._PAGE
        assert "__FONTS__" not in db._PAGE


class TestPhoneAssets:
    @pytest.fixture
    def server(self, isolated):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), db._Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()

    def test_the_bundled_faces_are_served(self, server):
        for name in db._FONTS:
            with urllib.request.urlopen(f"{server}/fonts/{name}", timeout=5) as r:
                assert r.status == 200
                assert r.headers["Content-Type"] == "font/ttf"
                assert len(r.read()) > 1000

    def test_the_page_declares_those_faces(self):
        for family in (f for f, _ in db._FONTS.values()):
            assert f"font-family:'{family}'" in db._PAGE

    def test_the_font_route_serves_nothing_else(self, server):
        for path in ("/fonts/settings.json", "/fonts/dashboard.py", "/fonts/"):
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(f"{server}{path}", timeout=5)
            assert exc.value.code == 404

    def test_it_is_installable(self, server):
        with urllib.request.urlopen(f"{server}/manifest.webmanifest", timeout=5) as r:
            manifest = json.loads(r.read().decode("utf-8"))
        assert manifest["name"] == "El Fager"
        assert manifest["display"] == "standalone"
        with urllib.request.urlopen(f"{server}{manifest['icons'][0]['src']}",
                                    timeout=5) as r:
            assert r.status == 200
            assert b"<svg" in r.read()
        assert 'rel="manifest"' in db._PAGE


class TestCommandChannel:
    @pytest.fixture
    def server(self, isolated, monkeypatch):
        import core.autonomous_tasks as at
        monkeypatch.setattr(at, "_TASKS_PATH", isolated / "tasks.json")
        (isolated / "data").mkdir(exist_ok=True)
        (isolated / "data" / "settings.json").write_text(
            json.dumps({"dashboard_token": "secret123"}), encoding="utf-8")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), db._Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()

    def _post(self, url, body, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{url}/api/command",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
        return urllib.request.urlopen(req, timeout=5)

    def test_missing_token_401_and_nothing_queued(self, server, isolated):
        import core.autonomous_tasks as at
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(server, {"text": "do something"})
        assert exc.value.code == 401
        assert at.AutonomousTaskManager().list_all() == []

    def test_wrong_token_401(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(server, {"text": "x"}, token="wrong")
        assert exc.value.code == 401

    def test_valid_token_queues_autonomous_task(self, server, isolated):
        import core.autonomous_tasks as at
        with self._post(server, {"text": "check NVDA rsi"},
                        token="secret123") as r:
            out = json.loads(r.read().decode("utf-8"))
        assert out["queued"] is True
        tasks = at.AutonomousTaskManager().list_all()
        assert len(tasks) == 1
        assert tasks[0]["description"] == "check NVDA rsi"

    def test_empty_text_400(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(server, {"text": "  "}, token="secret123")
        assert exc.value.code == 400

    def test_oversize_text_400(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(server, {"text": "x" * 501}, token="secret123")
        assert exc.value.code == 400

    def test_no_token_configured_rejects_all(self, isolated, monkeypatch):
        import core.autonomous_tasks as at
        monkeypatch.setattr(at, "_TASKS_PATH", isolated / "tasks.json")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), db._Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            with pytest.raises(urllib.error.HTTPError) as exc:
                self._post(url, {"text": "x"}, token="anything")
            assert exc.value.code == 401
        finally:
            srv.shutdown()

    def test_token_autogenerated_on_start(self, isolated):
        (isolated / "data").mkdir(exist_ok=True)
        (isolated / "data" / "settings.json").write_text(
            json.dumps({"dashboard_host": "127.0.0.1", "dashboard_port": 0}),
            encoding="utf-8")
        srv = db.start_dashboard()
        try:
            settings = json.loads(
                (isolated / "data" / "settings.json").read_text(encoding="utf-8"))
            assert len(settings.get("dashboard_token", "")) >= 20
        finally:
            if srv:
                srv.shutdown()


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
        generated = json.loads(
            (isolated / "data" / "settings.json").read_text(encoding="utf-8")
        )["dashboard_token"]
        assert generated, "start_dashboard must generate a token"
        status, _ = _get(f"http://127.0.0.1:{port}/api/status", generated)
        assert status == 200
        srv.shutdown()


class TestRosterSection:
    def test_snapshot_lists_every_agent(self):
        from core.dashboard import build_snapshot
        from core.agents.registry import ROSTER
        roster = build_snapshot()["roster"]
        callsigns = {a["callsign"] for a in roster["agents"]}
        assert callsigns == {spec.callsign for spec in ROSTER.values()}

    def test_pass_rates_come_from_the_ledger(self):
        from core.agents import ledger
        from core.dashboard import build_snapshot
        ledger.record("Sage", "research brokers", "pass")
        ledger.record("Sage", "research rates", "fail", reason="declined")
        agents = {a["callsign"]: a for a in build_snapshot()["roster"]["agents"]}
        assert agents["Sage"]["runs"] == 2
        assert agents["Sage"]["pass_rate"] == 50
        assert agents["Argus"]["runs"] == 0

    def test_work_in_flight_is_visible(self):
        from core.agents import ledger
        from core.dashboard import build_snapshot
        token = ledger.start_run("Nomad", "book a table", "voice")
        try:
            agents = {a["callsign"]: a for a in build_snapshot()["roster"]["agents"]}
            assert agents["Nomad"]["working_on"] == "book a table"
        finally:
            ledger.finish_run(token)

    def test_a_corrupt_ledger_degrades_instead_of_breaking_the_page(self, monkeypatch):
        from core.dashboard import build_snapshot
        monkeypatch.setattr(
            "core.agents.ledger.roster_status",
            lambda days=1: (_ for _ in ()).throw(ValueError("corrupt")),
        )
        assert build_snapshot()["roster"] == {"agents": [], "recent": []}


class TestRateLimiting:
    """A correct token is cheap to check; a wrong one should not be free.

    The command channel reaches every tool, and the token crosses the LAN in
    clear text, so both guessing and flooding need a ceiling.
    """

    def test_repeated_bad_tokens_start_getting_429(self, server, token):
        codes = [_get(f"{server}/api/status", "wrong")[0] for _ in range(8)]
        assert codes[:db._AUTH_FAILURES_PER_MIN] == [401] * db._AUTH_FAILURES_PER_MIN
        assert codes[db._AUTH_FAILURES_PER_MIN:] == [429] * (8 - db._AUTH_FAILURES_PER_MIN)

    def test_the_right_token_still_works_while_someone_guesses(self, server, token):
        for _ in range(8):
            _get(f"{server}/api/status", "wrong")
        status, _ = _get(f"{server}/api/status", token)
        assert status == 200, "throttling a guesser must not lock out the owner"

    def test_the_window_is_per_client(self):
        limiter = db._RateLimiter(limit=2)
        assert limiter.allow("10.0.0.1") and limiter.allow("10.0.0.1")
        assert not limiter.allow("10.0.0.1")
        assert limiter.allow("10.0.0.2"), "one client must not throttle another"

    def test_entries_expire_with_the_window(self):
        limiter = db._RateLimiter(limit=1, window_sec=0.05)
        assert limiter.allow("10.0.0.1")
        assert not limiter.allow("10.0.0.1")
        time.sleep(0.06)
        assert limiter.allow("10.0.0.1")
