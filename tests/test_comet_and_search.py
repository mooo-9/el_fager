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
        # The registry would still find a Comet installed on this machine.
        monkeypatch.setattr(comet, "_from_registry", lambda: None)
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
        sub.Popen.assert_called_once_with(
            [r"C:\Comet.exe", "--profile-directory=Default", "https://example.com"])

    def test_launches_comet_bare_when_no_url(self):
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_REMOTE_DEBUG", False), \
             patch.object(comet, "subprocess") as sub:
            comet.open_url()
        sub.Popen.assert_called_once_with([r"C:\Comet.exe", "--profile-directory=Default"])

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
                r"C:\Comet.exe", "--profile-directory=Default",
                "--remote-debugging-port=9222", "https://x.com"]

    def test_no_debug_port_when_disabled(self):
        with patch.object(comet, "_REMOTE_DEBUG", False):
            assert comet._launch_args(r"C:\Comet.exe") == [
                r"C:\Comet.exe", "--profile-directory=Default"]

    def test_links_open_in_mos_own_profile(self):
        """Comet has three profiles (mo, mm, saheb ziad). A bare launch hands the
        link to whichever was last active, so a video could open signed in as
        someone else. "Default" is Mo's."""
        args = comet._launch_args(r"C:\Comet.exe", "https://youtube.com/watch?v=x")
        assert "--profile-directory=Default" in args
        assert args.index("--profile-directory=Default") < args.index("https://youtube.com/watch?v=x")

    def test_the_profile_can_be_changed_from_env(self):
        with patch.object(comet, "_PROFILE", "Profile 2"):
            assert "--profile-directory=Profile 2" in comet._launch_args(r"C:\Comet.exe")


class TestAutostart:
    """A Comet Mo opens himself has no debugging port and Chromium can't add one
    to a live process, so El Fager has to get in first."""

    def test_starts_comet_minimised_with_the_port(self):
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_AUTOSTART", True), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "_DEBUG_PORT", "9222"), \
             patch.object(comet, "cdp_alive", return_value=False), \
             patch.object(comet, "subprocess") as sub:
            assert comet.autostart() is True
        args = sub.Popen.call_args.args[0]
        assert "--remote-debugging-port=9222" in args
        assert "startupinfo" in sub.Popen.call_args.kwargs

    def test_does_not_relaunch_an_attachable_comet(self):
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_AUTOSTART", True), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "cdp_alive", return_value=True), \
             patch.object(comet, "subprocess") as sub:
            assert comet.autostart() is True
        sub.Popen.assert_not_called()

    def test_skipped_when_disabled(self):
        with patch.object(comet, "_AUTOSTART", False), \
             patch.object(comet, "subprocess") as sub:
            assert comet.autostart() is False
        sub.Popen.assert_not_called()

    def test_skipped_when_comet_is_not_installed(self):
        with patch.object(comet, "_AUTOSTART", True), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "comet_path", return_value=None), \
             patch.object(comet, "subprocess") as sub:
            assert comet.autostart() is False
        sub.Popen.assert_not_called()

    def test_launch_failure_is_not_fatal(self):
        with patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"), \
             patch.object(comet, "_AUTOSTART", True), \
             patch.object(comet, "_REMOTE_DEBUG", True), \
             patch.object(comet, "cdp_alive", return_value=False), \
             patch.object(comet, "subprocess") as sub:
            sub.Popen.side_effect = OSError("denied")
            assert comet.autostart() is False


class TestAutomationContext:
    """Automation only ever drives Mo's own signed-in "mo" Comet. It used to
    fall back to a logged-out throwaway browser, which Mo doesn't want."""

    def _playwright(self, contexts=("his-context",)):
        pw = MagicMock()
        browser = MagicMock()
        browser.contexts = list(contexts)
        pw.chromium.connect_over_cdp.return_value = browser
        return pw, browser

    def _run(self, pw, headless=False, **overrides):
        from contextlib import ExitStack
        values = dict(comet_path=r"C:\Comet.exe", cdp_alive=False,
                      _comet_running=False, _start_debuggable_comet=True,
                      _close_comet=True)
        values.update(overrides)
        with ExitStack() as stack:
            stack.enter_context(patch.object(comet, "_REMOTE_DEBUG", True))
            mocks = {name: stack.enter_context(patch.object(comet, name, return_value=value))
                     for name, value in values.items()}
            return comet.automation_context(pw, headless=headless), mocks

    def test_attaches_to_running_comet_and_reuses_his_context(self):
        pw, browser = self._playwright()
        (b, ctx, owned), _ = self._run(pw, cdp_alive=True)
        assert (b, ctx) == (browser, "his-context")
        assert owned is False, "his browser must not be ours to close"
        pw.chromium.launch.assert_not_called()

    def test_starts_his_comet_when_it_isnt_running(self):
        pw, _ = self._playwright()
        (_, _, owned), mocks = self._run(pw)
        mocks["_start_debuggable_comet"].assert_called_once()
        mocks["_close_comet"].assert_not_called()
        assert owned is False

    def test_reopens_a_comet_mo_started_without_the_port(self):
        """A Comet opened from the taskbar has no debugging port; it is closed
        gracefully and reopened on his profile with one. Its tabs come back."""
        pw, _ = self._playwright()
        (_, _, owned), mocks = self._run(pw, _comet_running=True)
        mocks["_close_comet"].assert_called_once()
        mocks["_start_debuggable_comet"].assert_called_once()
        assert owned is False

    def test_never_falls_back_to_a_logged_out_browser(self):
        pw, _ = self._playwright()
        with pytest.raises(comet.CometUnavailable):
            self._run(pw, _start_debuggable_comet=False)
        pw.chromium.launch.assert_not_called()

    def test_a_comet_that_wont_close_is_reported_not_worked_around(self):
        pw, _ = self._playwright()
        with pytest.raises(comet.CometUnavailable):
            self._run(pw, _comet_running=True, _close_comet=False)
        pw.chromium.launch.assert_not_called()

    def test_a_failed_attach_is_reported_not_worked_around(self):
        pw, _ = self._playwright()
        pw.chromium.connect_over_cdp.side_effect = RuntimeError("refused")
        with pytest.raises(comet.CometUnavailable):
            self._run(pw, cdp_alive=True)
        pw.chromium.launch.assert_not_called()

    def test_headless_never_attaches(self):
        """research_agent reads public pages in bulk — it needs no login and
        must not open tabs in Mo's face."""
        pw, _ = self._playwright()
        (_, _, owned), _ = self._run(pw, headless=True, cdp_alive=True)
        pw.chromium.connect_over_cdp.assert_not_called()
        pw.chromium.launch.assert_called_once_with(headless=True)
        assert owned is True

    def test_without_the_debug_port_setting_it_refuses(self):
        pw, _ = self._playwright()
        with patch.object(comet, "_REMOTE_DEBUG", False), \
             patch.object(comet, "comet_path", return_value=r"C:\Comet.exe"):
            with pytest.raises(comet.CometUnavailable):
                comet.automation_context(pw)
        pw.chromium.launch.assert_not_called()

    def test_without_comet_installed_it_refuses(self):
        pw, _ = self._playwright()
        with patch.object(comet, "comet_path", return_value=None):
            with pytest.raises(comet.CometUnavailable):
                comet.automation_context(pw)
        pw.chromium.launch.assert_not_called()


class TestTeardownNeverClosesHisBrowser:
    def test_attached_session_closes_nothing_not_even_our_tab(self):
        # The tab holds what Mo asked for — he found his video, then watched
        # El Fager close it.
        import tools.browser_tool as bt
        page, context, browser = MagicMock(), MagicMock(), MagicMock()
        with patch.multiple(bt, _page=page, _context=context, _browser=browser,
                            _playwright=MagicMock(), _owned=False):
            bt._reset_browser_state()
        page.close.assert_not_called()
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
             patch.object(yt, "_search_channels", return_value=[]) as searched, \
             patch.object(yt.httpx, "get", return_value=_response(text=_FEED_XML)), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = yt.youtube_latest("@linkinpark")
        opened.assert_called_once_with("https://www.youtube.com/watch?v=kXYiU_JCYtU")
        assert "Numb" in result
        searched.assert_not_called()          # a handle that works needs no search

    def test_unknown_channel_opens_a_search(self):
        with patch.object(yt, "_channel_id", return_value=None), \
             patch.object(yt, "_search_channels", return_value=[]), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = yt.youtube_latest("some channel")
        assert "results?search_query=" in opened.call_args.args[0]
        assert "Couldn't find the channel" in result

    def test_unreadable_feed_opens_the_channel(self):
        with patch.object(yt, "_channel_id", return_value="UCfM3zsQsOnfWNUppiycmBuw"), \
             patch.object(yt, "_search_channels", return_value=[]), \
             patch.object(yt.httpx, "get", return_value=_response(status=404)), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            yt.youtube_latest("@linkinpark")
        assert opened.call_args.args[0].endswith("/videos")


_EMPTY_FEED = """<?xml version="1.0"?><feed><title>erzaa</title></feed>"""


class TestYouTubeLatestFindsTheRightChannel:
    """"Erzaa" resolved to @Erzaa — a different channel with no videos — and
    "Marwan Moussa" guessed @MarwanMoussa, which doesn't exist. YouTube's own
    channel search finds both."""

    def _feeds(self, by_channel):
        def get(url, **kwargs):
            for cid, text in by_channel.items():
                if cid in url:
                    return _response(text=text)
            return _response(status=404)
        return get

    def test_an_empty_channel_falls_through_to_one_that_has_videos(self):
        feeds = {"UCemptyemptyemptyempty": _EMPTY_FEED, "UCrealrealrealrealreal": _FEED_XML}
        with patch.object(yt, "_channel_id", return_value="UCemptyemptyemptyempty"), \
             patch.object(yt, "_search_channels", return_value=["UCrealrealrealrealreal"]), \
             patch.object(yt.httpx, "get", side_effect=self._feeds(feeds)), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            result = yt.youtube_latest("Erzaa")
        opened.assert_called_once_with("https://www.youtube.com/watch?v=kXYiU_JCYtU")
        assert "Numb" in result

    def test_a_name_with_no_handle_is_found_by_search(self):
        feeds = {"UCrealrealrealrealreal": _FEED_XML}
        with patch.object(yt, "_channel_id", return_value=None), \
             patch.object(yt, "_search_channels", return_value=["UCrealrealrealrealreal"]), \
             patch.object(yt.httpx, "get", side_effect=self._feeds(feeds)), \
             patch("tools.comet_tool.open_url", return_value=True) as opened:
            yt.youtube_latest("Marwan Moussa")
        opened.assert_called_once_with("https://www.youtube.com/watch?v=kXYiU_JCYtU")

    def test_channel_search_reads_channel_ids_in_order(self):
        html = ('{"channelRenderer":{"channelId":"UCaaaaaaaaaaaaaaaaaaaaaa","title":{"simpleText":"A"}}}'
                '{"channelRenderer":{"channelId":"UCbbbbbbbbbbbbbbbbbbbbbb","title":{"simpleText":"B"}}}')
        with patch.object(yt.httpx, "get", return_value=_response(text=html)) as get:
            assert yt._search_channels("marwan moussa") == [
                "UCaaaaaaaaaaaaaaaaaaaaaa", "UCbbbbbbbbbbbbbbbbbbbbbb"]
        assert "sp=EgIQAg" in get.call_args.args[0]      # YouTube's "channels only" filter


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


def test_feed_titles_are_unescaped_so_they_read_aloud_cleanly():
    # '"Over Each Other" Live' came back as '&quot;Over Each Other&quot; Live'.
    feed = ('<feed><title>Linkin Park</title><entry><yt:videoId>kXYiU_JCYtU</yt:videoId>'
            '<title>&quot;Over Each Other&quot; Live &amp; Loud</title></entry></feed>')
    with patch.object(yt.httpx, "get", return_value=_response(text=feed)):
        assert yt._newest_in_feed("UCfM3zsQsOnfWNUppiycmBuw") == (
            "kXYiU_JCYtU", '"Over Each Other" Live & Loud')
