"""Tests for ElFagerNotifier and notify_tool."""
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_resp(status_code: int):
    return type("R", (), {"status_code": status_code})()


# ── ElFagerNotifier ────────────────────────────────────────────────────────────

class TestElFagerNotifier:
    def _notifier(self, monkeypatch, token="", chat=""):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", chat)
        import importlib, core.notifier as cn
        monkeypatch.setattr(cn, "_INSTANCE", None)
        importlib.reload(cn)
        from core.notifier import ElFagerNotifier
        return ElFagerNotifier()

    def test_telegram_ready_when_env_set(self, monkeypatch):
        n = self._notifier(monkeypatch, token="tok123", chat="789")
        assert n.telegram_ready is True

    def test_telegram_not_ready_when_no_token(self, monkeypatch):
        n = self._notifier(monkeypatch, token="", chat="789")
        assert n.telegram_ready is False

    def test_telegram_not_ready_when_no_chat(self, monkeypatch):
        n = self._notifier(monkeypatch, token="tok123", chat="")
        assert n.telegram_ready is False

    def test_send_telegram_returns_false_when_not_configured(self, monkeypatch):
        n = self._notifier(monkeypatch)
        assert n.send_telegram("hello") is False

    def test_send_telegram_posts_to_api(self, monkeypatch):
        n = self._notifier(monkeypatch, token="tok123", chat="789")
        import httpx
        captured = {}
        def mock_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _make_resp(200)
        monkeypatch.setattr(httpx, "post", mock_post)
        result = n.send_telegram("test message")
        assert result is True
        assert "tok123" in captured["url"]
        assert captured["json"]["chat_id"] == "789"
        assert captured["json"]["text"] == "test message"

    def test_send_telegram_truncates_at_4096(self, monkeypatch):
        n = self._notifier(monkeypatch, token="t", chat="1")
        import httpx
        captured = {}
        monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: (
            captured.update({"text": json["text"]}), _make_resp(200)
        )[1])
        n.send_telegram("x" * 5000)
        assert len(captured["text"]) == 4096

    def test_send_telegram_returns_false_on_non_200(self, monkeypatch):
        n = self._notifier(monkeypatch, token="t", chat="1")
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_resp(400))
        assert n.send_telegram("hi") is False

    def test_send_telegram_returns_false_on_exception(self, monkeypatch):
        n = self._notifier(monkeypatch, token="t", chat="1")
        import httpx
        def boom(*a, **kw):
            raise ConnectionError("network down")
        monkeypatch.setattr(httpx, "post", boom)
        assert n.send_telegram("hi") is False

    def test_send_delegates_to_telegram(self, monkeypatch):
        n = self._notifier(monkeypatch, token="t", chat="1")
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_resp(200))
        assert n.send("hi") is True

    def test_status_shows_ready(self, monkeypatch):
        n = self._notifier(monkeypatch, token="t", chat="1")
        assert "ready" in n.status()

    def test_status_shows_not_configured(self, monkeypatch):
        n = self._notifier(monkeypatch)
        status = n.status()
        assert "not configured" in status
        assert "TELEGRAM_BOT_TOKEN" in status

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
            "telegram_ready": ready,
            "send_telegram": lambda self, msg: send_ok,
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
        assert "TELEGRAM_BOT_TOKEN" in result or "not configured" in result.lower()

    def test_send_notification_send_failed(self, monkeypatch):
        self._patch_notifier(monkeypatch, ready=True, send_ok=False)
        from tools.notify_tool import send_notification
        result = send_notification("test")
        assert "failed" in result.lower()

    def test_notification_status_delegates(self, monkeypatch):
        import core.notifier as cn
        mock = type("MN", (), {"status": lambda self: "Telegram: ready"})()
        monkeypatch.setattr(cn, "_INSTANCE", mock)
        from tools.notify_tool import notification_status
        result = notification_status()
        assert "Telegram" in result
