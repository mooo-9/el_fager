from unittest.mock import patch

import pytest

from core.agents import job_search_agent as jsa
from core.agents.job_search_agent import JobSearchAgent, _parse_linkedin, _parse_wuzzuf


@pytest.fixture(autouse=True)
def _seen_file(monkeypatch, tmp_path):
    """The seen-jobs record is Mo's real one; tests keep their own."""
    monkeypatch.setattr(jsa, "_FILE", tmp_path / "jobs_seen.json")


LINKEDIN_HTML = """
<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:111">
  <a class="base-card__full-link" href="https://eg.linkedin.com/jobs/view/data-analyst-intern-at-vodafone-111?position=1&amp;trackingId=abc">
    <span class="sr-only">Data Analyst Intern</span></a>
  <div class="base-search-card__info">
    <h3 class="base-search-card__title">  Data Analyst Intern </h3>
    <h4 class="base-search-card__subtitle"><a href="https://eg.linkedin.com/company/vodafone">Vodafone Egypt</a></h4>
    <div class="base-search-card__metadata">
      <span class="job-search-card__location">Cairo, Egypt</span>
      <time class="job-search-card__listdate" datetime="2026-09-23">2 days ago</time>
    </div></div></div></li>
<li><div class="base-card base-search-card job-search-card">
  <a class="base-card__full-link" href="https://eg.linkedin.com/jobs/view/senior-data-analyst-at-cib-222?trackingId=def"></a>
  <div class="base-search-card__info">
    <h3 class="base-search-card__title">Senior Data Analyst</h3>
    <h4 class="base-search-card__subtitle"><a>CIB</a></h4>
  </div></div></li>
"""

WUZZUF_HTML = """
<div class="css-1gatmva"><div class="css-pkv5jc"><div class="css-laomuu">
  <h2 class="css-m604qf"><a class="css-o171kl" href="/jobs/p/abc123-Business-Analyst-Noon-Academy-Cairo-Egypt">Business Analyst</a></h2>
  <div class="css-d7j1kk"><a class="css-17s97q8" href="https://wuzzuf.net/jobs/careers/Noon-Academy-Egypt-1">Noon Academy -</a><span class="css-5wys0k">Maadi, Cairo, Egypt</span></div>
  <div><div class="css-4c4ojb">3 days ago</div></div>
</div></div></div>
<div class="css-1gatmva"><div class="css-pkv5jc"><div class="css-laomuu">
  <h2 class="css-m604qf"><a href="https://wuzzuf.net/internship/xyz789-Data-Analyst-Intern-TMentors-Cairo-Egypt">Data Analyst Intern</a></h2>
  <div class="css-d7j1kk"><a href="/jobs/careers/TMentors-Egypt-2">TMentors -</a><span>Cairo, Egypt</span></div>
  <div><div class="css-do6t5g">1 day ago</div></div>
</div></div></div>
"""


class TestParseLinkedIn:
    def test_reads_each_card(self):
        jobs = _parse_linkedin(LINKEDIN_HTML)
        assert jobs[0] == {
            "title": "Data Analyst Intern", "company": "Vodafone Egypt",
            "location": "Cairo, Egypt", "posted": "2 days ago",
            "url": "https://eg.linkedin.com/jobs/view/data-analyst-intern-at-vodafone-111",
            "source": "LinkedIn",
        }
        assert len(jobs) == 2

    def test_tracking_parameters_are_dropped_from_the_url(self):
        """LinkedIn gives every listing a fresh trackingId: kept, the same job
        would look new on every search."""
        assert all("?" not in j["url"] for j in _parse_linkedin(LINKEDIN_HTML))

    def test_nothing_parsed_from_a_page_without_cards(self):
        assert _parse_linkedin("<html><body>Sign in</body></html>") == []


class TestParseWuzzuf:
    def test_finds_cards_by_their_links_not_class_names(self):
        jobs = _parse_wuzzuf(WUZZUF_HTML)
        assert jobs[0] == {
            "title": "Business Analyst", "company": "Noon Academy",
            "location": "Maadi, Cairo, Egypt", "posted": "3 days ago",
            "url": "https://wuzzuf.net/jobs/p/abc123-Business-Analyst-Noon-Academy-Cairo-Egypt",
            "source": "Wuzzuf",
        }

    def test_internship_pages_count_too(self):
        jobs = _parse_wuzzuf(WUZZUF_HTML)
        assert jobs[1]["url"] == "https://wuzzuf.net/internship/xyz789-Data-Analyst-Intern-TMentors-Cairo-Egypt"
        assert jobs[1]["company"] == "TMentors"


def _agent(pages: dict, searches: dict | None = None, rendered: str = ""):
    """An agent whose direct reads return `pages[source]` HTML, whose browser
    read of Wuzzuf returns `rendered`, and whose web searches return
    `searches[source]` (None = the search failed)."""
    searches = searches or {}
    agent = JobSearchAgent()
    agent.renders = []
    agent._render = lambda url: agent.renders.append(url) or rendered

    def fetch(url):
        if "wuzzuf" in url:
            return pages.get("Wuzzuf", "")
        if "linkedin" in url:
            return pages.get("LinkedIn", "")
        raise AssertionError(f"unexpected direct read: {url}")

    agent._fetch = fetch
    agent._web_search = lambda source, role: searches.get(source, [])
    return agent


class TestRun:
    def test_lists_jobs_from_every_board_that_had_some(self):
        out = _agent({"Wuzzuf": WUZZUF_HTML, "LinkedIn": LINKEDIN_HTML}).run("data analyst")
        assert out.startswith("3 new jobs for data analyst (Wuzzuf 2, LinkedIn 1):")
        assert "Data Analyst Intern -- Vodafone Egypt, Cairo, Egypt [LinkedIn, 2 days ago]" in out
        assert "https://wuzzuf.net/jobs/p/abc123-Business-Analyst-Noon-Academy-Cairo-Egypt" in out

    def test_senior_roles_are_left_out(self):
        out = _agent({"LinkedIn": LINKEDIN_HTML}).run("data analyst")
        assert "Senior Data Analyst" not in out

    def test_vice_presidents_are_left_out_too(self):
        vp = LINKEDIN_HTML.replace("Senior Data Analyst", "Vice President, Business Development")
        out = _agent({"LinkedIn": vp}).run("data analyst")
        assert "Vice President" not in out and "Data Analyst Intern" in out

    @pytest.mark.parametrize("bank", ["National Bank of Egypt", "CIB", "QNB Alahli", "HSBC",
                                      "Banque Misr", "Arab African International Bank",
                                      "Crédit Agricole Egypt", "بنك مصر"])
    def test_bank_jobs_are_left_out(self, bank):
        """Mo doesn't want to work at a bank."""
        html = LINKEDIN_HTML.replace("<a>CIB</a>", f"<a>{bank}</a>").replace(
            "Senior Data Analyst", "Data Analyst")
        out = _agent({"LinkedIn": html}).run("data analyst")
        assert bank not in out and "Vodafone Egypt" in out

    def test_a_fintech_is_not_a_bank(self):
        html = LINKEDIN_HTML.replace("<a>CIB</a>", "<a>Paymob</a>").replace(
            "Senior Data Analyst", "Banking Product Analyst")
        assert "Paymob" in _agent({"LinkedIn": html}).run("data analyst")

    def test_junior_titles_rank_first(self):
        out = _agent({"Wuzzuf": WUZZUF_HTML}).run("business analyst")
        lines = out.splitlines()
        # "Data Analyst Intern" matches one word of the role but is an
        # internship; "Business Analyst" matches both words. 1+2 beats 2.
        assert lines[1].startswith("1. Data Analyst Intern")

    def test_a_job_already_shown_is_not_new_again(self):
        agent = _agent({"Wuzzuf": WUZZUF_HTML})
        agent.run("data analyst")
        assert agent.run("data analyst") == "No new jobs for data analyst since the last check."

    def test_show_all_brings_back_jobs_already_shown(self):
        agent = _agent({"Wuzzuf": WUZZUF_HTML})
        agent.run("data analyst")
        out = agent.run("data analyst", show_all=True)
        assert out.startswith("2 jobs for data analyst")
        assert "NEW" not in out

    def test_show_all_marks_the_ones_not_seen_before(self):
        out = _agent({"Wuzzuf": WUZZUF_HTML}).run("data analyst", show_all=True)
        assert out.count(" NEW") == 2

    def test_only_the_jobs_shown_are_remembered(self, monkeypatch):
        """Past the cap they weren't seen yet, so they come next time."""
        monkeypatch.setattr(jsa, "_MAX_SHOWN", 1)
        agent = _agent({"Wuzzuf": WUZZUF_HTML})
        first = agent.run("data analyst")
        second = agent.run("data analyst")
        assert first.startswith("1 new jobs") and second.startswith("1 new jobs")
        assert first.splitlines()[1] != second.splitlines()[1]

    def test_a_board_that_blocks_reading_falls_back_to_web_search(self):
        found = [{"title": "Data Analyst job at X in Cairo", "company": "", "location": "",
                  "posted": "", "url": "https://wuzzuf.net/jobs/p/zz-Data-Analyst-X",
                  "source": "Wuzzuf"}]
        out = _agent({}, {"Wuzzuf": found}).run("data analyst")
        assert "Data Analyst job at X in Cairo [Wuzzuf]" in out

    def test_wuzzuf_behind_cloudflare_is_read_in_a_browser(self):
        """Wuzzuf answers a plain read with Cloudflare's "Just a moment..."
        page; a headless browser gets through it."""
        agent = _agent({"Wuzzuf": "<title>Just a moment...</title>"}, rendered=WUZZUF_HTML)
        out = agent.run("business analyst")
        assert "Business Analyst -- Noon Academy, Maadi, Cairo, Egypt [Wuzzuf" in out
        assert len(agent.renders) == 1 and "wuzzuf.net" in agent.renders[0]

    def test_a_wuzzuf_page_read_plainly_needs_no_browser(self):
        agent = _agent({"Wuzzuf": WUZZUF_HTML, "LinkedIn": LINKEDIN_HTML})
        agent.run("data analyst")
        assert agent.renders == []

    def test_only_wuzzuf_is_read_in_a_browser(self):
        agent = _agent({})
        agent.run("data analyst")
        assert agent.renders and all("wuzzuf.net" in u for u in agent.renders)

    def test_a_board_that_failed_for_every_role_is_named(self):
        out = _agent({"Wuzzuf": WUZZUF_HTML}, {"Bayt": None}).run("")
        assert out.endswith("Couldn't read: Bayt.")

    def test_no_role_searches_all_of_mos_targets(self):
        agent = _agent({})
        roles = []
        agent._web_search = lambda source, role: roles.append(role) or []
        out = agent.run("")
        assert set(roles) == set(jsa.TARGET_ROLES)
        assert out.startswith("No new jobs for data analyst, business analyst")

    def test_asked_for_no_role_it_searches_ai_data_and_ba(self):
        assert "machine learning" in jsa.TARGET_ROLES
        assert not {"software developer", "IT support"} & set(jsa.TARGET_ROLES)

    def test_the_same_job_on_two_boards_is_listed_once(self):
        dup = [{"title": "Business Analyst", "company": "Noon Academy", "location": "",
                "posted": "", "url": "https://www.bayt.com/en/egypt/jobs/business-analyst-5551",
                "source": "Bayt"}]
        out = _agent({"Wuzzuf": WUZZUF_HTML}, {"Bayt": dup}).run("business analyst")
        assert out.count("Business Analyst -- Noon Academy") == 1
        assert "bayt.com" not in out


class TestWebSearch:
    def _search(self, source, results):
        with patch("ddgs.DDGS") as MockDDGS:
            MockDDGS.return_value.__enter__.return_value.text.return_value = iter(results)
            return JobSearchAgent()._web_search(source, "data analyst")

    def test_keeps_job_pages_and_drops_listing_pages(self):
        jobs = self._search("Bayt", [
            {"title": "Data Analyst Jobs in Cairo (Aug 2026) - Bayt.com",
             "href": "https://www.bayt.com/en/egypt/jobs/data-analyst-jobs-in-cairo/"},
            {"title": "Data Analyst | Bayt.com",
             "href": "https://www.bayt.com/en/egypt/jobs/data-analyst-5173421/"},
        ])
        assert [j["url"] for j in jobs] == ["https://www.bayt.com/en/egypt/jobs/data-analyst-5173421"]
        assert jobs[0]["title"] == "Data Analyst"

    def test_forasna_job_pages(self):
        jobs = self._search("Forasna", [
            {"title": "x", "href": "https://forasna.com/a/%D9%88-data-entry"},
            {"title": "data entry", "href": "https://forasna.com/job/p/data-entry-420810"},
        ])
        assert [j["url"] for j in jobs] == ["https://forasna.com/job/p/data-entry-420810"]

    def test_title_loses_the_board_suffix(self):
        jobs = self._search("Wuzzuf", [{
            "title": "Data Analyst Intern at TMentors| Maadi, Cairo on Wuzzuf | Egypt",
            "href": "https://wuzzuf.net/internship/zZUJx7GP3clG-Data-Analyst-Intern-TMentors-Cairo-Egypt"}])
        assert jobs[0]["title"] == "Data Analyst Intern at TMentors"

    def test_a_failed_search_is_none_not_empty(self):
        with patch("ddgs.DDGS", side_effect=Exception("rate limited")):
            assert JobSearchAgent()._web_search("Bayt", "data analyst") is None


class TestBrainWiring:
    def test_the_tool_is_defined_with_optional_inputs(self):
        from core.brain import _SLIM_TOOLS
        tool = next(t for t in _SLIM_TOOLS if t["name"] == "job_search_agent")
        assert set(tool["input_schema"]["properties"]) == {"query", "show_all"}
        assert "required" not in tool["input_schema"]

    @pytest.mark.parametrize("message", [
        "find me jobs", "any new internships?", "what's on wuzzuf today",
        "data analyst vacancies in cairo",
    ])
    def test_job_talk_offers_the_tool(self, message):
        from core.brain import _select_tools
        assert "job_search_agent" in {t["name"] for t in _select_tools(message)}

    def test_other_talk_does_not(self):
        from core.brain import _select_tools
        assert "job_search_agent" not in {t["name"] for t in _select_tools("what's the weather")}

    def test_dispatch_passes_query_and_show_all(self):
        from core.brain import Brain
        with patch.object(JobSearchAgent, "run", return_value="ok") as run:
            assert Brain(profile={})._dispatch_tool(
                "job_search_agent", {"query": "data analyst", "show_all": True}) == "ok"
        run.assert_called_once_with("data analyst", show_all=True)

    def test_dispatch_with_no_inputs_searches_every_target(self):
        from core.brain import Brain
        with patch.object(JobSearchAgent, "run", return_value="ok") as run:
            Brain(profile={})._dispatch_tool("job_search_agent", {})
        run.assert_called_once_with("", show_all=False)
