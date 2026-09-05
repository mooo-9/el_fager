"""Comet is the browser El Fager opens things in; YouTube and web search go
through it. These cover the resolver, the page parsers, and the fallbacks that
keep a lookup useful when YouTube's markup changes."""
from unittest.mock import MagicMock, patch

import pytest

import tools.comet_tool as comet
import tools.youtube_tool as yt


@pytest.fixture(autouse=True)
def _reset():
    comet.reset_cache()
    yield
    comet.reset_cache()


class TestCometResolution:
    def test_found_under_localappdata(self, tmp_path, monkeypatch):
        exe = tmp_path / "Perplexity" / "Comet" / "Application" / "Comet.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.delenv("COMET_PATH", raising=False)
        assert comet.comet_path() == str(exe)
        assert comet.is_available()

    def test_comet_path_env_override_wins(self, tmp_path, monkeypatch):
        override = tmp_path / "elsewhere" / "Comet.exe"
        override.parent.mkdir(parents=True)
        override.write_text("")
        monkeypatch.setenv("COMET_PATH", str(override))
        assert comet.comet_path() == str(override)

    def test_missing_comet_resolves_to_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.delenv("COMET_PATH", raising=False)
        monkeypatch.delenv("PROGRAMFILES", raising=False)
        monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
        monkeypatch.delenv("PROGRAMW6432", raising=False)
        assert comet.comet_path() is None
        assert not comet.is_available()

    def test_resolution_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.delenv("COMET_PATH", raising=False)
        comet.comet_path()
        with patch.object(comet, "_candidates") as candidates:
            comet.comet_path()
        candidates.assert_not_called()


class TestOpenUrl:
    def test_launches_comet_with_the_url(self):
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", False), \
             patch.object(comet, "subprocess") as sub:
            assert comet.open_url("https://example.com") is True
        sub.Popen.assert_called_once_with([r"C:\Comet.exe", "https://example.com"])

    def test_launches_comet_bare_when_no_url(self):
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", False), \
             patch.object(comet, "subprocess") as sub:
            comet.open_url()
        sub.Popen.assert_called_once_with([r"C:\Comet.exe"])

    def test_everyday_launch_is_attachable(self):
        """open_url is what usually starts Comet, so it carries the debugging
        port — otherwise automation would rarely find an attachable browser."""
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "_DEBUG_PORT", "9222"), \
             patch.object(comet, "subprocess") as sub:
            comet.open_url("https://example.com")
        assert "--remote-debugging-port=9222" in sub.Popen.call_args.args[0]

    def test_falls_back_to_default_browser(self):
        with patch.object(comet, "comet_path", return_value=None), \
             patch.object(comet, "webbrowser") as wb:
            assert comet.open_url("https://example.com") is False
        wb.open.assert_called_once_with("https://example.com")

    def test_falls_back_when_comet_launch_raises(self):
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "subprocess") as sub, \
             patch.object(comet, "webbrowser") as wb:
            sub.Popen.side_effect = OSError("boom")
            assert comet.open_url("https://example.com") is False
        wb.open.assert_called_once()


class TestLaunchArgs:
    def test_debug_port_is_passed_so_automation_can_attach(self):
        with patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "_DEBUG_PORT", "9222"):
            assert comet._launch_args(r"C:\Comet.exe", "https://x.com") == [
                r"C:\Comet.exe", "--remote-debugging-port=9222", "https://x.com"]

    def test_no_debug_port_when_disabled(self):
        with patch.object(comet, "_REMOTE_DEBUG", False):
            assert comet._launch_args(r"C:\Comet.exe") == [r"C:\Comet.exe"]


class TestAutomationContext:
    """Automation attaches to Mo's running Comet so his logins carry. When it
    can't, it must still work — logged out, on a throwaway profile."""

    def _playwright(self, contexts=("his-context",)):
        pw = MagicMock()
        browser = MagicMock()
        browser.contexts = list(contexts)
        pw.chromium.connect_over_cdp.return_value = browser
        return pw, browser

    def test_attaches_to_running_comet_and_reuses_his_context(self):
        pw, browser = self._playwright()
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "cdp_alive", return_value=True):
            b, ctx, owned = comet.automation_context(pw)
        assert (b, ctx) == (browser, "his-context")
        assert owned is False, "his browser must not be ours to close"
        pw.chromium.launch.assert_not_called()

    def test_starts_comet_when_not_yet_attachable(self):
        pw, browser = self._playwright()
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "cdp_alive", return_value=False), \
             patch.object(comet, "_start_debuggable_comet", return_value=True) as start:
            _, _, owned = comet.automation_context(pw)
        start.assert_called_once()
        assert owned is False

    def test_falls_back_when_comet_is_not_attachable(self):
        pw, _ = self._playwright()
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "cdp_alive", return_value=False), \
             patch.object(comet, "_start_debuggable_comet", return_value=False):
            _, _, owned = comet.automation_context(pw)
        pw.chromium.launch.assert_called_once_with(headless=False)
        assert owned is True

    def test_falls_back_when_the_attach_itself_fails(self):
        pw, _ = self._playwright()
        pw.chromium.connect_over_cdp.side_effect = RuntimeError("refused")
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "cdp_alive", return_value=True):
            _, _, owned = comet.automation_context(pw)
        pw.chromium.launch.assert_called_once()
        assert owned is True

    def test_headless_never_attaches(self):
        """research_agent reads public pages in bulk — it needs no login and
        must not open tabs in Mo's face."""
        pw, _ = self._playwright()
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "cdp_alive", return_value=True):
            _, _, owned = comet.automation_context(pw, headless=True)
        pw.chromium.connect_over_cdp.assert_not_called()
        pw.chromium.launch.assert_called_once_with(headless=True)
        assert owned is True

    def test_remote_debug_disabled_uses_a_fresh_profile(self):
        pw, _ = self._playwright()
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", False):
            _, _, owned = comet.automation_context(pw)
        pw.chromium.connect_over_cdp.assert_not_called()
        assert owned is True


class TestTeardownNeverClosesHisBrowser:
    def test_attached_session_closes_only_our_tab(self):
        import tools.browser_tool as bt
        page, context, browser = MagicMock(), MagicMock(), MagicMock()
        with patch.multiple(bt, _page=page, _context=context, _browser=browser,
                            _playwright=MagicMock(), _owned=False):
            bt._reset_browser_state()
        page.close.assert_called_once()
        context.close.assert_not_called()
        browser.close.assert_not_called()

    def test_owned_session_is_torn_down_fully(self):
        import tools.browser_tool as bt
        page, context, browser = MagicMock(), MagicMock(), MagicMock()
        with patch.multiple(bt, _page=page, _context=context, _browser=browser,
                            _playwright=MagicMock(), _owned=True):
            bt._reset_browser_state()
        page.close.assert_called_once()
        context.close.assert_called_once()
        browser.close.assert_called_once()

    def test_research_agent_stays_headless_and_unattached(self):
        from pathlib import Path
        source = Path("core/agents/research_agent.py").read_text(encoding="utf-8")
        assert "chromium.launch(headless=True)" in source
        assert "comet" not in source.lower()


_SEARCH_HTML = (
    '{"contents":[{"adSlotRenderer":{"videoId":"AAAAAAAAAAA"}},'
    '{"videoRenderer":{"videoId":"kXYiU_JCYtU","thumbnail":{},'
    '"title":{"runs":[{"text":"Numb \\u2013 Linkin Park"}]}}}]}'
)

_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015">
 <title>Linkin Park</title>
 <entry><yt:videoId>kXYiU_JCYtU</yt:videoId><title>Numb</title></entry>
 <entry><yt:videoId>bbbbbbbbbbb</yt:videoId><title>Older</title></entry>
</feed>"""


def _response(status=200, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


class TestYouTubeParsers:
    def test_skips_ads_and_unescapes_the_title(self):
        assert yt._first_video(_SEARCH_HTML) == ("kXYiU_JCYtU", "Numb – Linkin Park")

    def test_falls_back_to_a_bare_video_id(self):
        assert yt._first_video('{"videoId":"dQw4w9WgXcQ"}') == ("dQw4w9WgXcQ", "")

    def test_returns_none_when_no_video_present(self):
        assert yt._first_video('{"nothing":"here"}') is None

    def test_channel_id_read_from_a_url(self):
        assert yt._channel_id(
            "https://www.youtube.com/channel/UCfM3zsQsOnfWNUppiycmBuw"
        ) == "UCfM3zsQsOnfWNUppiycmBuw"

    def test_channel_id_resolved_from_a_handle(self):
        html = '{"header":{},"channelId":"UCfM3zsQsOnfWNUppiycmBuw"}'
        with patch.object(yt.httpx, "get", return_value=_response(text=html)) as get:
            assert yt._channel_id("@linkinpark") == "UCfM3zsQsOnfWNUppiycmBuw"
        assert get.call_args.args[0] == "https://www.youtube.com/@linkinpark"


class TestYouTubeSearch:
    def test_opens_the_top_result(self):
        with patch.object(yt.httpx, "get", return_value=_response(text=_SEARCH_HTML)), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = yt.youtube_search("numb linkin park")
        opened.assert_called_once_with("https://www.youtube.com/watch?v=kXYiU_JCYtU")
        assert "Numb" in result

    def test_opens_the_results_page_when_parsing_fails(self):
        with patch.object(yt.httpx, "get", return_value=_response(text="<html/>")), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = yt.youtube_search("something obscure")
        assert "results?search_query=" in opened.call_args.args[0]
        assert "couldn't pick the top result" in result

    def test_network_failure_still_opens_the_search(self):
        with patch.object(yt.httpx, "get", side_effect=OSError("offline")), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            yt.youtube_search("numb")
        assert "results?search_query=" in opened.call_args.args[0]


class TestYouTubeLatest:
    def test_opens_the_newest_video(self):
        with patch.object(yt, "_channel_id", return_value="UCfM3zsQsOnfWNUppiycmBuw"), \
             patch.object(yt.httpx, "get", return_value=_response(text=_FEED_XML)), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = yt.youtube_latest("@linkinpark")
        opened.assert_called_once_with("https://www.youtube.com/watch?v=kXYiU_JCYtU")
        assert "Numb" in result

    def test_unknown_channel_opens_a_search(self):
        with patch.object(yt, "_channel_id", return_value=None), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = yt.youtube_latest("some channel")
        assert "results?search_query=" in opened.call_args.args[0]
        assert "Couldn't find the channel" in result

    def test_unreadable_feed_opens_the_channel(self):
        with patch.object(yt, "_channel_id", return_value="UCfM3zsQsOnfWNUppiycmBuw"), \
             patch.object(yt.httpx, "get", return_value=_response(status=404)), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            yt.youtube_latest("@linkinpark")
        assert opened.call_args.args[0].endswith("/videos")


class TestWebSearchOpensComet:
    def test_search_url_is_opened(self):
        from tools.web_tool import open_web_search
        with patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = open_web_search("how tall is the burj khalifa")
        url = opened.call_args.args[0]
        assert url.startswith("https://www.perplexity.ai/search?q=")
        assert "burj" in url
        assert "Comet" in result

    def test_says_so_when_comet_is_missing(self):
        from tools.web_tool import open_web_search
        with patch("tools.comet_tool.open_url", return_value=False):
            assert "Comet not found" in open_web_search("anything")


class TestOpenAppRoutesBrowsersToComet:
    @pytest.mark.parametrize("name", ["browser", "chrome", "Google Chrome",
                                      "internet", "comet"])
    def test_browser_names_open_comet(self, name):
        from tools.system_tool import open_app
        with patch("tools.comet_tool.open_comet", return_value="Opened Comet.") as oc:
            assert open_app(name) == "Opened Comet."
        oc.assert_called_once()

    @pytest.mark.parametrize("name,exe", [("edge", "msedge.exe"),
                                          ("firefox", "firefox.exe")])
    def test_naming_another_browser_still_opens_it(self, name, exe):
        """Mo asked for Comet over Chrome — not to lose every other browser."""
        from tools.system_tool import open_app
        with patch("tools.system_tool.subprocess") as sub:
            open_app(name)
        sub.Popen.assert_called_once_with(exe, shell=True)

    def test_other_apps_are_untouched(self):
        from tools.system_tool import open_app
        with patch("tools.system_tool.subprocess") as sub:
            open_app("notepad")
        sub.Popen.assert_called_once_with("notepad.exe", shell=True)


class TestBrainDispatch:
    def _brain(self):
        from core.brain import Brain
        return Brain(profile={})

    @pytest.mark.parametrize("tool,args,target", [
        ("youtube_search", {"query": "numb"}, "tools.youtube_tool.youtube_search"),
        ("youtube_latest", {"channel": "@lp"}, "tools.youtube_tool.youtube_latest"),
        ("open_web_search", {"task": "weather"}, "tools.web_tool.open_web_search"),
        ("open_comet", {"url": "https://x.com"}, "tools.comet_tool.open_comet"),
    ])
    def test_tools_dispatch(self, tool, args, target):
        brain = self._brain()
        with patch(target, return_value="done") as fn:
            assert brain._dispatch_tool(tool, args) == "done"
        fn.assert_called_once()
