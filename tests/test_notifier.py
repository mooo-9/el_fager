"""Tests for ElFagerNotifier and notify_tool (WhatsApp via Twilio sandbox)."""
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_resp(status_code: int):
    return type("R", (), {"status_code": status_code})()


def _patch_env(monkeypatch, sid="", token="", from_num="", to_num=""):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID",    sid)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN",      token)
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM",   from_num)
    monkeypatch.setenv("WHATSAPP_PHONE",         to_num)


# ── ElFagerNotifier ────────────────────────────────────────────────────────────

class TestElFagerNotifier:
    _FULL_ENV = dict(sid="ACtest", token="tok", from_num="+14155238886", to_num="+201152215125")

    def _notifier(self, monkeypatch, **kwargs):
        _patch_env(monkeypatch, **{**dict(sid="", token="", from_num="", to_num=""), **kwargs})
        import core.notifier as cn
        monkeypatch.setattr(cn, "_INSTANCE", None)
        from core.notifier import ElFagerNotifier
        return ElFagerNotifier()

    def test_whatsapp_ready_when_all_env_set(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        assert n.whatsapp_ready is True

    def test_whatsapp_not_ready_when_sid_missing(self, monkeypatch):
        env = {**self._FULL_ENV, "sid": ""}
        n = self._notifier(monkeypatch, **env)
        assert n.whatsapp_ready is False

    def test_whatsapp_not_ready_when_token_missing(self, monkeypatch):
        env = {**self._FULL_ENV, "token": ""}
        n = self._notifier(monkeypatch, **env)
        assert n.whatsapp_ready is False

    def test_whatsapp_not_ready_when_from_missing(self, monkeypatch):
        env = {**self._FULL_ENV, "from_num": ""}
        n = self._notifier(monkeypatch, **env)
        assert n.whatsapp_ready is False

    def test_whatsapp_not_ready_when_to_missing(self, monkeypatch):
        env = {**self._FULL_ENV, "to_num": ""}
        n = self._notifier(monkeypatch, **env)
        assert n.whatsapp_ready is False

    def test_send_whatsapp_returns_false_when_not_configured(self, monkeypatch):
        n = self._notifier(monkeypatch)
        assert n.send_whatsapp("hello") is False

    def test_send_whatsapp_posts_to_twilio_api(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        import httpx
        captured = {}
        def mock_post(url, data=None, auth=None, timeout=None):
            captured["url"]  = url
            captured["data"] = data
            captured["auth"] = auth
            return _make_resp(201)
        monkeypatch.setattr(httpx, "post", mock_post)
        result = n.send_whatsapp("test message")
        assert result is True
        assert "ACtest" in captured["url"]
        assert captured["data"]["From"] == "whatsapp:+14155238886"
        assert captured["data"]["To"]   == "whatsapp:+201152215125"
        assert captured["data"]["Body"] == "test message"
        assert captured["auth"] == ("ACtest", "tok")

    def test_send_whatsapp_accepts_200_and_201(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        import httpx
        for code in (200, 201):
            monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_resp(code))
            assert n.send_whatsapp("hi") is True

    def test_send_whatsapp_truncates_at_1600(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        import httpx
        captured = {}
        monkeypatch.setattr(httpx, "post", lambda url, data=None, auth=None, timeout=None: (
            captured.update({"body": data["Body"]}), _make_resp(201)
        )[1])
        n.send_whatsapp("x" * 2000)
        assert len(captured["body"]) == 1600

    def test_send_whatsapp_returns_false_on_non_2xx(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_resp(400))
        assert n.send_whatsapp("hi") is False

    def test_send_whatsapp_returns_false_on_exception(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(ConnectionError()))
        assert n.send_whatsapp("hi") is False

    def test_send_delegates_to_whatsapp(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_resp(201))
        assert n.send("hi") is True

    def test_status_shows_ready_with_phone(self, monkeypatch):
        n = self._notifier(monkeypatch, **self._FULL_ENV)
        status = n.status()
        assert "ready" in status
        assert "+201152215125" in status

    def test_status_lists_missing_vars(self, monkeypatch):
        n = self._notifier(monkeypatch)
        status = n.status()
        assert "TWILIO_ACCOUNT_SID" in status

    def test_get_notifier_returns_singleton(self, monkeypatch):
        import core.notifier as cn
        monkeypatch.setattr(cn, "_INSTANCE", None)
        from core.notifier import get_notifier
        assert get_notifier() is get_notifier()


# ── notify_tool ────────────────────────────────────────────────────────────────

class TestNotifyTool:
    def _patch_notifier(self, monkeypatch, *, ready=True, send_ok=True):
        import core.notifier as cn
        mock = type("MN", (), {
            "whatsapp_ready": ready,
            "send_whatsapp": lambda self, msg: send_ok,
        })()
        monkeypatch.setattr(cn, "_INSTANCE", mock)

    def test_send_notification_success(self, monkeypatch):
        self._patch_notifier(monkeypatch, ready=True, send_ok=True)
        from tools.notify_tool import send_notification
        result = send_notification("Hello Mo!")
        assert "sent" in result.lower()
        assert "Hello Mo" in result

    def test_send_notification_not_configured(self, monkeypatch):
        self._patch_notifier(monkeypatch, ready=False)
        from tools.notify_tool import send_notification
        result = send_notification("test")
        assert "TWILIO_ACCOUNT_SID" in result or "not configured" in result.lower()

    def test_send_notification_send_failed(self, monkeypatch):
        self._patch_notifier(monkeypatch, ready=True, send_ok=False)
        from tools.notify_tool import send_notification
        result = send_notification("test")
        assert "failed" in result.lower()

    def test_notification_status_delegates(self, monkeypatch):
        import core.notifier as cn
        mock = type("MN", (), {"status": lambda self: "WhatsApp (Twilio): ready"})()
        monkeypatch.setattr(cn, "_INSTANCE", mock)
        from tools.notify_tool import notification_status
        assert "WhatsApp" in notification_status()
