"""Suite-wide isolation: tests that exercise brain.chat() log conversation
turns; EL_FAGER_TEST_MODE diverts them to data/conversations_test/ so the
suite never pollutes the real usage logs HabitMiner mines."""
import pytest


@pytest.fixture(autouse=True)
def _el_fager_test_mode(monkeypatch):
    monkeypatch.setenv("EL_FAGER_TEST_MODE", "1")


@pytest.fixture(autouse=True)
def _isolated_trust_ledger(monkeypatch, tmp_path):
    """Any test that confirms a staged send appends to the Trust Ledger. Left
    alone, that wrote "sent gmail -> a@b.c" and "whatsapp -> Omar" into Mo's
    real data/action_ledger.jsonl on every run — an append-only record he
    reads as what El Fager did. Point it at a file of the test's own."""
    from core import ledger
    monkeypatch.setattr(ledger, "_LEDGER", tmp_path / "action_ledger.jsonl")


@pytest.fixture(autouse=True)
def _isolated_voice_learned(monkeypatch, tmp_path):
    """Songs El Fager plays teach Whisper their names, in data/voice_learned.json.
    A test that plays a fake song must not teach Mo's real El Fager "Song 39"."""
    from core import voice_learned
    monkeypatch.setattr(voice_learned, "_FILE", tmp_path / "voice_learned.json")


@pytest.fixture(autouse=True)
def _isolated_voice_liked(monkeypatch, tmp_path):
    """Names read from Mo's Liked Songs live in data/voice_liked.json; a test's
    fake library must never replace them."""
    from core import voice_liked
    monkeypatch.setattr(voice_liked, "_FILE", tmp_path / "voice_liked.json")


@pytest.fixture(autouse=True)
def _no_real_whatsapp(monkeypatch):
    """Drafting a WhatsApp message searches Mo's real WhatsApp Desktop, and a
    confirm clicks and types into it. No test may do either — a test that
    needs them replaces these stubs with its own."""
    from tools import whatsapp_desktop

    def blocked(*args, **kwargs):
        raise whatsapp_desktop.WhatsAppDesktopError("real WhatsApp is off in tests")

    monkeypatch.setattr(whatsapp_desktop, "find_chats", blocked)
    monkeypatch.setattr(whatsapp_desktop, "send", blocked)


@pytest.fixture(autouse=True)
def _no_real_comet(monkeypatch):
    """Browser automation starts Comet with a debugging port when it can't
    attach to one. With Mo's own Comet already open, the browser-agent tests
    ran comet.exe for real — Chromium hands that to the running browser, which
    opens windows on his screen. Launching Comet or the default browser is off
    in tests; a test that needs either patches these with its own mock."""
    from tools import comet_tool

    def blocked(*args, **kwargs):
        raise RuntimeError("launching a real browser is off in tests")

    monkeypatch.setattr(comet_tool, "subprocess",
                        type("NoSubprocess", (), {"Popen": staticmethod(blocked),
                                                  "run": staticmethod(blocked)}))
    monkeypatch.setattr(comet_tool, "webbrowser",
                        type("NoBrowser", (), {"open": staticmethod(blocked)}))
