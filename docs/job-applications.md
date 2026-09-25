# Job applications — how the pipeline works

El Fager finds jobs in Egypt, scores each against Mo's CV, drafts a tailored
application for the good fits, and sends only what Mo approves each morning.
Code: `core/career/`, `core/agents/job_search_agent.py`, `tools/career_tool.py`.

```
 02:00 nightly job hunt                       morning                     day
 check replies → gather → score → draft  ──►  review page /jobs  ──►  send (paced)
 (Gmail)         (boards,  (Claude,  (Claude)  Mo unticks, approves   email · Wuzzuf ·
                  Big 4     min 60)                                   LinkedIn · site form
                  sites)
```

## Getting started (say these to El Fager)

1. **"Import my CV from C:\Users\Mohab1\...\CV.pdf"** — reads it into the profile
   the scores and letters come from, and the file that gets attached.
2. **Answer what forms ask:** "my military status is exempted", "my expected
   salary is 15,000", "I can start immediately", "my GPA is 3.2"… `application
   status` lists what's still missing.
3. **"Turn on the nightly job hunt"** — prepares a batch every night at 02:00.
   Or "prepare my applications" to run one now.
4. **Review** at `http://127.0.0.1:8765/jobs` (dashboard token from
   `data/settings.json`). Everything is ticked; untick, press Approve.
5. **"Switch job applications to live"** once the CV is final. Until then it is
   practice mode: approving marks "would have sent", nothing leaves the machine.

## Mo's main goal: an interview at one of the biggest companies in Cairo

- **Every brain turn** carries a one-line job-hunt status (`core/career/focus.py`):
  interviews, the batch waiting for review, programme deadlines, referral notes.
  The persona says the job hunt comes first; the daily briefing opens with it.
- **Morning nudge** (proactive engine, 7–11 AM): what's waiting on him; a
  programme closing within a week also goes to his phone.
- **Graduate programmes** (`core/career/programmes.json`): the Big 4's and top
  companies' programme pages, read weekly by the nightly hunt, for status,
  deadline and whether fresh graduates can apply. "Which graduate programmes
  are open?"
- **Referrals** (`core/career/referrals.py`): each night, up to
  `referrals_per_day` people at target companies (alumni of his university
  first; set it with "my university is ...") with a drafted connection note and
  referral request. They appear on the review page with Copy buttons; Mo sends
  them himself and marks them sent.

## Where jobs come from

- Every search term (`search_terms` in `store.DEFAULTS`) on Wuzzuf, LinkedIn,
  Bayt and Forasna.
- The Big 4 by name on Wuzzuf and LinkedIn, plus their own sites: Deloitte's
  Middle East careers site, PwC's Workday, EY's student and careers sites.
- Target companies (`core/career/companies.json`) go first in the review: Big 4,
  then top employers in Egypt. Add a company there with its aliases.

## How applications go out

| Channel  | When                              | What happens |
|----------|-----------------------------------|--------------|
| email    | the posting gives an HR address   | Gmail from Mo's account, CV attached |
| wuzzuf   | Wuzzuf posting                    | applied in Mo's signed-in Comet, tab closed after |
| linkedin | LinkedIn posting                  | Easy Apply in Comet, max `linkedin_daily_cap`/day |
| site     | anything else (company sites, Bayt, Forasna) | form filled in Comet and left open — **Mo presses Submit** |

Browser applications are spaced 45–120 s apart. Every send goes to the Trust
Ledger. A form question the facts don't cover stops that application as
`needs_you` instead of guessing.

## Guard rails

- **Big 4 cap:** at most `big4_per_firm_per_month` (3) applications per firm per
  30 days — their systems keep every application, and rejections can bar
  re-applying for months.
- **Only Mo approves:** `approve_applications` is refused in background turns,
  so the nightly run can prepare a batch but never send it.
- **Nothing invented:** scores, letters and form answers use only the CV and the
  answers Mo gave.
- **Cost:** scoring and drafting use `claude-opus-5` (`core/career/claude.py`),
  logged under "career" in telemetry; the usage audit shows the daily spend.

## Settings

"Show my application settings" / "set my daily target to 60" / "set the
minimum score to 70". Stored in `data/career/settings.json`.
