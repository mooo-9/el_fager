# El Fager — Speed + Command-Center Plan (2026-07-07)

Execution plan for Fable 5. Planned/reviewed by Claude Code (Opus). El Fager is an
existing, capable agentic OS — this is **fix-and-polish + one new UI**, NOT a rebuild.

---

## Guardrails (read first, every phase)

1. **Do NOT delete tools, subsystems, or files without explicit sign-off from Mo.**
   The Gmail / WhatsApp / Calendar / memory / skills / proactive / scheduler code is
   working infrastructure. If something looks useless, list it in the changelog and
   ASK — never remove it silently.
2. **Surgical changes.** Every changed line traces to a phase goal. Match existing style.
3. **One phase at a time.** Finish a phase, meet its done-criteria, show Mo a working
   demo, wait for review. Do not sprint ahead into the next phase.
4. **Live trading stays gone / off.** Do not reintroduce any trading execution.
5. **Voice-first stays.** Ctrl+Space / "hey fager" voice loop is the primary interface;
   the new dashboard is an *addition*, not a replacement.
6. Preserve `EL_FAGER_TEST_MODE` isolation — test traffic never touches prod data.

## How Fable 5 should work each phase

- State a 3-5 step plan with a `verify:` check per step before writing code.
- Build → run `python main.py` → confirm it launches and the changed surface works.
- Keep a short changelog of what changed and (separately) anything you *want* to delete.
- Report speed numbers where the phase is about speed.

---

## Phase 0 — Runtime audit + speed quick-wins (do first, small)

The static audit is done; what's missing is knowing which integrations actually work
at runtime (auth tokens, API keys). Also grab the free speed wins.

Steps:
1. Launch `python main.py`, confirm tray + overlay come up. Capture cold-start time.
   → verify: app runs, note seconds to first paint.
2. For each key integration, run its read path once and record WORKS / BROKEN / NEEDS-AUTH:
   Gmail (`tools/gmail_tool.py`), Calendar (`calendar_tool.py`), WhatsApp send-preview
   (`whatsapp_tool.py`), News (`news_tool.py`), Todoist (`todoist_tool.py`),
   web search (`web_tool.py`), files/system, memory query.
   → verify: a written status table Mo can read.
3. **Model bump:** `data/settings.json` pins `claude-sonnet-4-6` (outdated). Switch to
   `claude-sonnet-5` for quality turns, and wire `claude-haiku-4-5-20251001` as the
   fast path for short/simple turns. Make the model id configurable, don't hardcode.
   → verify: a normal voice turn returns noticeably faster; answers still correct.
4. Confirm `GROQ_API_KEY` is set so Whisper STT runs in the cloud (skips the ~1.6GB
   local model + CPU transcription). If unset, tell Mo — it's a big latency lever.
   → verify: transcription latency measured with vs without.

Done-criteria: integration status table delivered; model upgraded; one measured
before/after on turn latency.

---

## Phase 1 — Speed (make every turn feel instant)

Target: text turn < 1s to first token; voice turn perceptibly snappy end-to-end.

Steps:
1. Profile a full voice turn (mic→STT→brain→first TTS sentence). Log per-stage ms.
   → verify: a stage-by-stage timing breakdown; identify the top 2 costs.
2. Attack the top costs. Likely candidates (confirm before changing):
   - Route short/simple turns to Haiku 4.5; reserve Sonnet 5 for tool-heavy turns.
   - Tighten `_select_tools` groups so fewer tool schemas ship per turn.
   - Verify prompt caching is actually hitting (check the token log from W2).
   - Reduce `FOLLOWUP_WINDOW_SEC` / silence window if it adds dead air.
   → verify: re-run the Phase-1 profile; each targeted stage is faster.
3. Do NOT split the 6127-line `brain.py` yet — that's risky and not required for speed.
   Only note it as future cleanup.

### Baseline — 2026-08-18

Ten turns through the real pipeline (`EL_FAGER_PROFILE=1`), five short and
five tool-heavy. Milliseconds from the start of the turn.

| stage | short (median / p90) | tool-heavy (median / p90) |
|---|---|---|
| first_token | 1,978 / 2,999 | 4,056 / 5,771 |

Tool cost, median per call:

| tool | ms |
|---|---|
| list_emails | 2,774 |
| list_calendar_events | 1,396 |
| list_tasks | 1,202 |
| get_weather | 641 |
| get_news | 540 |
| remember_fact | 5 |

Cache over the same 24 API calls: 19 read, **4 wrote, 51,615 tokens written**.

**The top two costs are not where they were assumed to be.**

1. *A single tool call*, not the model. `list_emails` at 2.8 s and
   `list_calendar_events` at 1.4 s dominate any turn that touches them —
   on one measured turn the calendar lookup was 42% of the whole 8 s.
2. *Cache writes.* 51,615 tokens re-cached across 24 calls, which is the
   `tools` array changing inside the cached prefix (see Phase 1 step 2).

The ChromaDB memory query, long suspected of costing time on the turn path,
measures **0.0 ms**. It is not a target.

**first_audio / last_audio are not recorded here.** The run exhausted Groq
Orpheus's free tier mid-way — 3,600 tokens per day — and the remaining turns
fell back to Edge TTS behind 429 retries, so those stages measured the rate
limit rather than the synthesis. Worth knowing independently: on the free
tier the neural voice lasts a few dozen sentences a day and then silently
degrades.

### What was fixed, and what was measured and left alone

| Change | Measured effect |
|---|---|
| Select tools once per turn, stable across a conversation | cache writes 4/24 → 2/30 calls; tokens re-cached 2,151 → 898 per call |
| Word-boundary trigger matching | three verified false positives gone; 44 → 34 tools on an unrelated phrase |
| One shared Groq client | 3,145 ms → ~0 ms of client construction on a five-sentence reply |

Measured and **not** changed, because the numbers did not justify it:

- **ChromaDB memory query** — 0.0 ms on the turn path.
- **Re-reading `data/settings.json`** — 0.042 ms per read; ten a turn is 0.4 ms.
  Caching it would buy a staleness bug and no time.

Still outstanding: the fixed delays (`END_SILENCE_SEC = 1.0`, the 800 ms
re-arm timer) have not been profiled against real speech, because that needs
a microphone rather than a typed turn.

Done-criteria: measured, reproducible latency improvement on both text and voice turns,
with before/after numbers. No regression in tool-calling correctness.

---

## Phase 2 — Hybrid command center (the one genuinely NEW piece)

Mo's biggest UI gap: there's no unified "today at a glance" surface. Build it.

Architecture (hybrid, per Mo's choice):
- **Native Qt shell** for the window frame + instant open (reuse `ui/theme.py` palette,
  reuse patterns from `ui/overlay.py`). The shell must open instantly — no QWebEngine
  on the open path.
- **Web panel (QWebEngine) only for the rich visual cards** (rings/sparklines/anim),
  loaded lazily and populated from local data — like the existing `ui/hud_web.py`.

Content — a single scrollable command center showing today:
- Top: greeting + the daily briefing (`core/briefing.py` already generates one).
- Calendar today (`calendar_tool.py`), top tasks (`todoist_tool.py`), unread/priority
  mail summary (`gmail_tool.py`), news brief (`news_tool.py`), health snapshot
  (`health_tool.py`).
- One global command bar (type or talk) that dispatches into `brain.chat` — reuse the
  overlay's input + pipeline; don't build a second brain path.
- Every outbound action (send mail/WhatsApp, create event) keeps the existing
  stage → preview → confirm flow. No new send path.

Steps:
1. Build the native shell + command bar; wire the command bar to the existing brain
   pipeline. → verify: opens instantly, typing a command gets a real answer.
2. Add data cards one at a time, each pulling from the tool that already exists, each
   backed by cached/last-known data so the view paints before live fetches finish.
   → verify: each card shows real data and never blocks the paint.
3. Lazy-load the web visual panel; keep it off the open path.
   → verify: cold open time unchanged vs shell-only.

Done-criteria: opening the command center feels instant and shows Mo's real day
(calendar, tasks, mail, news, health) with a working command bar. No feature that
already worked is broken.

---

## Phase 3 — Integration hardening (only what Phase 0 flagged BROKEN/NEEDS-AUTH)

For each integration marked broken/needs-auth in Phase 0: fix the auth flow, add a
clear one-time setup path, and confirm the read + (where relevant) the staged-send
path works. Do not add new integrations Mo didn't ask for.

Done-criteria: every integration surfaced on the command center returns real data.

---

## Phase 4 — Learning / profile polish (lightweight, last)

The observe→mine→skills backbone already exists. Don't rebuild it. Just make sure:
- The command center reflects what El Fager has learned (top facts, active skills,
  proposed automations) so the "it's getting to know me" promise is visible.
- The private profile/memory stays local and human-readable.

Done-criteria: Mo can see, on the dashboard, what El Fager knows and what it proposes.

---

## The prompt to give Fable 5 (per phase)

> You are executing ONE phase of the El Fager plan at `docs/rebuild-plan-2026-07-07.md`.
> Read the Guardrails and "How Fable 5 should work each phase" sections first, then do
> **only Phase N**. El Fager is a large working agentic OS — fix and polish, do not
> delete tools or subsystems without asking. State your step plan with verify checks,
> build it, run `python main.py` to confirm it works, then report a changelog + the
> phase's done-criteria results and stop. Do not start the next phase.

Replace `Phase N` each time. Review between phases before releasing the next.
