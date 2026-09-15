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
