from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.career import (
    appliers, companies, pipeline, profile, scorer, sources, store, tracker,
)


@pytest.fixture(autouse=True)
def _career_dir(monkeypatch, tmp_path):
    """Also set here so these run without the suite's conftest."""
    monkeypatch.setattr(store, "DIR", tmp_path / "career")


def _job(title, company, url, tier="", score=80, **extra):
    target = companies.match(company)
    return {"title": title, "company": company, "location": "Cairo", "posted": "",
            "url": url, "source": "Wuzzuf", "tier": target["tier"] if target else tier,
            "company_key": target["name"] if target else company, "score": score,
            "fit": "fits", "missing": [], "level": "entry", "in_egypt": True, **extra}


class TestCompanies:
    @pytest.mark.parametrize("name,firm", [
        ("PwC Middle East", "PwC"), ("EY", "EY"), ("Deloitte Innovation Hub", "Deloitte"),
        ("KPMG Hazem Hassan", "KPMG"), ("_VOIS", "Vodafone / _VOIS"),
        ("Vodafone Egypt", "Vodafone / _VOIS"),
    ])
    def test_postings_land_on_their_firm(self, name, firm):
        assert companies.match(name)["name"] == firm

    @pytest.mark.parametrize("name", ["Noon Academy", "Keysight", "Heyday Studio", ""])
    def test_lookalikes_do_not(self, name):
        assert companies.match(name) is None

    def test_the_big_four(self):
        assert [c["name"] for c in companies.big4()] == ["Deloitte", "PwC", "EY", "KPMG"]


class TestSettings:
    def test_practice_mode_is_the_default(self):
        assert store.settings()["live"] is False
        assert store.settings()["daily_target"] == 20

    def test_finance_and_credit_risk_are_searched(self):
        terms = store.settings()["search_terms"]
        assert "credit risk" in terms and "financial analyst" in terms

    def test_unknown_settings_are_ignored(self):
        s = store.update_settings(daily_target=50, nonsense=1)
        assert s["daily_target"] == 50 and "nonsense" not in s


class TestProfile:
    def test_every_answer_starts_missing(self):
        assert profile.missing_answers() == list(profile.ANSWER_KEYS)

    def test_an_answer_is_saved(self):
        assert profile.set_answer("military status", "Exempted").startswith("Saved")
        assert "military_status" not in profile.missing_answers()

    def test_an_unknown_question_is_refused(self):
        assert profile.set_answer("favourite colour", "blue").startswith("Error")

    def test_before_a_cv_the_profile_says_so(self):
        assert "No CV imported yet" in profile.as_text()

    def test_import_fills_empty_answers_but_keeps_mos_own(self, tmp_path):
        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF")
        profile.set_answer("phone", "+20 100 000 0000")
        fields = {"name": "Mohamed Ali", "headline": "BI student", "education": "Helwan BIS",
                  "skills": ["SQL", "Power BI"], "experience": ["Intern at X"], "projects": [],
                  "certifications": [], "languages": ["Arabic", "English"],
                  "email": "mo@x.com", "phone": "0111", "linkedin_url": "", "graduation_year": "2027",
                  "gpa": ""}
        with patch.object(profile, "_cv_text", return_value="CV text " * 50), \
             patch("core.career.claude.ask", return_value=fields):
            out = profile.import_cv(str(cv))
        p = profile.load()
        assert out.startswith("CV imported: Mohamed Ali -- 2 skills")
        assert p["answers"]["phone"] == "+20 100 000 0000"
        assert p["answers"]["email"] == "mo@x.com"
        assert p["cv_path"] == str(cv)
        assert "Skills: SQL; Power BI" in profile.as_text()

    def test_an_unreadable_cv_is_reported(self, tmp_path):
        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF")
        with patch.object(profile, "_cv_text", return_value=""):
            assert profile.import_cv(str(cv)).startswith("Error: couldn't read text")


class TestScorer:
    def test_finds_the_hr_address(self):
        text = "Apply on wuzzuf. Send your CV to careers@valeo.com. (noreply@x.com)"
        assert scorer.hr_email(text) == "careers@valeo.com"

    def test_board_and_noreply_addresses_are_not_hr(self):
        assert scorer.hr_email("support@wuzzuf.net noreply@company.com") == ""

    def test_score_is_clamped(self):
        with patch("core.career.claude.ask", return_value={
                "score": 140, "fit": "x", "missing": [], "level": "entry", "in_egypt": True}):
            assert scorer.score({"title": "Analyst"}, "profile")["score"] == 100


class TestChannel:
    @pytest.mark.parametrize("job,channel", [
        ({"url": "https://wuzzuf.net/jobs/p/1", "hr_email": "hr@a.com"}, "email"),
        ({"url": "https://wuzzuf.net/jobs/p/1"}, "wuzzuf"),
        ({"url": "https://eg.linkedin.com/jobs/view/1"}, "linkedin"),
        ({"url": "https://pwc.wd3.myworkdayjobs.com/x"}, "site"),
    ])
    def test_channel(self, job, channel):
        assert appliers.channel_for(job) == channel


def _seed(*apps):
    for a in apps:
        a.setdefault("status", "ready")
        a.setdefault("channel", appliers.channel_for(a))
        a.setdefault("draft", {"subject": "S", "body": "Dear team, ..."})
        tracker.add(a)
    return apps


class TestPrepareBatch:
    @pytest.fixture(autouse=True)
    def _cv(self, tmp_path):
        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF")
        profile.save({"cv_path": str(cv)})

    def _run(self, jobs, **settings):
        if settings:
            store.update_settings(**settings)
        scores = {j["url"]: j.pop("score") for j in jobs}
        with patch.object(sources, "gather", return_value=jobs), \
             patch.object(scorer, "read_description", return_value="Posting text"), \
             patch.object(scorer, "score", side_effect=lambda job, p: {
                 "score": scores[job["url"]], "fit": "fits", "missing": [],
                 "level": "entry", "in_egypt": True}) as score, \
             patch("core.career.tailor.draft", return_value={"subject": "S", "body": "B"}), \
             patch.object(pipeline, "_nightly_extras", return_value=""), \
             patch.object(pipeline, "_notify"):
            out = pipeline.prepare_batch()
        return out, score

    def test_drafts_the_good_fits_and_skips_the_rest(self):
        out, _ = self._run([_job("Analyst", "Fawry", "https://wuzzuf.net/jobs/p/1", score=85),
                            _job("Analyst", "Nobody", "https://wuzzuf.net/jobs/p/2", score=30)])
        assert sorted(a["status"] for a in tracker.all_apps().values()) == ["ready", "skipped"]
        assert out.startswith("1 applications ready for your review (practice mode")

    def test_big4_comes_first_and_is_capped_per_firm(self):
        jobs = [_job(f"Graduate {i}", "PwC Middle East", f"https://pwc.x/{i}", score=70)
                for i in range(5)]
        jobs.append(_job("Analyst", "Fawry", "https://wuzzuf.net/jobs/p/9", score=95))
        self._run(jobs)
        ready = pipeline.ready_batch()
        assert [a["company_key"] for a in ready] == ["PwC"] * 3 + ["Fawry"]
        capped = [a for a in tracker.with_status("skipped")]
        assert len(capped) == 2 and "this month" in capped[0]["events"][-1]["note"]

    def test_over_the_target_waits_for_tomorrow_without_rescoring(self):
        jobs = [_job(f"Analyst {i}", "Co", f"https://wuzzuf.net/jobs/p/{i}", score=90 - i)
                for i in range(3)]
        self._run(jobs, daily_target=2)
        assert len(tracker.with_status("ready")) == 2
        assert len(tracker.with_status("waiting")) == 1
        _, score = self._run([])
        score.assert_not_called()
        assert len(tracker.with_status("ready")) == 3

    def test_a_job_already_tracked_is_not_scored_again(self):
        _seed(_job("Analyst", "Co", "https://wuzzuf.net/jobs/p/1"))
        _, score = self._run([_job("Analyst", "Co", "https://wuzzuf.net/jobs/p/1")])
        score.assert_not_called()


class TestApprove:
    def test_approve_all_but_the_unticked(self):
        a, b = _seed(_job("A", "Co", "https://wuzzuf.net/jobs/p/1"),
                     _job("B", "Co", "https://wuzzuf.net/jobs/p/2"))
        with patch.object(pipeline, "start_in_background", return_value=True):
            out = pipeline.approve(skip=[b["id"]])
        assert out.startswith("Approved 1, skipped 1.")
        assert tracker.all_apps()[a["id"]]["status"] == "approved"
        assert tracker.all_apps()[b["id"]]["status"] == "skipped"

    def test_approve_only_some(self):
        a, b = _seed(_job("A", "Co", "https://wuzzuf.net/jobs/p/1"),
                     _job("B", "Co", "https://wuzzuf.net/jobs/p/2"))
        with patch.object(pipeline, "start_in_background", return_value=True):
            pipeline.approve(only=[b["id"]])
        assert tracker.all_apps()[a["id"]]["status"] == "skipped"


class TestRunApproved:
    def test_practice_mode_sends_nothing(self):
        (a,) = _seed(_job("A", "Co", "https://wuzzuf.net/jobs/p/1", status="approved"))
        with patch.object(appliers, "apply") as apply, patch.object(pipeline, "_notify"):
            out = pipeline.run_approved(pause=False)
        apply.assert_not_called()
        assert tracker.all_apps()[a["id"]]["status"] == "practice"
        assert out == "1 practice runs (not sent)"

    def test_live_without_a_cv_is_still_practice(self):
        store.update_settings(live=True)
        _seed(_job("A", "Co", "https://wuzzuf.net/jobs/p/1", status="approved"))
        with patch.object(appliers, "apply") as apply, patch.object(pipeline, "_notify"):
            pipeline.run_approved(pause=False)
        apply.assert_not_called()

    def test_live_sends_and_keeps_linkedin_under_its_cap(self, tmp_path):
        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF")
        profile.save({"cv_path": str(cv)})
        store.update_settings(live=True, linkedin_daily_cap=1)
        _seed(_job("A", "Co", "https://eg.linkedin.com/jobs/view/1", status="approved"),
              _job("B", "Co", "https://eg.linkedin.com/jobs/view/2", status="approved"),
              _job("C", "Co", "https://wuzzuf.net/jobs/p/3", status="approved"))
        with patch.object(appliers, "apply", return_value=("applied", "ok")) as apply, \
             patch.object(pipeline, "_notify"):
            pipeline.run_approved(pause=False)
        assert apply.call_count == 2
        assert len(tracker.with_status("approved")) == 1      # the second LinkedIn one waits


class TestAppliers:
    def _app(self, channel, **extra):
        return {"id": "x", "title": "Data Analyst", "company": "Valeo", "url": "https://v.com/j",
                "channel": channel, "draft": {"subject": "Application", "body": "COVER LETTER"},
                **extra}

    def test_a_site_form_is_left_for_mo_to_submit(self):
        task = appliers.browser_task(self._app("site"), {"answers": {"military_status": "Exempted"}})
        assert "do NOT press the final Submit" in task
        assert "Military status (exempted / completed / postponed): Exempted" in task
        assert "COVER LETTER" in task

    def test_browser_results_map_to_statuses(self, tmp_path):
        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF")
        prof = {"cv_path": str(cv), "answers": {}}
        for said, status in [("SUBMITTED - done", "applied"),
                             ("READY FOR REVIEW", "needs_you"),
                             ("BLOCKED: expected salary", "needs_you"),
                             ("Browser task completed (reached max steps).", "failed")]:
            with patch("core.agents.browser_agent.BrowserAgent.run", return_value=said) as run, \
                 patch.object(appliers, "_ledger"):
                assert appliers.apply_in_browser(self._app("wuzzuf"), prof)[0] == status
            assert run.call_args.kwargs["upload_path"] == str(cv)
            assert run.call_args.kwargs["close_tab"] is True

    def test_a_site_form_stays_open_in_comet(self, tmp_path):
        cv = tmp_path / "cv.pdf"
        cv.write_bytes(b"%PDF")
        with patch("core.agents.browser_agent.BrowserAgent.run", return_value="READY FOR REVIEW") as run:
            appliers.apply_in_browser(self._app("site"), {"cv_path": str(cv), "answers": {}})
        assert run.call_args.kwargs["close_tab"] is False

    def test_email_goes_with_the_cv_attached(self, tmp_path):
        cv = tmp_path / "Mohamed CV.pdf"
        cv.write_bytes(b"%PDF-1.4 cv")
        service = MagicMock()
        with patch("tools.gmail_tool.GMAIL_AVAILABLE", True), \
             patch("tools.gmail_tool.get_gmail_service", return_value=service), \
             patch.object(appliers, "_ledger") as ledger:
            status, note = appliers.send_email(self._app("email", hr_email="hr@valeo.com"),
                                               {"cv_path": str(cv)})
        assert status == "applied"
        raw = service.users().messages().send.call_args.kwargs["body"]["raw"]
        import base64
        mime = base64.urlsafe_b64decode(raw).decode()
        assert "hr@valeo.com" in mime and 'filename="Mohamed CV.pdf"' in mime
        ledger.assert_called_once()

    def test_email_without_gmail_fails_cleanly(self):
        with patch("tools.gmail_tool.GMAIL_AVAILABLE", False):
            assert appliers.send_email(self._app("email", hr_email="a@b.com"), {})[0] == "failed"


class TestReplies:
    def _service(self, messages):
        service = MagicMock()
        service.users().messages().list().execute.return_value = {
            "messages": [{"id": m["id"]} for m in messages]}
        by_id = {m["id"]: m for m in messages}
        service.users().messages().get.side_effect = lambda userId, id, **kw: MagicMock(
            execute=MagicMock(return_value={
                "snippet": by_id[id]["snippet"],
                "payload": {"headers": [{"name": "From", "value": by_id[id]["from"]},
                                        {"name": "Subject", "value": by_id[id]["subject"]}]}}))
        return service

    def test_interviews_and_rejections_are_recorded_once(self):
        a, b = _seed(_job("Analyst", "Valeo", "https://wuzzuf.net/jobs/p/1", status="applied"),
                     _job("Analyst", "Fawry", "https://wuzzuf.net/jobs/p/2", status="applied"))
        service = self._service([
            {"id": "m1", "from": "Valeo HR <hr@valeo.com>", "subject": "Interview invitation",
             "snippet": "We'd like to invite you"},
            {"id": "m2", "from": "Fawry Careers", "subject": "Your application",
             "snippet": "Unfortunately we have decided"},
        ])
        with patch("tools.gmail_tool.GMAIL_AVAILABLE", True), \
             patch("tools.gmail_tool.get_gmail_service", return_value=service), \
             patch.object(pipeline, "_notify") as notify:
            first = pipeline.check_replies()
            second = pipeline.check_replies()
        assert tracker.all_apps()[a["id"]]["status"] == "interview"
        assert tracker.all_apps()[b["id"]]["status"] == "rejected"
        assert "INTERVIEW: Analyst at Valeo" in first
        assert second == "No new replies from companies you applied to."
        notify.assert_called_once()


class TestStatus:
    def test_says_practice_mode_and_whats_missing(self):
        _seed(_job("A", "Co", "https://wuzzuf.net/jobs/p/1"))
        out = pipeline.status_text()
        assert out.startswith("Mode: PRACTICE (nothing is sent).")
        assert "1 ready" in out
        assert "military_status" in out


class TestSources:
    def test_gathers_tags_tiers_and_drops_senior_roles(self, monkeypatch):
        monkeypatch.setattr(companies, "premium", lambda: [])
        monkeypatch.setattr(companies, "with_career_sites", lambda: [])
        found = {
            ("Wuzzuf", "data analyst"): [
                {"title": "Data Analyst", "company": "PwC Middle East", "location": "", "posted": "",
                 "url": "https://wuzzuf.net/jobs/p/1", "source": "Wuzzuf"},
                {"title": "Senior Data Analyst", "company": "Fawry", "location": "", "posted": "",
                 "url": "https://wuzzuf.net/jobs/p/2", "source": "Wuzzuf"}],
        }
        with patch("core.agents.job_search_agent.JobSearchAgent._from_source",
                   lambda self, src, term: found.get((src, term), [])):
            jobs = sources.gather({"search_terms": ["data analyst"]})
        assert [(j["title"], j["tier"], j["company_key"]) for j in jobs] == [
            ("Data Analyst", "big4", "PwC")]

    def test_bank_jobs_never_reach_the_batch(self, monkeypatch):
        monkeypatch.setattr(companies, "premium", lambda: [])
        monkeypatch.setattr(companies, "with_career_sites", lambda: [])
        found = [{"title": "Credit Risk Analyst", "company": "CIB Egypt", "location": "",
                  "posted": "", "url": "https://wuzzuf.net/jobs/p/1", "source": "Wuzzuf"},
                 {"title": "Credit Risk Analyst", "company": "Tamweely", "location": "",
                  "posted": "", "url": "https://wuzzuf.net/jobs/p/2", "source": "Wuzzuf"}]
        with patch("core.agents.job_search_agent.JobSearchAgent._from_source",
                   lambda self, src, term: found if src == "Wuzzuf" else []):
            jobs = sources.gather({"search_terms": ["credit risk"]})
        assert [j["company"] for j in jobs] == ["Tamweely"]

    def test_no_bank_is_a_target(self):
        names = {c["name"] for c in companies.all_companies()}
        assert not names & {"CIB", "QNB", "National Bank of Egypt", "Banque Misr", "HSBC"}
        from core.career import programmes
        assert not [p for p in programmes.seeds() if p["company"] == "CIB"]

    def test_a_firms_name_search_keeps_only_its_own_postings(self):
        agent = MagicMock()
        agent._from_source.return_value = [
            {"title": "Auditor", "company": "KPMG Egypt", "url": "u1"},
            {"title": "Accountant", "company": "Some firm hiring ex-KPMG", "url": "u2"},
            {"title": "Clerk", "company": "Other", "url": "u3"}]
        kpmg = next(c for c in companies.big4() if c["name"] == "KPMG")
        out = sources._board_by_name(agent, "Wuzzuf", kpmg)
        assert [j["url"] for j in out] == ["u1", "u2"]

    def test_workday_keeps_egypt_postings(self):
        page = {"total": 2, "jobPostings": [
            {"title": "ETIC Graduate Program", "locationsText": "Cairo",
             "externalPath": "/job/Cairo/ETIC_1", "postedOn": "Posted Today"},
            {"title": "Audit Associate", "locationsText": "Dubai", "externalPath": "/job/Dubai/A_2"}]}
        wd = {"host": "pwc.wd3.myworkdayjobs.com", "tenant": "pwc", "site": "Global_Campus_Careers"}
        firm = next(c for c in companies.big4() if c["name"] == "PwC")
        with patch.object(sources, "_post_json", return_value=page) as post:
            jobs = sources._workday(wd, firm)
        assert post.call_args.args[0] ==             "https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/Global_Campus_Careers/jobs"
        assert [j["url"] for j in jobs] == [
            "https://pwc.wd3.myworkdayjobs.com/en-US/Global_Campus_Careers/job/Cairo/ETIC_1"]

    def test_workday_reads_past_its_first_twenty(self):
        """Workday answers 20 at a time, and says the total only on the first
        page: Valeo's 32 Egypt postings came back as 20."""
        def posting(i):
            return {"title": f"Engineer {i}", "locationsText": "Cairo, Egypt",
                    "externalPath": f"/job/Cairo/E_{i}"}
        pages = [{"total": 32, "jobPostings": [posting(i) for i in range(20)]},
                 {"total": 0, "jobPostings": [posting(i) for i in range(20, 32)]}]
        wd = {"host": "valeo.wd3.myworkdayjobs.com", "tenant": "valeo", "site": "valeo_jobs"}
        firm = companies.match("Valeo")
        with patch.object(sources, "_post_json", side_effect=pages) as post:
            jobs = sources._workday(wd, firm)
        assert len(jobs) == 32 and post.call_count == 2
        assert post.call_args.args[1]["offset"] == 20

    def test_smartrecruiters_postings_in_egypt(self):
        page = {"content": [{"id": "744000151793248", "name": "Delivery Support",
                             "location": {"city": "El Katameya", "country": "eg"},
                             "releasedDate": "2026-09-22T10:00:00.000Z"}]}
        firm = companies.match("talabat")
        with patch.object(sources, "_get_json", return_value=page) as get:
            jobs = sources._smartrecruiters({"company": "DeliveryHero"}, firm)
        assert get.call_args.args[0] ==             "https://api.smartrecruiters.com/v1/companies/DeliveryHero/postings"
        assert get.call_args.args[1]["country"] == "eg"
        assert jobs == [{"title": "Delivery Support", "company": "Talabat",
                         "location": "El Katameya", "posted": "2026-09-22",
                         "url": "https://jobs.smartrecruiters.com/DeliveryHero/744000151793248",
                         "source": "Talabat careers"}]

    def test_amazon_jobs_in_egypt(self):
        page = {"jobs": [{"title": "Business Analyst - MENA", "city": "Cairo",
                          "posted_date": "September 25, 2026",
                          "job_path": "/en/jobs/10560210/business-analyst-mena"}]}
        firm = companies.match("Amazon")
        with patch.object(sources, "_get_json", return_value=page) as get:
            jobs = sources._amazon({"country": "EGY"}, firm)
        assert get.call_args.args[1]["normalized_country_code[]"] == "EGY"
        assert jobs == [{"title": "Business Analyst - MENA", "company": "Amazon",
                         "location": "Cairo", "posted": "September 25, 2026",
                         "url": "https://www.amazon.jobs/en/jobs/10560210/business-analyst-mena",
                         "source": "Amazon careers"}]

    def test_every_firm_with_a_career_site_is_read_not_only_premium(self, monkeypatch):
        """Valeo isn't premium, but its own Workday board is read."""
        monkeypatch.setattr(companies, "premium", lambda: [])
        monkeypatch.setattr(companies, "with_career_sites", lambda: [companies.match("Valeo")])
        read = []
        with patch.object(sources, "_workday", side_effect=lambda wd, firm: read.append(
                (firm["name"], wd["tenant"])) or []),              patch("core.agents.job_search_agent.JobSearchAgent._from_source", return_value=[]):
            sources.gather({"search_terms": []})
        assert read == [("Valeo", "valeo")]

    def test_the_new_boards_are_in_the_list(self):
        boards = {c["name"]: c for c in companies.with_career_sites()}
        for firm in ("Valeo", "Mondelez", "Mastercard", "Sanofi", "Unilever", "GSK",
                     "Novartis", "Visa", "Pfizer"):
            assert boards[firm]["workday"], firm
        assert boards["Talabat"]["smartrecruiters"] == [{"company": "DeliveryHero"}]
        assert boards["Amazon"]["amazon_jobs"] == [{"country": "EGY"}]

    def test_the_global_firms_are_read_too(self):
        boards = {c["name"]: c for c in companies.with_career_sites()}
        assert boards["Oracle"]["oracle_cloud"] and boards["Dell Technologies"]["oracle_cloud"]
        assert boards["Ericsson"]["eightfold"] and boards["PepsiCo"]["jibe"]
        assert boards["BCG"]["phenom"] and boards["Majid Al Futtaim"]["phenom"]
        assert boards["L'Oréal"]["pages"]

    def test_every_kind_of_career_site_has_a_reader(self):
        assert set(sources.READERS) == set(companies.CAREER_SITE_KEYS)

    def test_oracle_cloud_in_egypt(self):
        page = {"items": [{"requisitionList": [
            {"Id": "344587", "Title": "SaaS Consultant", "PrimaryLocation": "CAIRO, Egypt",
             "PostedDate": "2026-09-06"}]}]}
        oc = {"host": "eeho.fa.us2.oraclecloud.com", "site": "CX_45001",
              "job_url": "https://careers.oracle.com/en/sites/jobsearch/job/"}
        with patch.object(sources, "_get_json", return_value=page) as get:
            jobs = sources._oracle_cloud(oc, companies.match("Oracle"))
        # The finder lives in the query string; any params, even {}, make httpx drop it.
        (url,) = get.call_args.args
        assert not get.call_args.kwargs
        assert url.startswith("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/")
        assert "siteNumber=CX_45001" in url and "location=Egypt" in url
        assert jobs == [{"title": "SaaS Consultant", "company": "Oracle",
                         "location": "CAIRO, Egypt", "posted": "2026-09-06",
                         "url": "https://careers.oracle.com/en/sites/jobsearch/job/344587",
                         "source": "Oracle careers"}]

    def test_eightfold_in_egypt(self):
        page = {"data": {"count": 1, "positions": [
            {"name": "Automation Engineer", "positionUrl": "/careers/job/563121777194376",
             "locations": ["Lisbon,Lisboa,Portugal", "Smart Village,Cairo,Egypt"],
             "postedTs": 1789468172}]}}
        ef = {"host": "jobs.ericsson.com", "domain": "ericsson.com"}
        with patch.object(sources, "_get_json", return_value=page) as get:
            jobs = sources._eightfold(ef, companies.match("Ericsson"))
        assert get.call_args.args[1]["location"] == "Egypt"
        assert jobs[0]["title"] == "Automation Engineer"
        assert jobs[0]["location"] == "Smart Village,Cairo,Egypt"
        assert jobs[0]["url"] == "https://jobs.ericsson.com/careers/job/563121777194376"
        assert jobs[0]["posted"].startswith("2026-")

    def test_jibe_reads_every_page_and_keeps_egypt(self):
        def job(slug, country="Egypt"):
            return {"data": {"slug": slug, "title": f"Engineer {slug}", "city": "Giza",
                             "country": country, "posted_date": "2026-09-07T00:00:00+0000"}}
        pages = [{"totalCount": 3, "jobs": [job("1"), job("2", "Morocco")]},
                 {"totalCount": 3, "jobs": [job("3")]}]
        with patch.object(sources, "_get_json", side_effect=pages) as get:
            jobs = sources._jibe({"host": "www.pepsicojobs.com"}, companies.match("PepsiCo"))
        assert get.call_count == 2 and get.call_args.args[1] == {"location": "Egypt", "page": 2}
        assert [j["url"] for j in jobs] == ["https://www.pepsicojobs.com/main/jobs/1",
                                           "https://www.pepsicojobs.com/main/jobs/3"]
        assert jobs[0]["posted"] == "2026-09-07"

    def test_phenom_in_egypt(self):
        found = {"refineSearch": {"data": {"jobs": [
            {"jobId": "58478", "title": "Finance Co-Op/Intern", "country": "Egypt",
             "cityStateCountry": "Cairo, Cairo, Egypt", "postedDate": "2026-06-22T00:00:00.000+0000"}]}}}
        ph = {"host": "careers.bcg.com", "ref": "BCG1US"}
        with patch.object(sources, "_post_json", return_value=found) as post:
            jobs = sources._phenom(ph, companies.match("BCG"))
        assert post.call_args.args[0] == "https://careers.bcg.com/widgets"
        assert post.call_args.args[1]["selected_fields"] == {"country": ["Egypt"]}
        assert jobs == [{"title": "Finance Co-Op/Intern", "company": "BCG",
                         "location": "Cairo, Cairo, Egypt", "posted": "2026-06-22",
                         "url": "https://careers.bcg.com/global/en/job/58478",
                         "source": "BCG careers"}]

    def test_a_careers_page_that_lists_its_jobs(self):
        html = """<a href="/en_US/jobs/JobDetail/Plant-Safety-Manager/234267">Plant Safety Manager</a>
                  <a href="/en_US/jobs/JobDetail/Plant-Safety-Manager/234267">Apply Now</a>
                  <a href="/en_US/jobs/SearchJobs/">Search</a>"""
        pg = {"url": "https://careers.loreal.com/en_US/jobs/SearchJobs/Egypt",
              "job_path": "/en_US/jobs/JobDetail/"}
        with patch.object(sources, "_get_text", return_value=html):
            jobs = sources._page(pg, companies.match("L'Oréal"))
        assert [(j["title"], j["url"]) for j in jobs] == [(
            "Plant Safety Manager",
            "https://careers.loreal.com/en_US/jobs/JobDetail/Plant-Safety-Manager/234267")]


class TestRepliesAfterAnInterview:
    def test_a_later_plain_reply_keeps_the_interview(self):
        (a,) = _seed(_job("Analyst", "Valeo", "https://wuzzuf.net/jobs/p/1", status="interview"))
        service = TestReplies()._service([
            {"id": "m3", "from": "Valeo HR", "subject": "Directions to our office",
             "snippet": "Our address is"}])
        with patch("tools.gmail_tool.GMAIL_AVAILABLE", True), \
             patch("tools.gmail_tool.get_gmail_service", return_value=service), \
             patch.object(pipeline, "_notify"):
            pipeline.check_replies()
        app = tracker.all_apps()[a["id"]]
        assert app["status"] == "interview" and app["reply_ids"] == ["m3"]
