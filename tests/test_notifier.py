"""Tests for ElFagerNotifier and notify_tool (WhatsApp via CallMeBot)."""
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_resp(status_code: int):
    return type("R", (), {"status_code": status_code})()


# ── ElFagerNotifier ────────────────────────────────────────────────────────────

class TestElFagerNotifier:
    def _notifier(self, monkeypatch, phone="", key=""):
        monkeypatch.setenv("WHATSAPP_PHONE", phone)
        monkeypatch.setenv("WHATSAPP_CALLMEBOT_KEY", key)
        import core.notifier as cn
        monkeypatch.setattr(cn, "_INSTANCE", None)
        from core.notifier import ElFagerNotifier
        return ElFagerNotifier()

    def test_whatsapp_ready_when_env_set(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="abc123")
        assert n.whatsapp_ready is True

    def test_whatsapp_not_ready_when_no_phone(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="", key="abc123")
        assert n.whatsapp_ready is False

    def test_whatsapp_not_ready_when_no_key(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="")
        assert n.whatsapp_ready is False

    def test_send_whatsapp_returns_false_when_not_configured(self, monkeypatch):
        n = self._notifier(monkeypatch)
        assert n.send_whatsapp("hello") is False

    def test_send_whatsapp_calls_callmebot_api(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="mykey")
        import httpx
        captured = {}
        def mock_get(url, params=None, timeout=None):
            captured["url"]    = url
            captured["params"] = params
            return _make_resp(200)
        monkeypatch.setattr(httpx, "get", mock_get)
        result = n.send_whatsapp("test message")
        assert result is True
        assert "callmebot" in captured["url"]
        assert captured["params"]["phone"]  == "201234567890"
        assert captured["params"]["apikey"] == "mykey"
        assert captured["params"]["text"]   == "test message"

    def test_send_whatsapp_truncates_at_1600(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="k")
        import httpx
        captured = {}
        monkeypatch.setattr(httpx, "get", lambda url, params=None, timeout=None: (
            captured.update({"text": params["text"]}), _make_resp(200)
        )[1])
        n.send_whatsapp("x" * 2000)
        assert len(captured["text"]) == 1600

    def test_send_whatsapp_returns_false_on_non_200(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="k")
        import httpx
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _make_resp(400))
        assert n.send_whatsapp("hi") is False

    def test_send_whatsapp_returns_false_on_exception(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="k")
        import httpx
        def boom(*a, **kw):
            raise ConnectionError("network down")
        monkeypatch.setattr(httpx, "get", boom)
        assert n.send_whatsapp("hi") is False

    def test_send_delegates_to_whatsapp(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="k")
        import httpx
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _make_resp(200))
        assert n.send("hi") is True

    def test_status_shows_ready(self, monkeypatch):
        n = self._notifier(monkeypatch, phone="201234567890", key="k")
        assert "ready" in n.status()

    def test_status_shows_not_configured(self, monkeypatch):
        n = self._notifier(monkeypatch)
        status = n.status()
        assert "not configured" in status
        assert "WHATSAPP_PHONE" in status

    def test_get_notifier_returns_singleton(self, monkeypatch):
        import core.notifier as cn
        monkeypatch.setattr(cn, "_INSTANCE", None)
        from core.notifier import get_notifier
        n1 = get_notifier()
        n2 = get_notifier()
        assert n1 is n2


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
        self._patch_notifier(monkeypatch, ready=False, send_ok=False)
        from tools.notify_tool import send_notification
        result = send_notification("test")
        assert "WHATSAPP_PHONE" in result or "not configured" in result.lower()

    def test_send_notification_send_failed(self, monkeypatch):
        self._patch_notifier(monkeypatch, ready=True, send_ok=False)
        from tools.notify_tool import send_notification
        result = send_notification("test")
        assert "failed" in result.lower()

    def test_notification_status_delegates(self, monkeypatch):
        import core.notifier as cn
        mock = type("MN", (), {"status": lambda self: "WhatsApp: ready"})()
        monkeypatch.setattr(cn, "_INSTANCE", mock)
        from tools.notify_tool import notification_status
        result = notification_status()
        assert "WhatsApp" in result
