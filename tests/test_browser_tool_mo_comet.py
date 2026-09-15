"""The browser tool drives Mo's own Comet; closing or resetting it must never
take his tabs with it — the model calls browser_close when it's done."""
from unittest.mock import MagicMock

import tools.browser_tool as bt


def _attached():
    page, context, browser, pw = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    bt._page, bt._context, bt._browser, bt._playwright = page, context, browser, pw
    bt._owned = False
    return page, context, browser, pw


def test_closing_detaches_and_leaves_his_tabs_open():
    page, context, browser, pw = _attached()
    out = bt.browser_close()
    page.close.assert_not_called()
    context.close.assert_not_called()
    browser.close.assert_not_called()
    pw.stop.assert_called_once()
    assert bt._page is None
    assert "open" in out.lower()


def test_a_browser_it_launched_itself_is_still_cleaned_up():
    page, context, browser, _ = _attached()
    bt._owned = True
    bt.browser_close()
    page.close.assert_called_once()
    browser.close.assert_called_once()


class TestSubmit:
    """browser_submit clicked whatever it was given. Given Wikipedia's search
    box — the natural thing to pass — clicking it submitted nothing."""

    def _page(self, tag="input", input_type="search"):
        page = MagicMock()
        page.url = "https://example.com/after"
        element = page.locator.return_value.first
        element.evaluate.return_value = {"tag": tag, "type": input_type}
        bt._page, bt._owned = page, False
        bt._owner_thread = __import__("threading").current_thread().ident
        return page, element

    def test_a_text_field_is_submitted_with_enter(self):
        page, element = self._page("input", "search")
        out = bt.browser_submit("input[name=search]")
        element.press.assert_called_once_with("Enter", timeout=5000)
        element.click.assert_not_called()
        assert "example.com/after" in out

    def test_a_button_is_clicked(self):
        page, element = self._page("button", "submit")
        bt.browser_submit("button[type=submit]")
        element.click.assert_called_once()
        element.press.assert_not_called()

    def test_a_page_that_never_goes_quiet_still_counts_as_submitted(self):
        # YouTube never reaches "networkidle"; the submit had worked.
        page, element = self._page("button", "submit")
        page.wait_for_load_state.side_effect = TimeoutError("Timeout 10000ms exceeded")
        out = bt.browser_submit("button[type=submit]")
        assert not out.startswith("[")


def test_back_that_lands_from_cache_is_not_reported_as_failed():
    # Comet restores the previous page from cache without a "load" event; the
    # back had worked, yet it timed out and said it failed.
    page = MagicMock()
    page.url = "https://en.wikipedia.org/wiki/Main_Page"
    page.go_back.side_effect = TimeoutError("Page.go_back: Timeout 10000ms exceeded")
    bt._page, bt._owned = page, False
    bt._owner_thread = __import__("threading").current_thread().ident
    out = bt.browser_back()
    assert not out.startswith("[") and "Main_Page" in out


class TestClickOrder:
    """"Gezira Island" was tried as a CSS selector first and waited out a 5 s
    timeout before the text match that found it."""

    def _page(self):
        page = MagicMock()
        bt._page, bt._owned = page, False
        bt._owner_thread = __import__("threading").current_thread().ident
        return page

    def test_plain_words_are_matched_as_text_first(self):
        page = self._page()
        out = bt.browser_click("Gezira Island")
        page.get_by_text.assert_called_once_with("Gezira Island", exact=False)
        page.click.assert_not_called()
        assert "Gezira Island" in out

    def test_a_css_selector_is_tried_as_a_selector_first(self):
        page = self._page()
        bt.browser_click("#submit-btn")
        page.click.assert_called_once_with("#submit-btn", timeout=5000)
        page.get_by_text.assert_not_called()

    def test_text_that_isnt_found_still_gets_the_selector_try(self):
        page = self._page()
        page.get_by_text.return_value.first.click.side_effect = TimeoutError("no text")
        bt.browser_click("Sign in")
        page.click.assert_called_once()
