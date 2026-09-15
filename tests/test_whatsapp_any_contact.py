"""WhatsApp to any chat saved in Mo's WhatsApp, by name.

The desktop driver (tools/whatsapp_desktop.py) is stubbed throughout — these
pin the decisions around it: which chat a spoken name lands on, that drafting
never sends, that a confirm sends to exactly the chat the draft named, and
that a failed send says so instead of claiming it went.
"""
import pytest

from core import staging


@pytest.fixture
def wa(monkeypatch, tmp_path):
    import tools.whatsapp_tool as w
    import tools.whatsapp_desktop as wd

    chats: dict = {"list": [], "photos": {}}
    sent: list = []
    monkeypatch.setattr(wd, "find_chats", lambda q: [
        wd.Chat(t, chats["photos"].get(t)) for t in chats["list"]])
    monkeypatch.setattr(wd, "send", lambda title, msg: sent.append((title, msg)))
    monkeypatch.setattr(w, "CONTACTS_PATH", tmp_path / "contacts.json")
    # The number path must never fire from these tests.
    monkeypatch.setattr(w.os, "startfile", lambda uri: sent.append(("URI", uri)))
    staging.reset()
    w._pending.clear()
    yield w, wd, chats, sent
    staging.reset()
    w._pending.clear()


class TestPickingTheChat:
    @pytest.mark.parametrize("query, chats, picked", [
        ("Yasmeen", ["Yasmeen Adam", "Marwan Lasheen"], "Yasmeen Adam"),
        ("yasmeen adam", ["Yasmeen Adam"], "Yasmeen Adam"),
        ("Seif", ["Seif Magdy", "Seif", "Seif Omar"], "Seif"),
        ("seif magdy", ["Seif Magdy", "Seif", "Seif Omar"], "Seif Magdy"),
        ("Mahmod", ["Mahmod Donga  عروض وفرها"], "Mahmod Donga  عروض وفرها"),
    ])
    def test_one_clear_match_is_picked(self, query, chats, picked):
        from tools.whatsapp_tool import _pick_chat
        assert _pick_chat(query, chats)[0] == picked

    def test_several_matches_are_not_guessed(self):
        from tools.whatsapp_tool import _pick_chat
        chosen, others = _pick_chat("Ahmed", ["Ahmed Adel", "Ahmed Sherif", "Loc"])
        assert chosen is None
        assert others == ["Ahmed Adel", "Ahmed Sherif"]

    def test_chats_found_by_something_other_than_the_name_dont_count(self):
        # WhatsApp's search also matches numbers and profile text: "Ahmed"
        # brought back "Loc" and "Del".
        from tools.whatsapp_tool import _pick_chat
        assert _pick_chat("Ahmed", ["Loc", "Del"]) == (None, [])

    def test_a_word_inside_a_name_isnt_a_match(self):
        from tools.whatsapp_tool import _pick_chat
        assert _pick_chat("mo", ["Honda", "Baba", "Ammo"]) == (None, [])


class TestDrafting:
    def test_a_saved_chat_is_staged_under_its_exact_name(self, wa):
        w, _, chats, sent = wa
        chats["list"] = ["Yasmeen Adam", "Marwan Lasheen"]
        out = w.prepare_whatsapp_message("yasmeen", "on my way")
        action = staging.current()
        assert action.medium == "whatsapp" and action.target == "Yasmeen Adam"
        assert "Yasmeen Adam" in out
        assert sent == [], "drafting sent something"

    def test_the_chosen_chats_photo_goes_on_the_draft(self, wa):
        w, _, chats, _ = wa
        chats["list"] = ["Yasmeen Adam", "Marwan Lasheen"]
        chats["photos"] = {"Yasmeen Adam": b"yasmeen-png", "Marwan Lasheen": b"marwan-png"}
        w.prepare_whatsapp_message("yasmeen", "on my way")
        assert staging.current().photo == b"yasmeen-png"

    def test_a_saved_number_draft_has_no_photo(self, wa):
        w, _, chats, _ = wa
        w.add_contact("Omar", "+201000000000")
        w.prepare_whatsapp_message("Omar", "hi")
        assert staging.current().photo is None

    def test_an_exact_name_is_staged_without_second_guessing(self, wa):
        # Listing "Seif Magdy" beside a draft for "Seif" had the model asking
        # Mo which one while the card already showed the draft.
        w, _, chats, _ = wa
        chats["list"] = ["Seif Magdy", "Seif", "Seif Omar"]
        out = w.prepare_whatsapp_message("Seif", "hi")
        assert staging.current().target == "Seif"
        assert "Seif Magdy" not in out and "Seif Omar" not in out

    def test_several_matches_ask_instead_of_staging(self, wa):
        w, _, chats, _ = wa
        chats["list"] = ["Ahmed Adel", "Ahmed Sherif"]
        out = w.prepare_whatsapp_message("Ahmed", "hi")
        assert staging.current() is None
        assert "Ahmed Adel" in out and "Ahmed Sherif" in out

    def test_no_whatsapp_match_falls_back_to_saved_numbers(self, wa):
        w, _, chats, sent = wa
        w.add_contact("Omar", "+201000000000")
        chats["list"] = []
        w.prepare_whatsapp_message("Omar", "hi")
        assert staging.current().target == "Omar"
        assert w._pending["phone"] == "+201000000000"

    def test_whatsapp_desktop_failing_falls_back_too(self, wa, monkeypatch):
        w, wd, _, _ = wa
        w.add_contact("Omar", "+201000000000")

        def broken(q):
            raise wd.WhatsAppDesktopError("WhatsApp Desktop didn't open")

        monkeypatch.setattr(wd, "find_chats", broken)
        w.prepare_whatsapp_message("Omar", "hi")
        assert staging.current().target == "Omar"

    def test_nothing_anywhere_says_so(self, wa):
        w, _, chats, _ = wa
        chats["list"] = []
        out = w.prepare_whatsapp_message("Nobody", "hi")
        assert staging.current() is None
        assert "Nobody" in out


class TestConfirming:
    def test_it_sends_to_the_chat_the_draft_named(self, wa):
        w, _, chats, sent = wa
        chats["list"] = ["Yasmeen Adam"]
        w.prepare_whatsapp_message("yasmeen", "on my way")
        out = w.confirm_whatsapp_send()
        assert sent == [("Yasmeen Adam", "on my way")]
        assert "Yasmeen Adam" in out
        assert staging.current() is None
        assert staging.receipts()[0]["target"] == "Yasmeen Adam"

    def test_a_failed_send_says_it_failed_and_clears_the_stage(self, wa, monkeypatch):
        w, wd, chats, _ = wa
        chats["list"] = ["Yasmeen Adam"]
        w.prepare_whatsapp_message("yasmeen", "on my way")

        def fails(title, msg):
            raise wd.WhatsAppDesktopError("the chat with 'Yasmeen Adam' didn't open")

        monkeypatch.setattr(wd, "send", fails)
        out = w.confirm_whatsapp_send()
        assert "not sent" in out.lower() and "didn't open" in out
        assert staging.current() is None
        assert staging.receipts() == []
