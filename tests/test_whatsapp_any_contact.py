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

    chats: dict = {"list": [], "photos": {}, "by_query": {}}
    sent: list = []
    searched: list = []

    def find_chats(q):
        searched.append(q)
        titles = chats["by_query"].get(q, chats["list"])
        return [wd.Chat(t, chats["photos"].get(t)) for t in titles]

    monkeypatch.setattr(wd, "find_chats", find_chats)
    chats["searched"] = searched
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


class TestArabicSavedChats:
    """Whisper writes every name in English letters, so a chat saved as
    "العائله" was out of reach. The model passes the Arabic spelling too, and
    matching allows the spellings WhatsApp's own search treats as the same."""

    @pytest.mark.parametrize("arabic, titles, picked", [
        ("العائلة", ["العائله"], "العائله"),                 # ة / ه
        ("امازون", ["تحقق أمازون"], "تحقق أمازون"),          # أ / ا
        ("عطاره", ["ماركت وعطارة سما"], "ماركت وعطارة سما"),  # the "و" in front
        ("عائلة", ["العائله"], "العائله"),                   # the "ال" in front
        ("محمد طه", ["د محمد طه عظام", "مركز د. محمود زكريا للأسنان"], "د محمد طه عظام"),
        ("دكتور محمد طه", ["د محمد طه عظام"], "د محمد طه عظام"),   # "Doctor" saved as "د"
        ("د. محمد طه", ["د محمد طه عظام"], "د محمد طه عظام"),
    ])
    def test_arabic_spellings_match(self, arabic, titles, picked):
        from tools.whatsapp_tool import _pick_chat
        assert _pick_chat(arabic, titles)[0] == picked

    def test_a_different_arabic_name_does_not_match(self):
        from tools.whatsapp_tool import _pick_chat
        assert _pick_chat("محمد", ["مركز د. محمود زكريا للأسنان"]) == (None, [])

    def test_the_arabic_spelling_finds_a_chat_the_english_one_cant(self, wa):
        w, _, chats, sent = wa
        chats["by_query"] = {"family": [], "العائلة": ["العائله"]}
        chats["photos"] = {"العائله": b"family-png"}
        w.prepare_whatsapp_message("family", "dinner at 8", contact_name_arabic="العائلة")
        action = staging.current()
        assert action.target == "العائله" and action.photo == b"family-png"
        assert sent == []

    def test_the_arabic_search_is_skipped_when_english_already_found_it(self, wa):
        w, _, chats, _ = wa
        chats["by_query"] = {"Yasmeen": ["Yasmeen Adam"]}
        w.prepare_whatsapp_message("Yasmeen", "hi", contact_name_arabic="ياسمين")
        assert chats["searched"] == ["Yasmeen"]
        assert staging.current().target == "Yasmeen Adam"

    def test_each_arabic_spelling_is_tried_in_turn(self, wa):
        # "Kings" can be saved as it sounds or as it means: "كينجز" or "الملوك".
        w, _, chats, _ = wa
        chats["by_query"] = {"Kings": [], "كينجز": [], "الملوك": ["الملوك only"]}
        w.prepare_whatsapp_message("Kings", "match at 9",
                                   contact_name_arabic="كينجز | الملوك")
        assert chats["searched"] == ["Kings", "كينجز", "الملوك"]
        assert staging.current().target == "الملوك only"

    def test_several_arabic_matches_ask(self, wa):
        w, _, chats, _ = wa
        chats["by_query"] = {"Mohamed": [], "محمد": ["د محمد طه عظام", "محمد علي"]}
        out = w.prepare_whatsapp_message("Mohamed", "hi", contact_name_arabic="محمد")
        assert staging.current() is None
        assert "د محمد طه عظام" in out and "محمد علي" in out


class TestLearningNames:
    def test_a_sent_whatsapp_teaches_whisper_the_name(self, wa):
        from core import voice_learned
        w, _, chats, _ = wa
        chats["list"] = ["Yasmeen Adam"]
        w.prepare_whatsapp_message("yasmeen", "on my way")
        assert voice_learned.names() == []          # drafting alone isn't contact
        w.confirm_whatsapp_send()
        assert voice_learned.names() == ["Yasmeen Adam"]

    def test_a_failed_send_teaches_nothing(self, wa, monkeypatch):
        from core import voice_learned
        w, wd, chats, _ = wa
        chats["list"] = ["Yasmeen Adam"]
        w.prepare_whatsapp_message("yasmeen", "on my way")

        def fails(title, msg):
            raise wd.WhatsAppDesktopError("didn't open")

        monkeypatch.setattr(wd, "send", fails)
        w.confirm_whatsapp_send()
        assert voice_learned.names() == []


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


def test_the_model_is_made_to_give_the_arabic_spelling():
    """The slimmed tool list drops parameter descriptions, so the model saw a
    bare optional field and mostly left it out. It's required, and the tool's
    own description — which survives slimming — says what it's for."""
    from core.brain import _SLIM_TOOLS
    tool = next(t for t in _SLIM_TOOLS if t["name"] == "prepare_whatsapp_message")
    assert "contact_name_arabic" in tool["input_schema"]["required"]
    assert "Arabic" in tool["description"]
